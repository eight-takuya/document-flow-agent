"""
split_receipts.py

複数ページ PDF を 1ページ = 1PDF に分解する。
scan / split の2フェーズで構成。

出力先: processing/splitted/
命名例:
  元ファイル: 20260522_receipts.pdf
  出力:       20260522_receipts-p001.pdf
              20260522_receipts-p002.pdf

Usage:
    python scripts/split_receipts.py                 # inbox/ 内の複数ページ PDF を一覧
    python scripts/split_receipts.py --dry-run       # 分割予定を表示（ファイルは作らない）
    python scripts/split_receipts.py --apply         # 実際に分割して processing/splitted/ へ出力
    python scripts/split_receipts.py <pdf_path>      # 単一 PDF を分割（--apply が必要）
"""

import argparse
import sys
from pathlib import Path
from typing import List, Optional, Tuple

try:
    from pypdf import PdfReader, PdfWriter
    PYPDF_AVAILABLE = True
except ImportError:
    PYPDF_AVAILABLE = False

REPO_ROOT = Path(__file__).parent.parent
INBOX_DIR = REPO_ROOT / "inbox"
SPLIT_DIR = REPO_ROOT / "processing" / "splitted"

# 分割対象の最大ページ数。これを超えるPDFは「書類（1文書）」とみなして分割しない。
# 領収証バンドルは通常1〜5ページ程度なので、この閾値で大型文書を除外できる。
DEFAULT_SPLIT_MAX_PAGES = 5


# ---------------------------------------------------------------------------
# Page count
# ---------------------------------------------------------------------------

def count_pages(pdf_path: Path) -> int:
    """PDF のページ数を返す。読み取り失敗時は -1 を返す。"""
    if not PYPDF_AVAILABLE:
        # フォールバック: mdls でページ数を確認 (macOS)
        import subprocess
        r = subprocess.run(
            ["mdls", "-name", "kMDItemNumberOfPages", str(pdf_path)],
            capture_output=True, text=True,
        )
        for tok in r.stdout.split():
            try:
                return int(tok)
            except ValueError:
                pass
        return -1
    try:
        reader = PdfReader(str(pdf_path))
        return len(reader.pages)
    except Exception:
        return -1


# ---------------------------------------------------------------------------
# Split
# ---------------------------------------------------------------------------

def split_pdf(
    pdf_path: Path,
    output_dir: Path = SPLIT_DIR,
    dry_run: bool = False,
) -> List[Path]:
    """
    PDF を 1ページ = 1PDF に分割して output_dir に保存する。

    Args:
        pdf_path:   分割元 PDF パス
        output_dir: 出力ディレクトリ（processing/splitted/）
        dry_run:    True の場合はファイルを書き出さず、出力パスのリストだけを返す

    Returns:
        生成した（または生成予定の）Path のリスト

    Raises:
        RuntimeError: pypdf が使えない場合
        ValueError:   PDF 読み取り失敗 / 1ページ以下
    """
    if not PYPDF_AVAILABLE:
        raise RuntimeError("pypdf がインストールされていません。pip install pypdf でインストールしてください。")

    try:
        reader = PdfReader(str(pdf_path))
        n = len(reader.pages)
    except Exception as e:
        raise ValueError(f"PDF 読み取り失敗: {pdf_path.name} — {e}")

    if n <= 1:
        raise ValueError(f"分割不要（{n} ページ）: {pdf_path.name}")

    stem = pdf_path.stem
    results: List[Path] = []

    if not dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)

    for i, page in enumerate(reader.pages, start=1):
        out_name = f"{stem}-p{i:03d}.pdf"
        out_path = output_dir / out_name

        if not dry_run:
            # 既に分割済みなら上書きしない (idempotent)
            if not out_path.exists():
                writer = PdfWriter()
                writer.add_page(page)
                with open(out_path, "wb") as f:
                    writer.write(f)

        results.append(out_path)

    return results


# ---------------------------------------------------------------------------
# Scan inbox
# ---------------------------------------------------------------------------

