"""
normalize_documents.py

inbox/ 内のファイルを走査し、種別・OCR品質・リネーム方針を表示する。
実際のファイル移動・変換は行わない（安全な読み取りのみ）。
"""

import re
from pathlib import Path
from typing import Dict, List, Tuple

INBOX_DIR = Path(__file__).parent.parent / "inbox"

PDF_EXTS = {".pdf"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg"}

# ファイル名に文字化けが疑われるパターン
GARBLED_PATTERN = re.compile(
    r"[醇珍嘗叡蕊燕蕎墨廃]"       # OCR誤認識頻出漢字
    r"|[ぁ-ん]{1}[ァ-ン]{1}"       # ひらがな・カタカナの異常混在
    r"|[^\x00-\x7F]{20,}"          # 非ASCII 20文字超（日本語としても長すぎ）
    r"|\d[^\w\-_\.\s　-鿿＀-￯]"  # 数字の直後に記号が続く異常パターン
)

# 既存ファイル名から日付を抽出するパターン
DATE_PATTERN = re.compile(r"^(\d{8})")

# 【TAG】形式のタグを抽出
BRACKET_TAG_PATTERN = re.compile(r"【([^】]+)】")


def classify_file(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in PDF_EXTS:
        return "PDF"
    if ext in IMAGE_EXTS:
        return "IMAGE"
    return "UNSUPPORTED"


def is_hidden_or_system(path: Path) -> bool:
    return path.name.startswith(".") or path.name in {".DS_Store"}


def detect_garbled(name: str) -> bool:
    """ファイル名に文字化けが含まれる可能性を検出する。"""
    stem = Path(name).stem
    return bool(GARBLED_PATTERN.search(stem))


def extract_date(name: str) -> str:
    """ファイル名先頭の YYYYMMDD を抽出する。なければ空文字。"""
    m = DATE_PATTERN.match(name)
    return m.group(1) if m else ""


def extract_bracket_tags(name: str) -> List[str]:
    """【TAG】形式のタグを全て抽出する。"""
    return BRACKET_TAG_PATTERN.findall(name)


def suggest_rename(path: Path) -> str:
    """
    既存ファイル名から命名規約への変換ヒントを生成する。
    確定的なリネームではなく、Claude Cowork への参考情報として使う。
    """
    name = path.name
    date = extract_date(name)
    tags = extract_bracket_tags(name)

    if not date:
        return "(日付不明: 要確認)"

    tag_suffix = f"-{tags[0]}" if tags else ""
    hint = f"{date}-[Category]-[Document]{tag_suffix}.pdf"
    return hint


def scan_inbox(inbox_dir: Path = INBOX_DIR) -> Dict[str, List[Path]]:
    result: Dict[str, List[Path]] = {"PDF": [], "IMAGE": [], "UNSUPPORTED": []}

    if not inbox_dir.exists():
        print(f"inbox not found: {inbox_dir}")
        return result

    files = sorted(
        f for f in inbox_dir.iterdir()
        if f.is_file() and not is_hidden_or_system(f)
    )

    for f in files:
        kind = classify_file(f)
        result[kind].append(f)

    return result


def run() -> None:
    classified = scan_inbox()
    all_files = classified["PDF"] + classified["IMAGE"] + classified["UNSUPPORTED"]

    pdf_count = len(classified["PDF"])
    image_count = len(classified["IMAGE"])
    unsupported_count = len(classified["UNSUPPORTED"])
    garbled_count = sum(1 for f in all_files if detect_garbled(f.name))
    no_date_count = sum(1 for f in all_files if not extract_date(f.name))

    print(f"=== inbox scan — {len(all_files)} files found ===")
    print()

    if not all_files:
        print("  (empty)")
        return

    # PDF
    if classified["PDF"]:
        print(f"[PDF] {pdf_count} files")
        for path in classified["PDF"]:
            garbled = " ⚠ garbled filename" if detect_garbled(path.name) else ""
            tags = extract_bracket_tags(path.name)
            tag_info = f" [tag: {', '.join(tags)}]" if tags else ""
            hint = suggest_rename(path)
            print(f"  {path.name}{garbled}{tag_info}")
            print(f"    → rename hint: {hint}")
        print()

    # IMAGE
    if classified["IMAGE"]:
        print(f"[IMAGE] {image_count} files — TODO: convert to PDF before processing")
        for path in classified["IMAGE"]:
            garbled = " ⚠ garbled filename" if detect_garbled(path.name) else ""
            print(f"  {path.name}{garbled}")
            print(f"    → convert to PDF first, then apply naming convention")
        print()

    # UNSUPPORTED
    if classified["UNSUPPORTED"]:
        print(f"[UNSUPPORTED] {unsupported_count} files — skipped")
        for path in classified["UNSUPPORTED"]:
            print(f"  {path.name}")
        print()

    # Summary
    print("=== summary ===")
    print(f"  PDF       : {pdf_count}")
    print(f"  IMAGE     : {image_count}  (TODO: PDF conversion)")
    print(f"  Unsupported: {unsupported_count}")
    print(f"  Garbled names: {garbled_count}  (⚠ manual review needed)")
    print(f"  No date in name: {no_date_count}  (⚠ date unknown)")
    print()
    print("Next steps:")
    print("  1. Review garbled filenames and correct manually if needed")
    print("  2. Open files with date-only names (e.g. 20260517.pdf) to identify content")
    print("  3. Apply naming convention via: python scripts/rename_documents.py")
    print("  4. See docs/naming-convention.md and docs/categories.md for reference")


if __name__ == "__main__":
    run()
