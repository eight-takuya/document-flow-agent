"""
export_utils.py

export/ ディレクトリ構造 v2 に関する共通ユーティリティ。

Export structure v2:
    export/
    ├── files/
    │   ├── Receipt/
    │   ├── Finance/
    │   ├── Utility/
    │   ├── Insurance/
    │   ├── School/
    │   ├── Government/
    │   ├── Medical/
    │   ├── Work/
    │   ├── Contract/
    │   ├── Tax/
    │   └── Other/
    └── metadata/
        └── <同構造>

generate_metadata.py / validate_metadata.py / export_to_dropbox.py
migrate_export_v2.py から呼び出される。
"""

import re
import unicodedata
from pathlib import Path
from typing import Optional


def _nfc(s: str) -> str:
    """macOS HFS+ は NFD でファイル名を保存するため、NFC に正規化して比較する。"""
    return unicodedata.normalize("NFC", s)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_CATEGORIES = {
    "Receipt", "Utility", "Finance", "Insurance", "School",
    "Government", "Medical", "Work", "Contract", "Tax", "Other",
}

# ファイル名の末尾重複連番パターン（-001, -002 ...）
_SUFFIX_RE = re.compile(r"-\d{3}$")

# 旧 category → v2 category 移行マップ
CATEGORY_MIGRATION: dict[str, str] = {
    "Expense": "Other",
}

# ---------------------------------------------------------------------------
# Document keyword → category 推論テーブル
# (category が不明なファイルに対してドキュメント名から推論する)
# ---------------------------------------------------------------------------

#: (マッチキーワードリスト, category) — 上から順に評価し、最初にマッチしたものを使用
DOCUMENT_CATEGORY_HINTS: list[tuple] = [
    # Government
    (["適用事業所", "変更通知書", "組合員証", "履歴事項全部証明書",
      "登記", "証明書", "行政", "交通反則", "保険証明書"], "Government"),
    # Contract
    (["御見積書", "見積書", "請求書", "発注書", "納品書", "契約書"], "Contract"),
    # Work
    (["業務完了通知書", "業務報告書", "業務委託"], "Work"),
    # School
    (["成績通知", "探究ゼミ", "講師派遣", "職業講演会", "Teams接続情報"], "School"),
    # Finance
    (["クレジットカード", "ETCカード", "ETcカード", "エボスETC",
      "ご利用明細", "引落通知", "振込明細", "口座明細", "カードについて"], "Finance"),
    # Tax
    (["課税通知", "納税通知", "確定申告"], "Tax"),
    # Medical
    (["診療明細", "処方箋", "医療費"], "Medical"),
    # Utility
    (["水道料金", "水道使用量", "電気料金", "ガス料金"], "Utility"),
    # Receipt
    (["領収書", "領収証", "レシート", "タクシー領収書"], "Receipt"),
    # Insurance
    (["保険", "共済", "確定拠出年金"], "Insurance"),
]


# ---------------------------------------------------------------------------
# Category extraction from filename
# ---------------------------------------------------------------------------

def extract_category_from_filename(filename: str) -> Optional[str]:
    """
    YYYYMMDD-Category-Document-... 形式のファイル名から category を抽出する。

    末尾の -001, -002 ... 連番は無視する。
    macOS NFD ファイル名を NFC に正規化してから比較する。

    Returns:
        有効な category 文字列、または None（含まれない場合）
    """
    stem = _nfc(Path(filename).stem)
    # 末尾連番を除去
    stem = _SUFFIX_RE.sub("", stem)
    parts = stem.split("-")
    if len(parts) >= 2:
        candidate = parts[1]
        if candidate in VALID_CATEGORIES:
            return candidate
        # 移行マップにあれば変換
        if candidate in CATEGORY_MIGRATION:
            return CATEGORY_MIGRATION[candidate]
    return None


def infer_category_from_document(document_or_filename: str) -> str:
    """
    ドキュメント名またはファイル名のキーワードから category を推論する。
    マッチしない場合は "Other" を返す。
    macOS NFD ファイル名を NFC に正規化してから比較する。
    """
    text = _nfc(document_or_filename)
    for keywords, cat in DOCUMENT_CATEGORY_HINTS:
        if any(kw in text for kw in keywords):
            return cat
    return "Other"