def scan_inbox_multipage(
    inbox_dir: Path = INBOX_DIR,
    split_max_pages: int = DEFAULT_SPLIT_MAX_PAGES,
) -> Tuple[List[Tuple[Path, int]], List[Tuple[Path, int]]]:
    """
    inbox/ の複数ページ PDF をスキャンし、分割対象と除外対象に分けて返す。

    Args:
        inbox_dir:        スキャン対象ディレクトリ
        split_max_pages:  この値以下のページ数のみ分割。超えるものは書類として除外。

    Returns:
        (split_targets, skip_targets)
        split_targets: (path, page_count) のリスト — 分割対象
        skip_targets:  (path, page_count) のリスト — ページ超過・書類として除外
    """
    split_targets: List[Tuple[Path, int]] = []
    skip_targets: List[Tuple[Path, int]] = []
    for f in sorted(inbox_dir.iterdir()):
        if not f.is_file() or f.suffix.lower() != ".pdf":
            continue
        if f.name.startswith(".") or f.name == ".DS_Store":
            continue
        n = count_pages(f)
        if n <= 1:
            continue
        if n <= split_max_pages:
            split_targets.append((f, n))
        else:
            skip_targets.append((f, n))
    return split_targets, skip_targets


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------

def _run_standalone(args: argparse.Namespace) -> None:
    dry_run = not args.apply

    if not PYPDF_AVAILABLE:
        print("ERROR: pypdf がインストールされていません。")
        print("  pip install pypdf")
        sys.exit(1)

    # 単一 PDF 指定の場合
    if args.pdf:
        pdf_path = Path(args.pdf)
        if not pdf_path.exists():
            print(f"ERROR: ファイルが見つかりません: {pdf_path}")
            sys.exit(1)
        n = count_pages(pdf_path)
        if n <= 1:
            print(f"  {pdf_path.name}: {n} ページ — 分割不要")
            return
        print(f"  {pdf_path.name}: {n} ページ → 分割{'予定' if dry_run else ''}...")
        pages = split_pdf(pdf_path, SPLIT_DIR, dry_run=dry_run)
        for p in pages:
            status = "(dry-run)" if dry_run else "OK"
            print(f"    → {p.name}  {status}")
        return

    # inbox/ 全体スキャン
    max_pages = args.max_pages
    split_targets, skip_targets = scan_inbox_multipage(split_max_pages=max_pages)
    total_pages = sum(n for _, n in split_targets)

    print(f"=== split_receipts.py  mode={'dry-run' if dry_run else 'apply'}  max-pages={max_pages} ===")
    print(f"分割対象: {len(split_targets)} 件  /  分割後PDF数: {total_pages}")
    if skip_targets:
        print(f"除外（>{max_pages}ページ書類）: {len(skip_targets)} 件")
    print()

    if not split_targets and not skip_targets:
        print("  複数ページ PDF なし")
        return

    if split_targets:
        print("[分割対象]")
        for pdf_path, n in split_targets:
            print(f"  {pdf_path.name}  ({n} ページ)")
            pages = split_pdf(pdf_path, SPLIT_DIR, dry_run=dry_run)
            for p in pages:
                status = "(dry-run: 未作成)" if dry_run else ("既存" if p.exists() else "OK")
                print(f"    → {p.name}  {status}")
        print()

    if skip_targets:
        print(f"[除外 — {max_pages}ページ超の書類として除外・元PDFをそのまま処理]")
        for pdf_path, n in skip_targets:
            print(f"  {pdf_path.name}  ({n} ページ)  → 分割スキップ")
        print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="複数ページ PDF を 1ページ = 1PDF に分割する",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python scripts/split_receipts.py               # inbox の複数ページ PDF を一覧（dry-run）
  python scripts/split_receipts.py --apply       # inbox の全複数ページ PDF を分割
  python scripts/split_receipts.py inbox/foo.pdf --apply  # 単一 PDF を分割
        """,
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--dry-run", action="store_true", default=False,
                            help="分割予定を表示するだけ（ファイルは作らない）")
    mode_group.add_argument("--apply", action="store_true", default=False,
                            help="実際に分割して processing/splitted/ へ出力")
    parser.add_argument("--max-pages", type=int, default=DEFAULT_SPLIT_MAX_PAGES,
                        metavar="N",
                        help=f"この値以下のページ数のみ分割（デフォルト: {DEFAULT_SPLIT_MAX_PAGES}）。超えるものは大型文書として除外")
    parser.add_argument("pdf", nargs="?", help="単一 PDF パスを指定（省略時は inbox/ 全体）")
    _args = parser.parse_args()
    _run_standalone(_args)
