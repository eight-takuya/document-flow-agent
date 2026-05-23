"""
export_to_dropbox.py

processing/renamed/ と processing/metadata-ready/ のファイルを export/ へコピーする。
月次で export/ を手動で Dropbox へ移動する運用を想定。

Usage:
    python scripts/export_to_dropbox.py --local           # export/ へコピー（デフォルト）
    python scripts/export_to_dropbox.py --local --dry-run # コピーせずに確認のみ

export/ 構成（v2 — category サブディレクトリ構造）:
    export/
    ├── files/
    │   ├── Receipt/
    │   ├── Finance/
    │   ├── Utility/
    │   └── ...（category 別）
    └── metadata/
        └── ...（同構造）

安全設計:
    - 元ファイル（processing/renamed/, processing/metadata-ready/）は削除しない
    - 同名ファイルがある場合は -001, -002 ... の連番で safe copy
    - review-decisions.json が残っている場合は export 不可（check_export_ready を呼ぶ）
    - dry-run では一切ファイルを変更しない
"""

import argparse
import json
import logging
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
RENAMED_DIR = ROOT / "processing" / "renamed"
AUTO_APPROVED_DIR = ROOT / "processing" / "auto-approved"
METADATA_DIR = ROOT / "processing" / "metadata-ready"
REVIEW_DIR = ROOT / "processing" / "review-required"
DECISIONS_FILE = REVIEW_DIR / "review-decisions.json"
EXPORT_DIR = ROOT / "export"
EXPORT_FILES_DIR = EXPORT_DIR / "files"
EXPORT_META_DIR = EXPORT_DIR / "metadata"
LOGS_DIR = ROOT / "logs"

_SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(_SCRIPTS_DIR))
from check_export_ready import run as check_ready
from export_utils import get_category, get_export_pdf_dir, get_export_meta_dir, safe_copy_dest


def _setup_logging(timestamp: str, dry_run: bool) -> logging.Logger:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOGS_DIR / f"export-{timestamp}.log"
    logger = logging.getLogger(f"export_{timestamp}")
    logger.setLevel(logging.DEBUG)
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    logger.addHandler(fh)
    logger.addHandler(ch)
    mode_label = "[DRY-RUN] " if dry_run else ""
    logger.info("%s=== export_to_dropbox 開始 ===", mode_label)
    return logger, log_path


def _safe_copy_dest(dest_dir: Path, filename: str) -> Path:
    """重複時に -001, -002 ... の連番を付けた保存先パスを返す（export_utils.safe_copy_dest を使用）。"""
    return safe_copy_dest(dest_dir, filename)


def _collect_pdfs() -> list:
    """renamed/ と auto-approved/ の処理済み PDF 一覧（.gitkeep 除外）。"""
    files = []
    for d in (RENAMED_DIR, AUTO_APPROVED_DIR):
        if d.exists():
            files.extend(f for f in d.glob("*.pdf") if f.name != ".gitkeep")
    return sorted(files)


def _collect_metadata() -> list:
    """metadata-ready/ の metadata JSON 一覧。"""
    if not METADATA_DIR.exists():
        return []
    return sorted(METADATA_DIR.glob("*.metadata.json"))


def _copy_file(src: Path, dest_dir: Path, dry_run: bool, logger: logging.Logger) -> tuple:
    """
    src を dest_dir へ safe copy する（v2: category サブディレクトリへ）。
    Returns: (dest_path, skipped: bool)
    """
    dest = _safe_copy_dest(dest_dir, src.name)
    rel_dest = dest.relative_to(EXPORT_DIR)
    if dry_run:
        suffix = " [new]" if dest.name == src.name else f" [→ {dest.name}]"
        logger.info("[DRY-RUN] COPY %s → export/%s%s", src.name, rel_dest, suffix)
        return dest, False
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    suffix = "" if dest.name == src.name else f" (→ {dest.name})"
    logger.info("COPY  %s → export/%s%s", src.name, rel_dest, suffix)
    return dest, False


def run_local(dry_run: bool = False) -> None:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    logger, log_path = _setup_logging(timestamp, dry_run)

    # export 可能か判定
    if DECISIONS_FILE.exists():
        logger.error("review-decisions.json が残っています。apply_review_decisions.py を先に実行してください")
        logger.error("  python scripts/apply_review_decisions.py")
        sys.exit(1)

    pdfs = _collect_pdfs()
    metadata = _collect_metadata()

    if not pdfs:
        logger.error("processing/renamed/ に PDF がありません。処理対象がありません")
        sys.exit(1)

    logger.info("export 対象: PDF %d 件、metadata %d 件", len(pdfs), len(metadata))
    if dry_run:
        logger.info("[DRY-RUN] ファイルは変更されません")

    copied_pdfs = 0
    copied_meta = 0
    skipped = 0

    # PDF のコピー（v2: category サブディレクトリへ）
    logger.info("--- PDF のコピー: renamed/ → export/files/<category>/ ---")
    for pdf in pdfs:
        try:
            # metadata から category を取得（あれば）
            meta_path = METADATA_DIR / (pdf.stem + ".metadata.json")
            meta_data = None
            if meta_path.exists():
                try:
                    meta_data = json.loads(meta_path.read_text(encoding="utf-8"))
                except Exception:
                    pass
            category = get_category(pdf.name, metadata=meta_data)
            dest_dir = get_export_pdf_dir(category)
            _copy_file(pdf, dest_dir, dry_run, logger)
            copied_pdfs += 1
        except Exception as e:
            logger.warning("SKIP %s: %s", pdf.name, e)
            skipped += 1

    # metadata のコピー（v2: category サブディレクトリへ）
    logger.info("--- metadata のコピー: metadata-ready/ → export/metadata/<category>/ ---")
    for meta in metadata:
        try:
            meta_data = None
            try:
                meta_data = json.loads(meta.read_text(encoding="utf-8"))
            except Exception:
                pass
            category = get_category(meta.name, metadata=meta_data)
            dest_dir = get_export_meta_dir(category)
            _copy_file(meta, dest_dir, dry_run, logger)
            copied_meta += 1
        except Exception as e:
            logger.warning("SKIP %s: %s", meta.name, e)
            skipped += 1

    # サマリ
    logger.info("=== 完了 === PDF:%d  metadata:%d  skipped:%d", copied_pdfs, copied_meta, skipped)
    if not dry_run:
        logger.info("export/files/    に %d 件コピー済み", copied_pdfs)
        logger.info("export/metadata/ に %d 件コピー済み", copied_meta)
        logger.info("次のステップ: export/ の内容を確認し、月次で Dropbox へ手動転送してください")
    print(f"\n  ログ保存: {log_path.relative_to(ROOT)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="processing/renamed/ と metadata-ready/ のファイルを export/ へコピーする",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python scripts/export_to_dropbox.py --local           # export/ へコピー
  python scripts/export_to_dropbox.py --local --dry-run # 確認のみ（コピーしない）
        """,
    )
    parser.add_argument(
        "--local", action="store_true", required=True,
        help="export/ へローカルコピーする（Dropbox 転送は将来実装）",
    )
    parser.add_argument(
        "--dry-run", action="store_true", default=False,
        help="ファイルを変更せずに確認のみ実行",
    )
    args = parser.parse_args()

    if args.local:
        run_local(dry_run=args.dry_run)