def get_category(
    filename: str,
    metadata: Optional[dict] = None,
    use_inference: bool = True,
) -> str:
    """
    ファイル名 → metadata → ドキュメントキーワード推論 の優先順で category を決定する。

    Args:
        filename:       処理対象のファイル名（PDF or metadata JSON）
        metadata:       対応する metadata dict（なければ None）
        use_inference:  True の場合、不明時にドキュメントキーワード推論を適用する

    Returns:
        有効な category 文字列（必ず VALID_CATEGORIES のいずれか）
    """
    # 1. ファイル名から抽出
    cat = extract_category_from_filename(filename)
    if cat:
        return cat

    # 2. metadata から取得
    if metadata:
        meta_cat = str(metadata.get("category") or "").strip()
        if meta_cat in VALID_CATEGORIES and meta_cat != "Other":
            return meta_cat

    # 3. ドキュメントキーワード推論（ファイル名から）
    if use_inference:
        cat = infer_category_from_document(filename)
        if cat != "Other":
            return cat

    # 4. metadata の category（Other でも採用）
    if metadata:
        meta_cat = str(metadata.get("category") or "").strip()
        if meta_cat in VALID_CATEGORIES:
            return meta_cat

    return "Other"


# ---------------------------------------------------------------------------
# Filename with category insertion
# ---------------------------------------------------------------------------

def insert_category_into_filename(filename: str, category: str) -> str:
    """
    YYYYMMDD-Document-... → YYYYMMDD-Category-Document-... に変換する。
    すでに category が含まれている場合はそのまま返す。

    Args:
        filename: 対象ファイル名
        category: 挿入する category

    Returns:
        category 挿入済みファイル名
    """
    # すでに category が含まれていれば変換不要
    if extract_category_from_filename(filename) is not None:
        return filename

    stem = Path(filename).stem
    suffix = Path(filename).suffix

    # 末尾連番を退避
    seq_match = _SUFFIX_RE.search(stem)
    seq_suffix = seq_match.group(0) if seq_match else ""
    if seq_suffix:
        stem = stem[: -len(seq_suffix)]

    # YYYYMMDD-... かチェック
    parts = stem.split("-", 1)
    if len(parts) == 2 and re.match(r"^\d{8}$", parts[0]):
        return f"{parts[0]}-{category}-{parts[1]}{seq_suffix}{suffix}"
    else:
        # 日付なし形式 — 先頭に category を付与
        return f"{category}-{stem}{seq_suffix}{suffix}"


# ---------------------------------------------------------------------------
# Export path builders
# ---------------------------------------------------------------------------

ROOT = Path(__file__).parent.parent
EXPORT_DIR = ROOT / "export"
EXPORT_FILES_DIR = EXPORT_DIR / "files"
EXPORT_META_DIR = EXPORT_DIR / "metadata"


def get_export_pdf_dir(category: str) -> Path:
    """export/files/<category>/ パスを返す。"""
    return EXPORT_FILES_DIR / category


def get_export_meta_dir(category: str) -> Path:
    """export/metadata/<category>/ パスを返す。"""
    return EXPORT_META_DIR / category


def safe_copy_dest(dest_dir: Path, filename: str) -> Path:
    """
    重複時に -001, -002 ... の連番を付けた保存先パスを返す（overwrite しない）。
    """
    candidate = dest_dir / filename
    if not candidate.exists():
        return candidate
    stem = Path(filename).stem
    suffix_ext = Path(filename).suffix

    # metadata.json の二重拡張子対応
    if filename.endswith(".metadata.json"):
        stem = filename[: -len(".metadata.json")]
        suffix_ext = ".metadata.json"

    for i in range(1, 1000):
        candidate = dest_dir / f"{stem}-{i:03d}{suffix_ext}"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"空きパスが見つかりません: {filename}")


def all_category_dirs() -> list[str]:
    """v2 で使用する category ディレクトリ名の一覧（ソート済み）。"""
    return sorted(VALID_CATEGORIES)
