"""
ocr_extract.py

macOS Vision Framework (Swift) を使った PDF/画像 OCR と、
OCR テキストからの rename フィールド推定モジュール。

依存: swiftc (macOS 標準), sips (macOS 標準)
外部 pip パッケージは不要。
"""

import re
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

SCRIPTS_DIR = Path(__file__).parent
SWIFT_SOURCE = SCRIPTS_DIR / "vision_ocr.swift"
OCR_BINARY = SCRIPTS_DIR / "vision_ocr"

# ---------------------------------------------------------------------------
# Category keyword mapping (優先度順)
# ---------------------------------------------------------------------------
CATEGORY_KEYWORDS: List[tuple] = [
    ("Work",       ["業務完了通知書", "完了通知書", "作業完了", "業務報告", "業務委託"]),
    ("Contract",   ["御見積書", "見積書", "発注書", "請求書", "納品書", "契約書"]),
    ("Government", ["履歴事項全部証明書", "証明書", "変更通知書", "通告制度",
                    "登記", "行政", "許可証", "所在名称変更", "適用事業所"]),
    ("Tax",        ["住民税", "所得税", "固定資産税", "課税通知", "確定申告", "納税通知"]),
    ("Insurance",  ["保険証", "保険", "被保険者"]),
    ("Medical",    ["診療明細書", "診療", "処方箋", "クリニック", "病院", "医療費"]),
    ("School",     ["成績", "通知表", "学校", "入学", "授業料"]),
    ("Utility",    ["使用水量", "水道料金", "電気料金", "ガス料金", "通信費", "下水道"]),
    ("Receipt",    ["領収書", "レシート"]),
    ("Expense",    ["会食", "交通費", "宿泊費"]),
    ("Other",      []),  # fallback
]

# ---------------------------------------------------------------------------
# 日本語元号 → 西暦変換
# ---------------------------------------------------------------------------
ERA_TABLE = {
    "令和": 2018,
    "平成": 1988,
    "昭和": 1925,
    "大正": 1911,
}

DATE_PATTERNS = [
    re.compile(r"(令和|平成|昭和|大正)(\d{1,2})年\s*(\d{1,2})月\s*(\d{1,2})日"),
    re.compile(r"(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日"),
    re.compile(r"(\d{4})/(\d{1,2})/(\d{1,2})"),
    re.compile(r"(\d{4})-(\d{2})-(\d{2})"),
]

AMOUNT_PATTERN = re.compile(r"(\d{1,3}(?:,\d{3})*)\s*円")
AMOUNT_YEN_PATTERN = re.compile(r"¥\s*(\d{1,3}(?:,\d{3})*)")

COMPANY_PATTERNS = [
    re.compile(r"株式会社[\s　]*([\w぀-鿿＀-￯]+)"),
    re.compile(r"([\w぀-鿿＀-￯]+)[\s　]*株式会社"),
    re.compile(r"合同会社[\s　]*([\w぀-鿿＀-￯]+)"),
]


# ---------------------------------------------------------------------------
# OCR binary management
# ---------------------------------------------------------------------------

