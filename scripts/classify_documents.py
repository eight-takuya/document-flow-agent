"""
classify_documents.py

inbox/ 内の PDF ファイルをスキャンし、カテゴリを推定して分類する。
Claude API を使ってテキスト抽出・分類を行うことを想定。
"""

import os
import json
from pathlib import Path
from datetime import datetime

INBOX_DIR = Path(__file__).parent.parent / "inbox"
PROCESSING_DIR = Path(__file__).parent.parent / "processing"
LOGS_DIR = Path(__file__).parent.parent / "logs"
TEMPLATES_DIR = Path(__file__).parent.parent / "templates"

CATEGORIES = [
    "CONTRACT",
    "INVOICE",
    "RECEIPT",
    "REPORT",
    "NOTICE",
    "PERMIT",
    "OTHER",
]


def load_metadata_template() -> dict:
    # TODO: templates/metadata_template.json を読み込んで返す
    template_path = TEMPLATES_DIR / "metadata_template.json"
    with open(template_path) as f:
        return json.load(f)


def extract_text_from_pdf(pdf_path: Path) -> str:
    # TODO: PyMuPDF (fitz) または pdfplumber でテキスト抽出
    # TODO: テキストが取れない場合は OCR (tesseract / Vision API) にフォールバック
    raise NotImplementedError


def classify_with_claude(text: str) -> dict:
    # TODO: Anthropic SDK で Claude API を呼び出し
    # TODO: カテゴリ・タイトル・相手先・日付・保存期間を推定
    # TODO: metadata_template.json のスキーマに合わせた dict を返す
    raise NotImplementedError


def move_to_processing(pdf_path: Path, metadata: dict) -> Path:
    # TODO: processing/ へファイルを移動
    # TODO: 同名の .json メタデータファイルも生成して隣に置く
    raise NotImplementedError


def log_action(pdf_path: Path, metadata: dict, status: str) -> None:
    # TODO: logs/ に JSONL 形式でログを追記
    # TODO: {"timestamp": ..., "file": ..., "metadata": ..., "status": ...}
    raise NotImplementedError


def run() -> None:
    # TODO: inbox/ を走査して未処理 PDF を取得
    # TODO: 各ファイルに対して extract → classify → move → log を実行
    # TODO: エラーが出たファイルはスキップし、ログに記録してから継続
    raise NotImplementedError


if __name__ == "__main__":
    run()
