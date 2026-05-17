"""
apply_review_decisions.py

processing/review-required/review-decisions.json を読み込み、
各ファイルに対して rename / discard / skip の処理を行う。

  rename  : inbox/ のファイルを processing/renamed/ へ safe copy し、
            metadata scaffold を processing/metadata-ready/ に生成する。
  discard : ログのみ記録。inbox のファイルは削除しない。
  skip    : ログのみ記録。
"""

import json
import logging
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
INBOX_DIR = ROOT / "inbox"
RENAMED_DIR = ROOT / "processing" / "renamed"
METADATA_DIR = ROOT / "processing" / "metadata-ready"
REVIEW_DIR = ROOT / "processing" / "review-required"
DECISIONS_FILE = REVIEW_DIR / "review-decisions.json"
LOGS_DIR = ROOT / "logs"

sys.path.insert(0, str(Path(__file__).parent))
from generate_metadata import generate_metadata, save_metadata


def _setup_logging(timestamp: str) -> logging.Logger:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOGS_DIR / f"apply-review-{timestamp}.log"
    logger = logging.getLogger("apply_review")
    logger.setLevel(logging.DEBUG)
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


def _safe_copy_destination(dest_dir: Path, filename: str) -> Path:
    """重複時に -001, -002 … の連番を付けた保存先パスを返す。"""
    candidate = dest_dir / filename
    if not candidate.exists():
        return candidate
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    for i in range(1, 1000):
        candidate = dest_dir / f"{stem}-{i:03d}{suffix}"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Could not find a free path for {filename}")


def _apply_rename(item: dict, logger: logging.Logger) -> bool:
    source_name = item["source_file_name"]
    approved_name = item.get("approved_file_name", "").strip()
    notes = item.get("notes", "")

    if not approved_name:
        logger.warning("RENAME skip — approved_file_name が空です: %s", source_name)
        return False

    # inbox からソースファイルを探す
    source_path = INBOX_DIR / source_name
    if not source_path.exists():
        logger.error("RENAME 失敗 — inbox にファイルが見つかりません: %s", source_name)
        return False

    # approved_name を安全なファイル名に制限
    safe_name = re.sub(r'[<>:"/\\|?*]', "_", approved_name)
    if not safe_name.lower().endswith(".pdf"):
        safe_name += ".pdf"

    RENAMED_DIR.mkdir(parents=True, exist_ok=True)
    METADATA_DIR.mkdir(parents=True, exist_ok=True)

    dest_path = _safe_copy_destination(RENAMED_DIR, safe_name)
    shutil.copy2(source_path, dest_path)
    logger.info("RENAME OK  %s -> %s", source_name, dest_path.name)

    # metadata scaffold 生成
    try:
        metadata = generate_metadata(dest_path.name, source_filename=source_name)
        metadata["status"] = "renamed"
        if notes:
            metadata["notes"] = notes
        saved = save_metadata(metadata, METADATA_DIR)
        logger.info("METADATA   %s", saved.name)
    except Exception as e:
        logger.warning("METADATA 生成失敗 — %s: %s", dest_path.name, e)

    return True


def run(decisions_path: Path = DECISIONS_FILE) -> None:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    logger = _setup_logging(timestamp)

    if not decisions_path.exists():
        logger.error("review-decisions.json が見つかりません: %s", decisions_path)
        logger.error("HTML レポートで判断を入力し、JSONを %s に保存してください", decisions_path)
        sys.exit(1)

    with open(decisions_path, encoding="utf-8") as f:
        data = json.load(f)

    reviewed_at = data.get("reviewed_at", "")
    items = data.get("items", [])

    logger.info("=== apply_review_decisions 開始 === reviewed_at=%s, %d 件", reviewed_at, len(items))

    stats = {"rename": 0, "discard": 0, "skip": 0, "error": 0}

    for item in items:
        decision = item.get("decision", "skip")

        if decision == "rename":
            ok = _apply_rename(item, logger)
            stats["rename" if ok else "error"] += 1

        elif decision == "discard":
            logger.info("DISCARD    %s (notes: %s)", item.get("source_file_name"), item.get("notes", ""))
            stats["discard"] += 1

        elif decision == "skip":
            logger.info("SKIP       %s", item.get("source_file_name"))
            stats["skip"] += 1

        else:
            logger.warning("不明な decision '%s' — skip します: %s", decision, item.get("source_file_name"))
            stats["skip"] += 1

    logger.info(
        "=== 完了 === rename:%d  discard:%d  skip:%d  error:%d",
        stats["rename"], stats["discard"], stats["skip"], stats["error"],
    )

    if stats["rename"] > 0:
        logger.info("processing/renamed/ と processing/metadata-ready/ を確認してください。")
    if stats["discard"] > 0:
        logger.info("廃棄対象 %d 件 — inbox から手動削除し、ログに「廃棄」として記録してください。", stats["discard"])


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="review-decisions.json を処理して rename/discard/skip を実行する")
    parser.add_argument(
        "--decisions",
        type=Path,
        default=DECISIONS_FILE,
        help=f"review-decisions.json のパス (デフォルト: {DECISIONS_FILE})",
    )
    args = parser.parse_args()
    run(decisions_path=args.decisions)
