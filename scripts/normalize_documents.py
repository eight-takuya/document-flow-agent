"""
normalize_documents.py

inbox/ 内のファイルを走査し、種別ごとに分類して一覧表示する。
実際のファイル移動・変換は行わない（安全な読み取りのみ）。
"""

from pathlib import Path

INBOX_DIR = Path(__file__).parent.parent / "inbox"

PDF_EXTS = {".pdf"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg"}
SUPPORTED_EXTS = PDF_EXTS | IMAGE_EXTS


def classify_file(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in PDF_EXTS:
        return "PDF"
    if ext in IMAGE_EXTS:
        return "IMAGE"
    return "UNKNOWN"


def format_label(path: Path, kind: str) -> str:
    if kind == "PDF":
        return f"  - {path.name} [PDF]"
    if kind == "IMAGE":
        return f"  - {path.name} [IMAGE: TODO convert to PDF]"
    return f"  - {path.name} [UNSUPPORTED: skipped]"


def scan_inbox(inbox_dir: Path = INBOX_DIR) -> dict[str, list[Path]]:
    result: dict[str, list[Path]] = {"PDF": [], "IMAGE": [], "UNSUPPORTED": []}

    if not inbox_dir.exists():
        print(f"inbox not found: {inbox_dir}")
        return result

    files = sorted(
        f for f in inbox_dir.iterdir()
        if f.is_file() and f.name != ".gitkeep"
    )

    for f in files:
        kind = classify_file(f)
        result[kind].append(f)

    return result


def run() -> None:
    classified = scan_inbox()
    all_files = classified["PDF"] + classified["IMAGE"] + classified["UNSUPPORTED"]

    print(f"Found {len(all_files)} files in inbox:")

    if not all_files:
        print("  (empty)")
        return

    for kind in ("PDF", "IMAGE", "UNSUPPORTED"):
        for path in classified[kind]:
            print(format_label(path, kind))

    pdf_count = len(classified["PDF"])
    image_count = len(classified["IMAGE"])
    unsupported_count = len(classified["UNSUPPORTED"])

    print()
    print(f"Summary: {pdf_count} PDF, {image_count} image (TODO: convert), {unsupported_count} unsupported")

    if image_count > 0:
        print()
        print("Next step for images:")
        print("  - Convert to PDF using scripts/classify_documents.py (not yet implemented)")
        print("  - Or manually convert and re-place in inbox/")


if __name__ == "__main__":
    run()
