"""
scan_inbox_watcher.py

inbox/ を監視し、新しい PDF が追加されたら classify_documents.py を自動実行する。
watchdog ライブラリを使ったファイルシステムウォッチャー。
"""

import time
import logging
from pathlib import Path

INBOX_DIR = Path(__file__).parent.parent / "inbox"
LOGS_DIR = Path(__file__).parent.parent / "logs"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def on_new_pdf(pdf_path: Path) -> None:
    # TODO: classify_documents.run() を呼び出して新規 PDF を処理
    # TODO: 処理完了後に結果をログへ記録
    raise NotImplementedError


def build_handler():
    # TODO: watchdog の FileSystemEventHandler を継承したクラスを定義
    # TODO: on_created イベントで .pdf ファイルのみ on_new_pdf へ転送
    raise NotImplementedError


def run(poll_interval: int = 5) -> None:
    # TODO: watchdog の Observer を使って INBOX_DIR を再帰的に監視
    # TODO: KeyboardInterrupt で安全に停止できるようにする
    # TODO: watchdog が使えない環境向けに polling フォールバックも検討
    raise NotImplementedError


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="inbox/ を監視して自動分類を実行する")
    parser.add_argument(
        "--interval",
        type=int,
        default=5,
        help="ポーリング間隔（秒）。デフォルト: 5",
    )
    args = parser.parse_args()
    run(poll_interval=args.interval)
