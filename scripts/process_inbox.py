"""
process_inbox.py

inbox をスキャンし、分析・rename候補提示・safe copy を行う。

デフォルト動作は --dry-run（分析と表示のみ）。
--apply を明示した場合のみ、review不要ファイルを processing/renamed/ へコピーし
metadata scaffold を自動生成する。

Usage:
    python scripts/process_inbox.py            # --dry-run と同じ
    python scripts/process_inbox.py --dry-run  # 分析のみ（ファイルは変更しない）
    python scripts/process_inbox.py --apply    # renamed/ へコピー + metadata 生成
"""

import argparse
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).parent.parent
INBOX_DIR = REPO_ROOT / "inbox"
PROCESSING_DIR = REPO_ROOT / "processing"
RENAMED_DIR = PROCESSING_DIR / "renamed"
METADATA_READY_DIR = PROCESSING_DIR / "metadata-ready"
REVIEW_DIR = PROCESSING_DIR / "review-required"
OCR_ERROR_DIR = PROCESSING_DIR / "ocr-error"
LOGS_DIR = REPO_ROOT / "logs"

sys.path.insert(0, str(Path(__file__).parent))
from normalize_documents import (
    scan_inbox,
    detect_garbled,
    extract_date,
    extract_bracket_tags,
    classify_file,
)
from generate_metadata import generate_metadata, save_metadata, METADATA_READY_DIR as META_DIR

MAX_STEM_LENGTH = 80
# 日付プレフィクス + アンダースコア／スペース を除去するパターン
DATE_PREFIX_PATTERN = re.compile(r"^\d{8}[_\-\s]?")
BRACKET_TAG_PATTERN = re.compile(r"【[^】]+】")
UNSAFE_CHARS_PATTERN = re.compile(r'[/\\:*?"<>|\s]')


# ---------------------------------------------------------------------------
# Analysis helpers
# ---------------------------------------------------------------------------

def is_date_only(name: str) -> bool:
    return bool(re.match(r"^\d{8}$", Path(name).stem))


def is_too_long(name: str) -> bool:
    return len(Path(name).stem) > MAX_STEM_LENGTH


def extract_document_portion(name: str) -> str:
    """
    既存ファイル名から date prefix と bracket tags を除いた "document" 部分を抽出する。
    例: '20260226_業務完了通知書.pdf' → '業務完了通知書'
        '20260401【B8E】適用事業所所在名称変更通知書.pdf' → '適用事業所所在名称変更通知書'
    """
    stem = Path(name).stem
    stem = BRACKET_TAG_PATTERN.sub("", stem)
    stem = DATE_PREFIX_PATTERN.sub("", stem)
    stem = UNSAFE_CHARS_PATTERN.sub("-", stem)
    stem = re.sub(r"-{2,}", "-", stem).strip("-")
    return stem


def build_best_effort_name(name: str) -> str:
    """
    既存ファイル名から命名規約に近いベストエフォート名を生成する。
    Category は人間が後で補完するため含めない。

    例: '20260226_業務完了通知書.pdf' → '20260226-業務完了通知書.pdf'
        '20260401【B8E】適用事業所所在名称変更通知書.pdf' → '20260401-適用事業所所在名称変更通知書-B8E.pdf'
    """
    date = extract_date(name)
    if not date:
        return name

    tags = extract_bracket_tags(name)
    doc = extract_document_portion(name)

    parts = [date]
    if doc:
        parts.append(doc)
    if tags:
        parts.append(tags[0])

    return "-".join(parts) + ".pdf"


