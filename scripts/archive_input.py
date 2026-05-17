"""
archive_input.py

inbox/ の処理済み原本ファイルを archive/original-input/YYYYMM/ へ月別アーカイブする。

月フォルダ決定順:
  1. ファイル名先頭の YYYYMMDD（例: 20260517_foo.pdf → 202605/）
  2. 取れない場合はファイルの更新日時（mtime）

安全チェック（--apply 実行前）:
  export/files/ または processing/renamed/ または processing/auto-approved/
  にファイルが存在しない場合は警告して停止。
  --force で強制実行可能。

Usage:
    python scripts/archive_input.py --dry-run   # デフォルト。ファイルは変更しない
    python scripts/archive_input.py --apply      # inbox/ から archive/ へ移動
    python scripts/archive_input.py --apply --force  # 安全チェックをスキップ
"""

import argparse
import logging
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
INBOX_DIR = ROOT / "inbox"
ARCHIVE_BASE = ROOT / "archive" / "original-input"
PROCESSING_DIR = ROOT / "processing"
RENAMED_DIR = PROCESSING_DIR / "renamed"
AUTO_APPROVED_DIR = PROCESSING_DIR / "auto-approved"
EXPORT_FILES_DIR = ROOT / "export" / "files"
LOGS_DIR = ROOT / "logs"

ACCEPTED_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg"}
DATE_PREFIX_RE = re.compile(r"^(\d{4})(\d{2})\d{2}")


def _setup_logging(timestamp: str, dry_run: bool) -> tuple:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOGS_DIR / f"archive-input-{timestamp}.log"
    logger = logging.getLogger(f"archive_input_{timestamp}")
    logger.setLevel(logging.DEBUG)
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    logger.addHandler(fh)
    logger.addHandler(ch)
    mode = "[DRY-RUN] " if dry_run else ""
    logger.info("%s=== archive_input 開始 ===", mode)
    return logger, log_path


def _yyyymm_from_name(name: str) -> str:
    """ファイル名先頭の YYYYMMDD から YYYYMM を返す。取れなければ空文字。"""
    m = DATE_PREFIX_RE.match(name)
    if m:
        return m.group(1) + m.group(2)
    return ""


def _yyyymm_from_mtime(path: Path) -> str:
    """ファイルの mtime から YYYYMM を返す。"""
    mtime = datetime.fromtimestamp(path.stat().st_mtime)
    return mtime.strftime("%Y%m")


def _safe_dest(dest_dir: Path, filename: str) -> Path:
    """同名ファイルがある場合は -001, -002 ... の連番を付与して返す。"""
    candidate = dest_dir / filename
    if not candidate.exists():
        return candidate
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    for i in range(1, 1000):
        candidate = dest_dir / f"{stem}-{i:03d}{suffix}"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"空きパスが見つかりません: {filename}")


def _collect_inbox_files() -> list:
    """inbox/ の対象ファイルを収集する（隠しファイル・.gitkeep・ディレクトリを除外）。"""
    if not INBOX_DIR.exists():
        return []
    return sorted(
        f for f in INBOX_DIR.iterdir()
        if f.is_file()
        and not f.name.startswith(".")
        and f.name != ".gitkeep"
        and f.suffix.lower() in ACCEPTED_SUFFIXES
    )


def _has_processed_files() -> bool:
    """export/files/, renamed/, auto-approved/ のいずれかにファイルがあるか確認する。"""
    for d in (EXPORT_FILES_DIR, RENAMED_DIR, AUTO_APPROVED_DIR):
        if d.exists():
            files = [f for f in d.iterdir() if f.is_file() and not f.name.startswith(".") and f.name != ".gitkeep"]
            if files:
                return True
    return False


def run(apply: bool, force: bool = False) -> None:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dry_run = not apply
    logger, log_path = _setup_logging(timestamp, dry_run)

    # 安全チェック
    if apply and not force:
        if not _has_processed_files():
            logger.error(
                "処理済みファイルが見つかりません。inbox のファイルがまだ処理されていない可能性があります。"
            )
            logger.error(
                "  確認先: export/files/  processing/renamed/  processing/auto-approved/"
            )
            logger.error("  処理済みであることを確認してから実行してください。")
            logger.error("  強制実行する場合: python scripts/archive_input.py --apply --force")
            sys.exit(1)

    files = _collect_inbox_files()
    if not files:
        logger.info("inbox/ に対象ファイルがありません。処理終了。")
        print(f"\n  ログ保存: {log_path.relative_to(ROOT)}")
        return

    logger.info("対象ファイル数: %d", len(files))
    if dry_run:
        logger.info("[DRY-RUN] ファイルは変更されません")

    moved = 0
    skipped = 0

    print()
    for f in files:
        yyyymm = _yyyymm_from_name(f.name) or _yyyymm_from_mtime(f)
        dest_dir = ARCHIVE_BASE / yyyymm
        dest = _safe_dest(dest_dir, f.name)
        renamed_note = f" [→ {dest.name}]" if dest.name != f.name else ""

        if dry_run:
            logger.info("[DRY-RUN] MOVE %s → %s/%s%s", f.name, yyyymm, dest.name, renamed_note)
        else:
            try:
                dest_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(f), str(dest))
                logger.info("MOVE  %s → %s/%s%s", f.name, yyyymm, dest.name, renamed_note)
                moved += 1
            except Exception as e:
                logger.warning("SKIP  %s: %s", f.name, e)
                skipped += 1

    print()
    if dry_run:
        logger.info("=== DRY-RUN 完了 === 対象:%d  (実際には移動しません)", len(files))
        print("  → --apply を付けて実行すると移動を実行します")
    else:
        logger.info("=== 完了 === 移動:%d  スキップ:%d", moved, skipped)
        if moved:
            print(f"  archive/original-input/ に {moved} 件を移動しました")
        if skipped:
            print(f"  スキップ: {skipped} 件")

    print(f"\n  ログ保存: {log_path.relative_to(ROOT)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="inbox/ の原本を archive/original-input/YYYYMM/ へ月別アーカイブする",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python scripts/archive_input.py --dry-run          # 確認のみ（デフォルト）
  python scripts/archive_input.py --apply            # 実際に移動
  python scripts/archive_input.py --apply --force    # 安全チェックをスキップして移動
        """,
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--dry-run", action="store_true", default=False, help="確認のみ（ファイルは変更しない）")
    mode_group.add_argument("--apply", action="store_true", default=False, help="inbox/ から archive/ へ移動")
    parser.add_argument("--force", action="store_true", default=False, help="安全チェックをスキップして移動")
    args = parser.parse_args()

    run(apply=args.apply, force=args.force)
