"""
generate_metadata.py

命名規約に従ったファイル名から metadata scaffold を生成し、
processing/metadata-ready/ に .metadata.json として保存する。

今フェーズでは OCR 内容解析は行わない。
ファイル名を解析して空の metadata scaffold を生成するのみ。
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# tag_utils は同ディレクトリにある
_SCRIPTS_DIR = Path(__file__).parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
from tag_utils import generate_tags, merge_tags    # noqa: E402
from summary_utils import generate_summary         # noqa: E402

PROCESSING_DIR = Path(__file__).parent.parent / "processing"
RENAMED_DIR = PROCESSING_DIR / "renamed"
METADATA_READY_DIR = PROCESSING_DIR / "metadata-ready"
TEMPLATES_DIR = Path(__file__).parent.parent / "templates"

AMOUNT_PATTERN = re.compile(r"^(\d+)JPY$")

PAYMENT_METHODS = {
    "AMEX", "SMBC", "RakutenCard", "PayPay",
    "Cash", "BankTransfer", "DirectDebit", "Suica", "Other",
}

RETENTION_YEARS = {
    "Tax": 7,
    "Contract": 7,
    "Work": 5,
    "Insurance": 5,
    "Asset": 10,
    "Medical": 5,
    "School": 3,
    "Government": 7,
    "Finance": 5,
    "Receipt": 3,
    "Utility": 3,
    "Other": 3,
}

# document が [要確認] プレースホルダーの場合に status を document-unknown に変換
DOCUMENT_PLACEHOLDER_PATTERN = re.compile(r"^\[.*要確認.*\]$")


def load_template() -> dict:
    """templates/metadata_template.json を読み込んで返す。"""
    template_path = TEMPLATES_DIR / "metadata_template.json"
    with open(template_path, encoding="utf-8") as f:
        return json.load(f)


def parse_filename(filename: str) -> dict:
    """
    命名規約のファイル名を解析してフィールドを抽出する。

    フォーマット: YYYYMMDD-Category-Document-[Counterparty]-[AmountJPY]-[PaymentMethod].pdf

    Returns:
        dict with keys: date, category, document, counterparty, amount_jpy, payment_method
    """
    stem = Path(filename).stem
    parts = stem.split("-")

    result = {
        "date": "",
        "category": "",
        "document": "",
        "counterparty": "",
        "amount_jpy": None,
        "payment_method": "",
    }

    if len(parts) >= 1 and re.match(r"^\d{8}$", parts[0]):
        result["date"] = parts[0]
    if len(parts) >= 2:
        result["category"] = parts[1]
    if len(parts) >= 3:
        result["document"] = parts[2]

    for part in parts[3:]:
        amount_match = AMOUNT_PATTERN.match(part)
        if amount_match:
            result["amount_jpy"] = int(amount_match.group(1))
        elif part in PAYMENT_METHODS:
            result["payment_method"] = part
        elif not result["counterparty"]:
            result["counterparty"] = part

    return result


def format_event_date(date_str: str) -> str:
    """YYYYMMDD を YYYY-MM-DD に変換する。変換できない場合はそのまま返す。"""
    if re.match(r"^\d{8}$", date_str):
        return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
    return date_str


def calc_retention(category: str) -> str:
    """Category から保存期間の説明を返す。"""
    years = RETENTION_YEARS.get(category, 3)
    return f"{years}年"


def calc_discard_date(issue_date: str, retention: str) -> str:
    """
    issue_date (YYYY-MM-DD) と retention ("N年") から廃棄予定日を計算する。
    issue_date が不正の場合は空文字を返す。
    """
    if not issue_date or len(issue_date) < 4:
        return ""
    m = re.match(r"(\d+)年", retention)
    if not m:
        return ""
    years = int(m.group(1))
    try:
        y, mo, d = int(issue_date[:4]), int(issue_date[5:7]), int(issue_date[8:10])
        return f"{y + years:04d}-{mo:02d}-{d:02d}"
    except (ValueError, IndexError):
        return ""


def generate_metadata(
    filename: str,
    source_filename: Optional[str] = None,
    ocr_data: Optional[dict] = None,
) -> dict:
    """
    ファイル名から metadata scaffold を生成する（schema v1）。

    Args:
        filename:        命名規約に従ったファイル名
        source_filename: inbox での元ファイル名（分かる場合）
        ocr_data:        process_inbox.py からの OCR 結果（confidence, ocr_engine,
                         normalized_pdf, original_extension, split_* など）

    Returns:
        metadata dict（schema v1 に準拠）
    """
    parsed = parse_filename(filename)
    template = load_template()
    ocr = ocr_data or {}

    issue_date = format_event_date(parsed["date"])
    category = parsed["category"]
    retention = calc_retention(category)
    discard_date = calc_discard_date(issue_date, retention)

    # [Document要確認] プレースホルダーを status に分離
    document = parsed["document"]
    if DOCUMENT_PLACEHOLDER_PATTERN.match(document):
        document = ""
        initial_status = "document-unknown"
    else:
        initial_status = ocr.get("status", "renamed")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    metadata = dict(template)
    # --- v1 必須フィールド ---
    metadata["schema_version"] = "v1"
    metadata["file_name"] = filename
    metadata["source_file"] = source_filename or ocr.get("source_file", "")
    metadata["file_type"] = "PDF"
    metadata["original_extension"] = ocr.get("original_extension", Path(filename).suffix)
    metadata["normalized_pdf"] = bool(ocr.get("normalized_pdf", False))
    metadata["category"] = category
    metadata["document"] = document
    metadata["counterparty"] = parsed["counterparty"]
    metadata["issue_date"] = issue_date
    metadata["amount_jpy"] = parsed["amount_jpy"]
    metadata["payment_method"] = parsed["payment_method"]
    metadata["retention"] = retention
    metadata["discard_date"] = discard_date
    metadata["confidence"] = ocr.get("confidence", None)
    metadata["ocr_engine"] = ocr.get("ocr_engine", "vision" if ocr else "filename")
    metadata["status"] = initial_status
    # --- 任意フィールド ---
    metadata["archive_path"] = ocr.get("archive_path", "")
    metadata["export_path"] = ocr.get("export_path", "")
    # tags: OCR由来タグと自動生成タグをマージして初期付与
    base_tags: list = ocr.get("tags", [])
    auto_tags = generate_tags(metadata)
    metadata["tags"] = merge_tags(base_tags, auto_tags)
    metadata["notion_registered"] = False
    metadata["dropbox_exported"] = False
    metadata["notes"] = ""
    metadata["summary"] = generate_summary(metadata)
    metadata["created_at"] = now
    metadata["updated_at"] = now
    # --- split PDF フィールド ---
    if ocr.get("split_pdf"):
        metadata["split_pdf"] = True
        metadata["split_source"] = ocr.get("split_source", "")
        metadata["split_page"] = ocr.get("split_page")
        metadata["split_total"] = ocr.get("split_total")

    # 後方互換フィールド（既存ツールが参照している可能性があるもの）
    metadata["title"] = document or parsed["document"] or ""

    return metadata


def save_metadata(metadata: dict, output_dir: Path) -> Path:
    """metadata を output_dir に .metadata.json として保存する。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(metadata["file_name"]).stem
    output_path = output_dir / f"{stem}.metadata.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)
    return output_path


