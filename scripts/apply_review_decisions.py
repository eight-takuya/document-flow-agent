"""
apply_review_decisions.py

processing/review-required/review-decisions.json を読み込み、
各ファイルに対して rename / discard / skip の処理を行う。

  rename  : inbox/ のファイルを processing/renamed/ へ safe copy し、
            metadata scaffold を processing/metadata-ready/ に生成する。
  discard : ログのみ記録。inbox のファイルは削除しない。
  skip    : ログのみ記録。

処理後は review-decisions.json を
  processing/review-required/applied/review-decisions-YYYYMMDD-HHMMSS.applied.json
へ移動する（再適用防止）。
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
APPLIED_DIR = REVIEW_DIR / "applied"
DECISIONS_FILE = REVIEW_DIR / "review-decisions.json"
NORMALIZED_DIR = ROOT / "processing" / "normalized"
LOGS_DIR = ROOT / "logs"

sys.path.insert(0, str(Path(__file__).parent))
from generate_metadata import generate_metadata, save_metadata
from normalize_images import normalize_image, ACCEPTED_IMAGE_SUFFIXES


def _setup_logging(timestamp: str) -> logging.Logger:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOGS_DIR / f"apply-review-{timestamp}.log"
    logger = logging.getLogger(f"apply_review_{timestamp}")
    logger.setLevel(logging.DEBUG)
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


def _load_applied_keys() -> set:
    """
    applied/ フォルダ内の過去の決定から (source_file_name, approved_file_name) のセットを返す。
    これにより、同じ決定の再適用を防止する。
    """
    keys: set = set()
    if not APPLIED_DIR.exists():
        return keys
    for f in APPLIED_DIR.glob("*.applied.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            for item in data.get("items", []):
                src = item.get("source_file_name", "")
                dst = item.get("approved_file_name", "")
                if src:
                    keys.add((src, dst))
        except Exception:
            pass
    return keys


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

    source_path = INBOX_DIR / source_name
    if not source_path.exists():
        logger.error("RENAME 失敗 — inbox にファイルが見つかりません: %s", source_name)
        return False

    # 画像ファイルは正規化済み PDF を使用する
    is_image = source_path.suffix.lower() in ACCEPTED_IMAGE_SUFFIXES
    if is_image:
        normalized = normalize_image(source_path, NORMALIZED_DIR)
        if normalized:
            source_path = normalized
            logger.info("NORM       %s → %s (normalized PDF)", source_name, normalized.name)
        else:
            logger.warning("NORM 失敗 — 元の画像ファイルを使用します: %s", source_name)

    safe_name = re.sub(r'[<>:"/\\|?*]', "_", approved_name)
    # 画像ソースは必ず .pdf 拡張子にする（正規化済み PDF をコピーするため）
    if is_image:
        safe_name = Path(safe_name).stem + ".pdf"
    elif Path(safe_name).suffix.lower() not in {".pdf", ".jpg", ".jpeg", ".png"}:
        safe_name += ".pdf"

    RENAMED_DIR.mkdir(parents=True, exist_ok=True)
    METADATA_DIR.mkdir(parents=True, exist_ok=True)

    # 既に renamed/ に同名ファイルがある場合は警告（-001 付与で続行）
    exact_path = RENAMED_DIR / safe_name
    if exact_path.exists():
        logger.warning(
            "WARN: %s は既に renamed/ に存在します — -001 連番で safe copy します", safe_name
        )

    dest_path = _safe_copy_destination(RENAMED_DIR, safe_name)
    shutil.copy2(source_path, dest_path)
    logger.info("RENAME OK  %s -> %s", source_name, dest_path.name)

    try:
        metadata = generate_metadata(dest_path.name, source_filename=source_name)
        metadata["status"] = "renamed"
        if notes:
            metadata["notes"] = notes
        if is_image:
            metadata["original_extension"] = Path(source_name).suffix.lower()
            metadata["normalized_pdf"] = True
        saved = save_metadata(metadata, METADATA_DIR)
        logger.info("METADATA   %s", saved.name)
    except Exception as e:
        logger.warning("METADATA 生成失敗 — %s: %s", dest_path.name, e)

    return True


def _archive_decisions(decisions_path: Path, timestamp: str, logger: logging.Logger) -> None:
    """処理済み decisions ファイルを applied/ へ移動する。"""
    APPLIED_DIR.mkdir(parents=True, exist_ok=True)
    archive_name = f"review-decisions-{timestamp}.applied.json"
    dest = APPLIED_DIR / archive_name
    shutil.move(str(decisions_path), str(dest))
    logger.info("ARCHIVED   %s → applied/%s", decisions_path.name, archive_name)


def run(decisions_path: Path = DECISIONS_FILE) -> None:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    logger = _setup_logging(timestamp)

    if not decisions_path.exists():
        logger.error("review-decisions.json が見つかりません: %s", decisions_path)
        logger.error("  review_server.py でレビューし、「保存」ボタンを押してください")
        logger.error("  または: python scripts/review_server.py")
        sys.exit(1)

    with open(decisions_path, encoding="utf-8") as f:
        data = json.load(f)

    reviewed_at = data.get("reviewed_at", "")
    items = data.get("items", [])

    logger.info("=== apply_review_decisions 開始 === reviewed_at=%s, %d 件", reviewed_at, len(items))

    # 過去の適用済み決定を読み込んで重複チェック用セットを作成
    applied_keys = _load_applied_keys()
    if applied_keys:
        logger.info("過去の適用済み決定: %d 件（重複スキップ対象）", len(applied_keys))

    stats = {"rename": 0, "discard": 0, "skip": 0, "already_applied": 0, "error": 0}

    for item in items:
        source_name = item.get("source_file_name", "")
        approved_name = item.get("approved_file_name", "")
        decision = item.get("decision", "skip")

        # 同一 (source, approved) の組み合わせが既に適用済みならスキップ
        if decision == "rename" and (source_name, approved_name) in applied_keys:
            logger.info(
                "SKIP (already applied): %s → %s", source_name, approved_name
            )
            stats["already_applied"] += 1
            continue

        if decision == "rename":
            ok = _apply_rename(item, logger)
            stats["rename" if ok else "error"] += 1

        elif decision == "discard":
            logger.info("DISCARD    %s (notes: %s)", source_name, item.get("notes", ""))
            stats["discard"] += 1

        elif decision == "skip":
            logger.info("SKIP       %s", source_name)
            stats["skip"] += 1

        else:
            logger.warning("不明な decision '%s' — skip します: %s", decision, source_name)
            stats["skip"] += 1

    logger.info(
        "=== 完了 === rename:%d  discard:%d  skip:%d  already_applied:%d  error:%d",
        stats["rename"], stats["discard"], stats["skip"],
        stats["already_applied"], stats["error"],
    )

    if stats["rename"] > 0:
        logger.info("processing/renamed/ と processing/metadata-ready/ を確認してください。")
    if stats["discard"] > 0:
        logger.info("廃棄対象 %d 件 — inbox から手動削除し、ログに記録してください。", stats["discard"])
    if stats["already_applied"] > 0:
        logger.info("再適用スキップ %d 件 — applied/ に既に処理済みの決定があります。", stats["already_applied"])

    # 処理済み decisions ファイルを applied/ へ移動（再適用防止）
    _archive_decisions(decisions_path, timestamp, logger)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        description="review-decisions.json を処理して rename/discard/skip を実行する"
    )
    parser.add_argument(
        "--decisions",
        type=Path,
        default=DECISIONS_FILE,
        help=f"review-decisions.json のパス (デフォルト: {DECISIONS_FILE})",
    )
    args = parser.parse_args()
    run(decisions_path=args.decisions)
