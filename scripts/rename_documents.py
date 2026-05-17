"""
rename_documents.py

processing/ 内のファイルを命名規則に従ってリネームする。
命名規則: YYYYMMDD_カテゴリ_相手先_概要.pdf
"""

import re
from pathlib import Path

PROCESSING_DIR = Path(__file__).parent.parent / "processing"
LOGS_DIR = Path(__file__).parent.parent / "logs"

NAMING_PATTERN = r"^\d{8}_[A-Z]+_.+_.+\.pdf$"


def build_filename(metadata: dict) -> str:
    # TODO: metadata の event_date, category, counterparty, title から
    #       YYYYMMDD_カテゴリ_相手先_概要.pdf 形式のファイル名を生成
    # TODO: 禁則文字（スペース・スラッシュ等）をアンダースコアに置換
    raise NotImplementedError


def validate_filename(filename: str) -> bool:
    # TODO: NAMING_PATTERN に一致するか検証して bool を返す
    raise NotImplementedError


def rename_file(current_path: Path, new_name: str) -> Path:
    # TODO: 同名ファイルが存在する場合はサフィックス (_2, _3 ...) を付与
    # TODO: リネーム実行し、新しい Path を返す
    raise NotImplementedError


def load_metadata(pdf_path: Path) -> dict:
    # TODO: pdf_path と同名の .json ファイルを読み込んで返す
    raise NotImplementedError


def log_rename(old_path: Path, new_path: Path) -> None:
    # TODO: logs/ に JSONL 形式でリネームログを追記
    raise NotImplementedError


def run() -> None:
    # TODO: processing/ を走査してメタデータ付き PDF を取得
    # TODO: build_filename → validate → rename → log の順で処理
    raise NotImplementedError


if __name__ == "__main__":
    run()