def run() -> None:
    """
    processing/renamed/ を走査し、metadata がない PDF に対して scaffold を生成する。
    出力先: processing/metadata-ready/
    """
    if not RENAMED_DIR.exists():
        print(f"renamed/ not found: {RENAMED_DIR}")
        return

    pdf_files = sorted(
        f for f in RENAMED_DIR.iterdir()
        if f.is_file() and f.suffix.lower() == ".pdf"
    )

    if not pdf_files:
        print("No PDF files found in processing/renamed/")
        print()
        print("--- Demo mode: running with sample filename ---")
        _demo()
        return

    print(f"=== generate_metadata — {len(pdf_files)} PDF(s) found in renamed/ ===")
    print()

    for pdf in pdf_files:
        existing = METADATA_READY_DIR / f"{pdf.stem}.metadata.json"
        if existing.exists():
            print(f"  [SKIP] {pdf.name} — metadata already exists")
            continue

        metadata = generate_metadata(pdf.name)
        out_path = save_metadata(metadata, METADATA_READY_DIR)
        print(f"  [OK]   {pdf.name}")
        print(f"         → {out_path.relative_to(Path(__file__).parent.parent)}")


def _demo() -> None:
    """renamed/ が空の場合にサンプルで動作確認する。"""
    samples = [
        "20260517-Expense-会食-焼肉きんぐ-12000JPY-AMEX.pdf",
        "20260407-Government-履歴事項全部証明書-B8E.pdf",
        "20260226-Work-業務完了通知書.pdf",
    ]

    print()
    for filename in samples:
        metadata = generate_metadata(filename)
        out_path = save_metadata(metadata, METADATA_READY_DIR)
        print(f"  [DEMO] {filename}")
        print(f"         → {out_path.relative_to(Path(__file__).parent.parent)}")
        print(f"         category: {metadata['category']} / retention: {metadata['retention']}")
        if metadata["amount_jpy"]:
            print(f"         amount: {metadata['amount_jpy']} JPY / method: {metadata['payment_method']}")
        print()


if __name__ == "__main__":
    run()