def ensure_ocr_binary() -> bool:
    """Swift OCR バイナリが存在しなければコンパイルする。利用可否を返す。"""
    if OCR_BINARY.exists():
        return True
    if not SWIFT_SOURCE.exists():
        return False
    result = subprocess.run(
        ["swiftc", str(SWIFT_SOURCE), "-o", str(OCR_BINARY)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return False
    return OCR_BINARY.exists()


def _run_vision_ocr(image_path: Path) -> str:
    """Vision OCR バイナリを実行してテキストを返す。"""
    result = subprocess.run(
        [str(OCR_BINARY), str(image_path)],
        capture_output=True, text=True, timeout=30,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _pdf_first_page_to_image(pdf_path: Path) -> Optional[Path]:
    """sips を使って PDF の1ページ目を JPEG に変換する。"""
    tmp = Path(tempfile.mktemp(suffix=".jpg"))
    result = subprocess.run(
        ["sips", "-s", "format", "jpeg", str(pdf_path), "--out", str(tmp)],
        capture_output=True, text=True,
    )
    if result.returncode == 0 and tmp.exists():
        return tmp
    return None


def extract_text(file_path: Path) -> str:
    """
    PDF または画像ファイルから OCR テキストを抽出する。

    Returns:
        抽出テキスト。OCR 不可の場合は空文字。
    """
    if not ensure_ocr_binary():
        return ""

    ext = file_path.suffix.lower()
    try:
        if ext == ".pdf":
            img = _pdf_first_page_to_image(file_path)
            if img:
                text = _run_vision_ocr(img)
                img.unlink(missing_ok=True)
                return text
        elif ext in {".png", ".jpg", ".jpeg"}:
            return _run_vision_ocr(file_path)
    except Exception:
        pass
    return ""


# ---------------------------------------------------------------------------
# Heuristic parsing of OCR text
# ---------------------------------------------------------------------------

def _extract_date(text: str, fallback_filename: str) -> str:
    """OCR テキストから日付を抽出し YYYYMMDD 形式で返す。"""
    for pat in DATE_PATTERNS:
        m = pat.search(text)
        if m:
            groups = m.groups()
            if len(groups) == 4:
                era, year_n, month, day = groups
                base = ERA_TABLE.get(era, 0)
                year = base + int(year_n)
            elif len(groups) == 3:
                year, month, day = groups
                year = int(year)
            else:
                continue
            try:
                return f"{int(year):04d}{int(month):02d}{int(day):02d}"
            except (ValueError, TypeError):
                continue

    # filename の先頭8桁にフォールバック
    m = re.match(r"^(\d{8})", fallback_filename)
    return m.group(1) if m else ""


def _extract_category(text: str) -> str:
    """キーワードマッピングで Category を推定する。"""
    for category, keywords in CATEGORY_KEYWORDS:
        for kw in keywords:
            if kw in text:
                return category
    return "Other"


def _extract_counterparty(text: str, bracket_tags: List[str]) -> str:
    """
    OCR テキストから発行元・取引先を推定する。
    括弧タグがあればそちらを優先。
    """
    if bracket_tags:
        return bracket_tags[0]

    for pat in COMPANY_PATTERNS:
        m = pat.search(text)
        if m:
            name = m.group(1).strip()
            if 1 < len(name) < 20:
                return name

    # 「御中」の直前の行を相手先と見なす
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if "御中" in line and i > 0:
            candidate = lines[i - 1].strip()
            candidate = re.sub(r"株式会社|合同会社|有限会社", "", candidate).strip()
            if 1 < len(candidate) < 20:
                return candidate

    return ""


def _extract_amount(text: str) -> Optional[int]:
    """OCR テキストから金額（円）を抽出する。最大値を返す。"""
    amounts = []
    for pat in [AMOUNT_PATTERN, AMOUNT_YEN_PATTERN]:
        for m in pat.finditer(text):
            try:
                val = int(m.group(1).replace(",", ""))
                amounts.append(val)
            except ValueError:
                pass
    return max(amounts) if amounts else None


def _extract_document_name(text: str, category: str) -> str:
    """カテゴリに関連する文書名キーワードを OCR テキストから探す。"""
    doc_keywords = {
        "Work": ["業務完了通知書", "完了通知書", "業務報告書"],
        "Contract": ["御見積書", "見積書", "請求書", "発注書", "納品書"],
        "Government": ["履歴事項全部証明書", "変更通知書", "適用事業所所在名称変更通知書",
                       "交通反則通告制度案内"],
        "Tax": ["住民税通知書", "課税通知書", "納税通知書"],
        "Insurance": ["保険証券", "保険更新通知"],
        "Medical": ["診療明細書", "領収書", "処方箋"],
        "School": ["成績通知", "通知表"],
        "Utility": ["使用水量のお知らせ", "電気ご使用量のお知らせ", "ガス使用量のお知らせ"],
        "Receipt": ["領収書"],
        "Other": [],
    }
    for kw in doc_keywords.get(category, []):
        if kw in text:
            return kw
    return ""


def parse_rename_fields(
    ocr_text: str,
    source_filename: str,
    bracket_tags: Optional[List[str]] = None,
) -> Dict:
    """
    OCR テキストとソースファイル名から rename フィールドを推定する。

    優先順位:
    - 日付: ファイル名の YYYYMMDD を最優先。日付のみファイル名のときのみ OCR 日付を使用
    - Category: OCR テキスト → ファイル名テキストの順で判定
    - Document: OCR テキスト → ファイル名から推定
    - Counterparty: Bracket tag → OCR テキスト
    """
    tags = bracket_tags or []

    # --- 日付: ファイル名を最優先 ---
    filename_date = re.match(r"^(\d{8})", source_filename)
    stem = Path(source_filename).stem
    if filename_date and stem != filename_date.group(1):
        # ファイル名に日付 + 他のテキストがある → ファイル名の日付を使う
        date = filename_date.group(1)
    else:
        # 日付のみファイル名 or 日付なし → OCR から取得
        date = _extract_date(ocr_text, source_filename)

    # --- Category: OCR → ファイル名順 ---
    combined_text = ocr_text + " " + source_filename
    category = _extract_category(combined_text)

    # --- Counterparty ---
    counterparty = _extract_counterparty(ocr_text, tags)

    # --- Amount ---
    amount_jpy = _extract_amount(ocr_text)

    # --- Document: OCR → ファイル名推定 ---
    document = _extract_document_name(combined_text, category)
    if not document:
        # ファイル名の日付/タグを除いた部分を document として使う
        doc_from_name = re.sub(r"【[^】]+】", "", stem)
        doc_from_name = re.sub(r"^\d{8}[_\-]?", "", doc_from_name).strip("-_")
        if doc_from_name:
            document = doc_from_name[:30]

    return {
        "date": date,
        "category": category,
        "document": document,
        "counterparty": counterparty,
        "amount_jpy": amount_jpy,
        "payment_method": "",
    }


def build_ocr_rename_candidate(fields: Dict) -> str:
    """
    parse_rename_fields の結果から rename 候補ファイル名を生成する。
    Category が確定していない部分は [要確認] を残す。
    """
    date = fields.get("date") or "[日付不明]"
    category = fields.get("category") or "Other"
    document = fields.get("document") or "[Document要確認]"
    counterparty = fields.get("counterparty", "")
    amount_jpy = fields.get("amount_jpy")
    payment = fields.get("payment_method", "")

    parts = [date, category, document]
    if counterparty:
        parts.append(counterparty)
    if amount_jpy:
        parts.append(f"{amount_jpy}JPY")
    if payment:
        parts.append(payment)

    return "-".join(parts) + ".pdf"