def analyze_file(path: Path) -> Dict:
    """ファイルを分析してフラグと rename 情報を返す。"""
    name = path.name
    kind = classify_file(path)
    date = extract_date(name)
    tags = extract_bracket_tags(name)
    garbled = detect_garbled(name)
    date_only = is_date_only(name)
    too_long = is_too_long(name)

    warnings: List[str] = []
    if garbled:
        warnings.append("OCR 文字化けの可能性あり")
    if date_only:
        warnings.append("ファイル名が日付のみ — 内容不明")
    if too_long:
        warnings.append(f"ファイル名が長すぎる ({len(Path(name).stem)} 文字)")
    if not date:
        warnings.append("日付が読み取れない")
    if kind == "IMAGE":
        warnings.append("画像ファイル — PDF 化が必要")

    needs_ocr_review = garbled
    needs_review = bool(warnings)

    rename_hint: str
    best_effort_name: Optional[str]

    if date:
        tag_suffix = f"-{tags[0]}" if tags else ""
        rename_hint = f"{date}-[Category]-[Document]{tag_suffix}.pdf"
        best_effort_name = build_best_effort_name(name) if not needs_review else None
    else:
        rename_hint = "(日付不明: 要確認)"
        best_effort_name = None

    return {
        "path": path,
        "name": name,
        "kind": kind,
        "date": date,
        "tags": tags,
        "garbled": garbled,
        "date_only": date_only,
        "too_long": too_long,
        "needs_review": needs_review,
        "needs_ocr_review": needs_ocr_review,
        "rename_hint": rename_hint,
        "best_effort_name": best_effort_name,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Safe copy helpers
# ---------------------------------------------------------------------------

def resolve_dest_path(dest_dir: Path, filename: str) -> Path:
    """
    コピー先に同名ファイルが存在する場合、連番サフィックスを付与して返す。
    例: foo.pdf → foo-001.pdf → foo-002.pdf
    """
    candidate = dest_dir / filename
    if not candidate.exists():
        return candidate

    stem = Path(filename).stem
    suffix = Path(filename).suffix
    for i in range(1, 1000):
        new_name = f"{stem}-{i:03d}{suffix}"
        candidate = dest_dir / new_name
        if not candidate.exists():
            return candidate

    raise RuntimeError(f"Could not find a free filename for {filename} after 999 attempts")


def copy_to_renamed(src: Path, dest_name: str) -> Path:
    """inbox のファイルを renamed/ にコピーする（元ファイルは残す）。"""
    RENAMED_DIR.mkdir(parents=True, exist_ok=True)
    dest = resolve_dest_path(RENAMED_DIR, dest_name)
    shutil.copy2(src, dest)
    return dest


# ---------------------------------------------------------------------------
# Report writers
# ---------------------------------------------------------------------------

def write_review_report(items: List[Dict], timestamp: str) -> Path:
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REVIEW_DIR / f"review-report-{timestamp}.json"
    report = {
        "generated_at": datetime.now().isoformat(),
        "count": len(items),
        "files": [
            {"name": item["name"], "warnings": item["warnings"], "rename_hint": item["rename_hint"]}
            for item in items
        ],
    }
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    return report_path


def write_ocr_error_report(items: List[Dict], timestamp: str) -> Path:
    OCR_ERROR_DIR.mkdir(parents=True, exist_ok=True)
    report_path = OCR_ERROR_DIR / f"ocr-error-report-{timestamp}.json"
    report = {
        "generated_at": datetime.now().isoformat(),
        "count": len(items),
        "files": [
            {"name": item["name"], "warnings": item["warnings"]}
            for item in items
        ],
    }
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    return report_path


# ---------------------------------------------------------------------------
# Log writer
# ---------------------------------------------------------------------------

def write_log(
    mode: str,
    timestamp: str,
    total: int,
    normal_count: int,
    copied: int,
    review_count: int,
    ocr_count: int,
    metadata_count: int,
    details: List[Dict],
) -> Path:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOGS_DIR / f"process-inbox-{timestamp}.log"

    lines = [
        f"=== process_inbox.py log ===",
        f"timestamp   : {datetime.now().isoformat()}",
        f"mode        : {mode}",
        f"",
        f"[counts]",
        f"  total files     : {total}",
        f"  rename 候補     : {normal_count}",
        f"  copy 実行数     : {copied}",
        f"  review-required : {review_count}",
        f"  ocr-error       : {ocr_count}",
        f"  metadata 生成数 : {metadata_count}",
        f"",
        f"[detail]",
    ]

    for d in details:
        status = d.get("status", "-")
        src = d.get("src", "")
        dest = d.get("dest", "")
        warn = ", ".join(d.get("warnings", []))
        if dest:
            lines.append(f"  [{status}] {src} → {dest}")
        elif warn:
            lines.append(f"  [{status}] {src}  ⚠ {warn}")
        else:
            lines.append(f"  [{status}] {src}")

    with open(log_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    return log_path


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def print_section(title: str) -> None:
    print("=" * 60)
    print(title)
    print("=" * 60)


def print_divider() -> None:
    print("-" * 60)


# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------

def run(apply: bool) -> None:
    mode = "apply" if apply else "dry-run"
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    classified = scan_inbox(INBOX_DIR)
    all_files: List[Path] = classified["PDF"] + classified["IMAGE"] + classified["UNSUPPORTED"]

    print_section(f"[SCAN]  mode={mode}")
    print(f"Found {len(all_files)} files in inbox/")
    print()

    if not all_files:
        print("  inbox is empty. Nothing to process.")
        return

    analyses = [analyze_file(f) for f in all_files]
    normal = [a for a in analyses if not a["needs_review"]]
    review_needed = [a for a in analyses if a["needs_review"] and not a["needs_ocr_review"]]
    ocr_errors = [a for a in analyses if a["needs_ocr_review"]]

    log_details: List[Dict] = []
    copied_count = 0
    metadata_count = 0

    # -----------------------------------------------------------------------
    # [SUGGEST] — Normal files
    # -----------------------------------------------------------------------
    if normal:
        label = "[APPLY] — rename 候補を renamed/ へコピー" if apply else "[SUGGEST] — rename 候補（dry-run: ファイルは変更しない）"
        print(label)
        print_divider()

        for item in normal:
            tags_info = f" [tag: {', '.join(item['tags'])}]" if item["tags"] else ""
            best = item["best_effort_name"] or item["rename_hint"]

            if apply:
                dest_path = copy_to_renamed(item["path"], best)
                dest_rel = dest_path.relative_to(REPO_ROOT)

                metadata = generate_metadata(dest_path.name, source_filename=item["name"])
                metadata["status"] = "renamed"
                meta_path = save_metadata(metadata, METADATA_READY_DIR)
                meta_rel = meta_path.relative_to(REPO_ROOT)

                copied_count += 1
                metadata_count += 1
                print(f"  [COPY]  {item['name']}{tags_info}")
                print(f"          → {dest_rel}")
                print(f"  [META]  → {meta_rel}")

                log_details.append({
                    "status": "COPY",
                    "src": item["name"],
                    "dest": str(dest_rel),
                    "warnings": [],
                })
            else:
                print(f"  {item['name']}{tags_info}")
                print(f"  → {best}")
                log_details.append({
                    "status": "DRY-RUN",
                    "src": item["name"],
                    "dest": best,
                    "warnings": [],
                })
        print()

    # -----------------------------------------------------------------------
    # [WARNING] — OCR errors
    # -----------------------------------------------------------------------
    if ocr_errors:
        print("[WARNING] — OCR 文字化けの可能性あり（--apply でも処理対象外）")
        print_divider()
        for item in ocr_errors:
            print(f"  {item['name']}")
            for w in item["warnings"]:
                print(f"    ⚠ {w}")
            print(f"    → rename hint: {item['rename_hint']}")
            log_details.append({"status": "OCR-ERROR", "src": item["name"], "warnings": item["warnings"]})
        print()
        ocr_report = write_ocr_error_report(ocr_errors, timestamp)
        print(f"  レポート保存: {ocr_report.relative_to(REPO_ROOT)}")
        print()

    # -----------------------------------------------------------------------
    # [REVIEW REQUIRED] — Other issues
    # -----------------------------------------------------------------------
    if review_needed:
        print("[REVIEW REQUIRED] — 確認が必要なファイル（--apply でも処理対象外）")
        print_divider()
        for item in review_needed:
            print(f"  {item['name']}")
            for w in item["warnings"]:
                print(f"    ⚠ {w}")
            print(f"    → rename hint: {item['rename_hint']}")
            log_details.append({"status": "REVIEW", "src": item["name"], "warnings": item["warnings"]})
        print()
        review_report = write_review_report(review_needed, timestamp)
        print(f"  レポート保存: {review_report.relative_to(REPO_ROOT)}")
        print()

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    print_section("[SUMMARY]")
    print(f"  mode           : {mode}")
    print(f"  total          : {len(analyses)}")
    print(f"  rename 候補    : {len(normal)}")
    print(f"  copy 実行      : {copied_count}  {'(dry-run のため 0)' if not apply else ''}")
    print(f"  metadata 生成  : {metadata_count}  {'(dry-run のため 0)' if not apply else ''}")
    print(f"  ocr-error      : {len(ocr_errors)}  → processing/ocr-error/ にレポート")
    print(f"  review-required: {len(review_needed)}  → processing/review-required/ にレポート")
    print("=" * 60)

    log_path = write_log(
        mode=mode,
        timestamp=timestamp,
        total=len(analyses),
        normal_count=len(normal),
        copied=copied_count,
        review_count=len(review_needed),
        ocr_count=len(ocr_errors),
        metadata_count=metadata_count,
        details=log_details,
    )
    print(f"\n  ログ保存: {log_path.relative_to(REPO_ROOT)}")
    print()

    if not apply:
        print("Next steps:")
        print("  1. rename hint を確認し、問題なければ --apply を実行")
        print("  2. OCR エラー / review 対象は内容を目視確認してから手動で renamed/ へコピー")
        print("  3. python scripts/generate_metadata.py で残りの metadata を生成")
        print("  4. metadata を補完後に export/ または archive/ へ移動")
        print("  5. docs/export-rules.md の条件を満たしてから export/ へ")
    else:
        print("Next steps:")
        print("  1. processing/renamed/ のファイル名を確認し、Category を手動で追記")
        print("  2. processing/metadata-ready/ の .metadata.json を開いて category 等を補完")
        print("  3. OCR エラー / review 対象は内容を目視確認してから手動で renamed/ へコピー")
        print("  4. docs/export-rules.md の条件を満たしたら export/ または archive/ へ移動")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="inbox を分析し、safe copy と metadata 生成を行う",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python scripts/process_inbox.py            # dry-run（デフォルト）
  python scripts/process_inbox.py --dry-run  # 分析のみ、ファイルは変更しない
  python scripts/process_inbox.py --apply    # renamed/ へコピー + metadata 生成
        """,
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--dry-run", action="store_true", default=False, help="分析のみ（デフォルト）")
    group.add_argument("--apply", action="store_true", default=False, help="rename copy + metadata 生成を実行")
    args = parser.parse_args()

    run(apply=args.apply)
