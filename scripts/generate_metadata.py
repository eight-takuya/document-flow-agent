"""
generate_metadata.py

処理済みファイルに対してメタデータ JSON を生成・補完する。
classify_documents.py で生成できなかった項目を補完する用途にも使う。
"""

import json
from pathlib import Path
from datetime import datetime, date

PROCESSING_DIR = Path(__file__).parent.parent / "processing"
TEMPLATES_DIR = Path(__file__).parent.parent / "templates"

# 保存期間定義（年単位）
RETENTION_PERIODS = {
    "CONTRACT": 7,
    "INVOICE": 7,
    "RECEIPT": 5,
    "REPORT": 3,
    "NOTICE": 1,
    "PERMIT": 10,
    "OTHER": 3,
}


def load_template() -> dict:
    # TODO: templates/metadata_template.json を読み込んで返す
    raise NotImplementedError


def calculate_discard_date(event_date: str, category: str) -> str:
    # TODO: event_date (YYYY-MM-DD) と category から保存期間を計算
    # TODO: 廃棄予定日 (YYYY-MM-DD) を返す
    raise NotImplementedError


def generate_metadata(pdf_path: Path, overrides: dict | None = None) -> dict:
    # TODO: テンプレートをベースに、PDF のテキストや overrides から補完
    # TODO: discard_date を calculate_discard_date で自動計算
    # TODO: 生成した metadata を pdf_path と同名の .json として保存
    raise NotImplementedError


def validate_metadata(metadata: dict) -> list[str]:
    # TODO: 必須フィールド (title, category, event_date) が埋まっているか確認
    # TODO: 問題があればフィールド名のリストを返す（空リストなら OK）
    raise NotImplementedError


def run() -> None:
    # TODO: processing/ を走査して .json が存在しない PDF を検出
    # TODO: generate_metadata を呼び出して .json を生成
    # TODO: validate_metadata で問題があればログに警告を記録
    raise NotImplementedError


if __name__ == "__main__":
    run()
