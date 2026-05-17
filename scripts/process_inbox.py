"""
process_inbox.py

inbox をスキャンして、各ファイルの状態を分析し、
rename 候補・review 要否・OCR エラーの可能性を報告する。

実際のファイル移動は行わない。
分析レポートを processing/review-required/ と processing/ocr-error/ に書き出す。
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List

REPO_ROOT = Path(__file__).parent.parent
INBOX_DIR = REPO_ROOT / "inbox"
PROCESSING_DIR = REPO_ROOT / "processing"
REVIEW_DIR = PROCESSING_DIR / "review-required"
OCR_ERROR_DIR = PROCESSING_DIR / "ocr-error"

sys.path.insert(0, str(Path(__file__).parent))
from normalize_documents import (
    scan_inbox,
    detect_garbled,
    extract_date,
    extract_bracket_tags,
    classify_file,
)
from rename_documents import build_filename, validate_filename, CATEGORIES


PDF_EXTS = {".pdf"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg"}
MAX_STEM_LENGTH = 80


# ---------------------------------------------------------------------------
# Analysis helpers
# ---------------------------------------------------------------------------

def is_date_only(name: str) -> bool:
    stem = Path(name).stem
    return bool(__import__("re").match(r"^\d{8}$", stem))


def is_too_long(name: str) -> bool:
    return len(Path(name).stem) > MAX_STEM_LENGTH


def analyze_file(path: Path) -> Dict:
    """
    ファイルを分析してフラグと rename ヒントを返す。

    Returns:
        dict with keys:
            name, kind, date, tags, garbled, date_only, too_long,
            needs_review, needs_ocr_review, rename_hint, warnings
    """
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

    # rename hint
    if date:
        tag_suffix = f"-{tags[0]}" if tags else ""
        rename_hint = f"{date}-[Category]-[Document]{tag_suffix}.pdf"
    else:
        rename_hint = "(日付不明: 要確認)"

    return {
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
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Report writers
# ---------------------------------------------------------------------------

def write_review_report(items: List[Dict]) -> Path:
    """review-required/ にレポート JSON を書き出す。"""
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    report_path = REVIEW_DIR / f"review-report-{timestamp}.json"
    report = {
        "generated_at": datetime.now().isoformat(),
        "count": len(items),
        "files": [
            {
                "name": item["name"],
                "warnings": item["warnings"],
                "rename_hint": item["rename_hint"],
            }
            for item in items
        ],
    }
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    return report_path


def write_ocr_error_report(items: List[Dict]) -> Path:
    """ocr-error/ にレポート JSON を書き出す。"""
    OCR_ERROR_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    report_path = OCR_ERROR_DIR / f"ocr-error-report-{timestamp}.json"
    report = {
        "generated_at": datetime.now().isoformat(),
        "count": len(items),
        "files": [
            {
                "name": item["name"],
                "warnings": item["warnings"],
            }
            for item in items
        ],
    }
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    return report_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run() -> None:
    classified = scan_inbox(INBOX_DIR)
    all_files: List[Path] = classified["PDF"] + classified["IMAGE"] + classified["UNSUPPORTED"]

    print("=" * 60)
    print("[SCAN]")
    print(f"Found {len(all_files)} files in inbox/")
    print("=" * 60)
    print()

    if not all_files:
        print("  inbox is empty. Nothing to process.")
        return

    analyses = [analyze_file(f) for f in all_files]

    normal = [a for a in analyses if not a["needs_review"]]
    review_needed = [a for a in analyses if a["needs_review"] and not a["needs_ocr_review"]]
    ocr_errors = [a for a in analyses if a["needs_ocr_review"]]

    # -----------------------------------------------------------------------
    # [SUGGEST] — Normal files
    # -----------------------------------------------------------------------
    if normal:
        print("[SUGGEST] — rename 候補（要確認・自動適用しない）")
        print("-" * 60)
        for item in normal:
            tags = f" [tag: {', '.join(item['tags'])}]" if item["tags"] else ""
            print(f"  {item['name']}{tags}")
            print(f"  → {item['rename_hint']}")
        print()

    # -----------------------------------------------------------------------
    # [WARNING] — OCR errors
    # -----------------------------------------------------------------------
    if ocr_errors:
        print("[WARNING] — OCR 文字化けの可能性あり")
        print("-" * 60)
        for item in ocr_errors:
            print(f"  {item['name']}")
            for w in item["warnings"]:
                print(f"    ⚠ {w}")
            print(f"    → rename hint: {item['rename_hint']}")
        print()
        ocr_report = write_ocr_error_report(ocr_errors)
        print(f"  レポート保存: {ocr_report.relative_to(REPO_ROOT)}")
        print()

    # -----------------------------------------------------------------------
    # [REVIEW REQUIRED] — Other issues
    # -----------------------------------------------------------------------
    if review_needed:
        print("[REVIEW REQUIRED] — 確認が必要なファイル")
        print("-" * 60)
        for item in review_needed:
            print(f"  {item['name']}")
            for w in item["warnings"]:
                print(f"    ⚠ {w}")
            print(f"    → rename hint: {item['rename_hint']}")
        print()
        review_report = write_review_report(review_needed)
        print(f"  レポート保存: {review_report.relative_to(REPO_ROOT)}")
        print()

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    print("=" * 60)
    print("[SUMMARY]")
    print(f"  Total      : {len(analyses)}")
    print(f"  Normal     : {len(normal)}  → rename hint 表示済み")
    print(f"  OCR Error  : {len(ocr_errors)}  → processing/ocr-error/ にレポート")
    print(f"  Review     : {len(review_needed)}  → processing/review-required/ にレポート")
    print("=" * 60)
    print()
    print("Next steps:")
    print("  1. 上記 rename hint を確認し、手動でファイルをコピー → processing/renamed/")
    print("  2. OCR エラー・review 対象は内容を目視確認してから renamed/ へ移動")
    print("  3. python scripts/generate_metadata.py で metadata scaffold を生成")
    print("  4. metadata を確認・補完後に export/ または archive/ へ移動")
    print("  5. docs/export-rules.md の export 可能条件を満たしてから export/ へ")


if __name__ == "__main__":
    run()
