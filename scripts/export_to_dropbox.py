"""
export_to_dropbox.py

export/ 内のファイルを Dropbox の 99_Imported/ へ移動する。
Dropbox のローカル同期フォルダを直接操作することを想定。
"""

import shutil
from pathlib import Path

EXPORT_DIR = Path(__file__).parent.parent / "export"
LOGS_DIR = Path(__file__).parent.parent / "logs"

# Dropbox ローカル同期フォルダのパス（環境に合わせて変更）
# 例: Path.home() / "Dropbox" / "00_DocumentVault" / "99_Imported"
DROPBOX_IMPORTED_DIR: Path | None = None


def get_dropbox_dir() -> Path:
    # TODO: DROPBOX_IMPORTED_DIR が None なら環境変数 DROPBOX_VAULT_PATH を参照
    # TODO: それも未設定なら例外を raise して終了
    raise NotImplementedError


def list_export_files() -> list[Path]:
    # TODO: export/ 内の PDF ファイルを一覧で返す（.gitkeep は除外）
    raise NotImplementedError


def copy_to_dropbox(src: Path, dest_dir: Path) -> Path:
    # TODO: src を dest_dir へコピー（同名ファイルがあればサフィックスを付与）
    # TODO: コピー成功後に src を削除して export/ を空にする
    raise NotImplementedError


def log_export(src: Path, dest: Path) -> None:
    # TODO: logs/ に JSONL 形式でエクスポートログを追記
    raise NotImplementedError


def run(dry_run: bool = False) -> None:
    # TODO: dry_run=True の場合はファイル移動せずログだけ出力
    # TODO: list_export_files → copy_to_dropbox → log_export の順で処理
    # TODO: 処理後に export/ が空であることを確認してサマリを出力
    raise NotImplementedError


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="export/ の内容を Dropbox へ移動する")
    parser.add_argument("--dry-run", action="store_true", help="ファイルを実際に移動しない")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
