"""
normalize_images.py

.jpg/.jpeg/.png を単一ページ PDF へ変換する。
OCR や rename の前処理として process_inbox.py から呼ばれる。

変換後 PDF は processing/normalized/ に一時保存される。
元画像は変更しない。

Usage (standalone):
    python scripts/normalize_images.py <image_path>
"""

from pathlib import Path
from typing import Optional

from PIL import Image

NORMALIZED_DIR = Path(__file__).parent.parent / "processing" / "normalized"
ACCEPTED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


def image_to_pdf(src: Path, dest: Path) -> bool:
    """src 画像を dest に単一ページ PDF として書き出す。成功したら True。"""
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        img = Image.open(src)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        img.save(str(dest), "PDF", resolution=150)
        return True
    except Exception as e:
        print(f"[normalize_images] 変換失敗: {src.name} → {e}")
        return False


def normalize_image(src: Path, normalized_dir: Path = NORMALIZED_DIR) -> Optional[Path]:
    """
    画像ファイルを normalized_dir に PDF として変換して返す。
    - 対象外の拡張子の場合は None を返す
    - 変換失敗の場合も None を返す
    - 既に変換済みの PDF が存在する場合はそれをそのまま返す
    """
    if src.suffix.lower() not in ACCEPTED_IMAGE_SUFFIXES:
        return None
    dest = normalized_dir / (src.stem + ".pdf")
    if dest.exists():
        return dest
    return dest if image_to_pdf(src, dest) else None


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python scripts/normalize_images.py <image_path>")
        sys.exit(1)

    src_path = Path(sys.argv[1])
    if not src_path.exists():
        print(f"ファイルが見つかりません: {src_path}")
        sys.exit(1)

    result = normalize_image(src_path)
    if result:
        print(f"OK: {src_path.name} → {result}")
    else:
        print(f"失敗: {src_path.name}")
        sys.exit(1)
