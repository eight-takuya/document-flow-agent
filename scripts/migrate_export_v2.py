"""
migrate_export_v2.py

export/files/ と export/metadata/ のフラット構造を
category 別サブディレクトリ構造（v2）へ移行する。

Usage:
    python scripts/migrate_export_v2.py             # dry-run（変更なし）
    python scripts/migrate_export_v2.py --report    # dry-run + レポート出力
    python scripts/migrate_export_v2.py --apply     # 実際に移行
    python scripts/migrate_export_v2.py --apply --report  # 移行 + レポート

Migration ルール:
    1. export/files/*.pdf → export/files/<category>/[<new_name>.pdf]
    2. export/metadata/*.metadata.json → export/metadata/<category>/[<new_name>.metadata.json]
    3. category が含まれていないファイルは category をファイル名に挿入する
    4. 衝突時は -001, -002 ... 付与（overwrite 禁止）
    5. 元ファイルは --apply でも削除しない（手動クリーンアップ）

Report 出力:
    - 移行ファイル一覧
    - rename（category 補完）一覧
    - 衝突一覧
    - metadata missing（orphan PDF）
    - orphan metadata（PDF なし）
    - category unknown（Other へフォールバック）
"""

import argparse
import json
import shutil
import unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional


def _nfc(s: str) -> str:
    """macOS HFS+ は NFD でファイル名を保存するため、比較前に NFC に正規化する。"""
    return unicodedata.normalize("NFC", s)

import sys
_SCRIPTS_DIR = Path(__file__).parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from export_utils import (
    EXPORT_FILES_DIR,
    EXPORT_META_DIR,
    VALID_CATEGORIES,
    extract_category_from_filename,
    get_category,
    get_export_meta_dir,
    get_export_pdf_dir,
    insert_category_into_filename,
    safe_copy_dest,
)

ROOT = Path(__file__).parent.parent
REPORTS_DIR = ROOT / "processing" / "metadata-reports"
METADATA_READY_DIR = ROOT / "processing" / "metadata-ready"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_metadata(meta_path: Path) -> Optional[dict]:
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _stem_of_pdf(pdf_name: str) -> str:
    """20260430-御見積書.pdf → 20260430-御見積書"""
    return Path(pdf_name).stem


def _meta_name_for_pdf(pdf_name: str) -> str:
    """20260430-御見積書.pdf → 20260430-御見積書.metadata.json"""
    return Path(pdf_name).stem + ".metadata.json"


def _collect_flat_pdfs() -> list[Path]:
    """export/files/ 直下の PDF 一覧（サブディレクトリは除外）。"""
    if not EXPORT_FILES_DIR.exists():
        return []
    return sorted(f for f in EXPORT_FILES_DIR.iterdir()
                  if f.is_file() and f.suffix.lower() == ".pdf")


def _collect_flat_metadata() -> list[Path]:
    """export/metadata/ 直下の .metadata.json 一覧（サブディレクトリは除外）。"""
    if not EXPORT_META_DIR.exists():
        return []
    return sorted(f for f in EXPORT_META_DIR.iterdir()
                  if f.is_file() and f.name.endswith(".metadata.json"))


# ---------------------------------------------------------------------------
# Plan builder
# ---------------------------------------------------------------------------

def build_migration_plan() -> dict:
    """
    移行計画を構築して返す。

    Returns:
        plan = {
            "moves":   list of MoveEntry,
            "orphan_pdfs":   list[str],   # metadata が見つからない PDF
            "orphan_meta":   list[str],   # PDF が見つからない metadata
            "unknown_cat":   list[str],   # Other にフォールバックしたファイル
            "renames":       list[str],   # category が補完されたファイル
            "conflicts":     list[str],   # 衝突が発生する予定のファイル
        }

    MoveEntry = {
        "pdf_src":     Path or None,
        "pdf_dest":    Path,
        "meta_src":    Path or None,
        "meta_dest":   Path,
        "category":    str,
        "pdf_renamed": bool,  # ファイル名が変わる場合 True
        "meta_renamed": bool,
        "pdf_new_name": str,
        "meta_new_name": str,
        "conflict_pdf": bool,
        "conflict_meta": bool,
    }
    """
    flat_pdfs  = _collect_flat_pdfs()
    flat_metas = _collect_flat_metadata()

    # metadata を stem でインデックス（NFC 正規化して比較）
    meta_by_stem: dict[str, Path] = {}
    for m in flat_metas:
        stem = _nfc(m.name[: -len(".metadata.json")])
        meta_by_stem[stem] = m

    pdf_stems_seen: set[str] = set()
    moves = []
    orphan_pdfs  = []
    orphan_metas = []
    unknown_cats = []
    renames      = []
    conflicts    = []

    for pdf in flat_pdfs:
        stem = _nfc(_stem_of_pdf(pdf.name))
        pdf_stems_seen.add(stem)
        meta_path = meta_by_stem.get(stem)

        # metadata を読み込む（category 判定に使う）
        meta_data: Optional[dict] = None
        if meta_path:
            meta_data = _load_metadata(meta_path)

        # 対応する metadata-ready/ の metadata も確認（NFC stem を使用）
        mready = METADATA_READY_DIR / (stem + ".metadata.json")
        if meta_data is None and mready.exists():
            meta_data = _load_metadata(mready)

        # category 決定
        category = get_category(pdf.name, metadata=meta_data, use_inference=True)
        if category == "Other" and extract_category_from_filename(pdf.name) is None:
            unknown_cats.append(pdf.name)

        # 新しいファイル名（category 補完）
        pdf_new_name = insert_category_into_filename(pdf.name, category)
        pdf_renamed  = pdf_new_name != pdf.name
        if pdf_renamed:
            renames.append(f"{pdf.name} → {pdf_new_name}")

        # metadata 新名
        if meta_path:
            meta_orig_name = meta_path.name
            meta_new_name  = insert_category_into_filename(
                Path(pdf_new_name).stem + ".metadata.json",
                category,
            )
            # insert_category_into_filename は PDF 用なので補正
            # → すでに category 付きの stem から生成するだけでOK
            meta_new_name = Path(pdf_new_name).stem + ".metadata.json"
            meta_renamed   = meta_new_name != meta_orig_name
        else:
            meta_orig_name = ""
            meta_new_name  = Path(pdf_new_name).stem + ".metadata.json"
            meta_renamed   = False
            orphan_pdfs.append(pdf.name)

        # 移行先パス
        pdf_dest_dir  = get_export_pdf_dir(category)
        meta_dest_dir = get_export_meta_dir(category)
        pdf_dest_candidate  = pdf_dest_dir / pdf_new_name
        meta_dest_candidate = meta_dest_dir / meta_new_name

        # 衝突チェック（既存サブディレクトリ内の同名ファイル）
        conflict_pdf  = pdf_dest_candidate.exists()
        conflict_meta = meta_dest_candidate.exists()
        if conflict_pdf or conflict_meta:
            conflicts.append(pdf.name)

        moves.append({
            "pdf_src":      pdf,
            "pdf_dest":     pdf_dest_candidate,
            "meta_src":     meta_path,
            "meta_dest":    meta_dest_candidate,
            "category":     category,
            "pdf_renamed":  pdf_renamed,
            "meta_renamed": meta_renamed if meta_path else False,
            "pdf_new_name": pdf_new_name,
            "meta_new_name": meta_new_name,
            "conflict_pdf":  conflict_pdf,
            "conflict_meta": conflict_meta,
        })

    # orphan metadata（対応 PDF がない）
    for stem, meta_path in meta_by_stem.items():
        if stem not in pdf_stems_seen:
            orphan_metas.append(meta_path.name)

    return {
        "moves":       moves,
        "orphan_pdfs": orphan_pdfs,
        "orphan_metas": orphan_metas,
        "unknown_cats": unknown_cats,
        "renames":      renames,
        "conflicts":    conflicts,
    }


# ---------------------------------------------------------------------------
# Dry-run print
# ---------------------------------------------------------------------------

def print_dry_run(plan: dict) -> None:
    moves = plan["moves"]
    by_cat: dict[str, list] = defaultdict(list)
    for m in moves:
        by_cat[m["category"]].append(m)

    print(f"\n=== migrate_export_v2 [DRY-RUN] ===")
    print(f"  対象 PDF          : {len(moves)} 件")
    print(f"  category 別:")
    for cat in sorted(by_cat):
        print(f"    {cat:<14}: {len(by_cat[cat])} 件")
    print()

    if plan["renames"]:
        print(f"  ── category 補完（{len(plan['renames'])} 件）──")
        for r in plan["renames"]:
            print(f"    {r}")
        print()

    if plan["conflicts"]:
        print(f"  ── 衝突（{len(plan['conflicts'])} 件）── ※ -001 付与して safe copy")
        for c in plan["conflicts"]:
            print(f"    {c}")
        print()

    if plan["orphan_pdfs"]:
        print(f"  ── metadata missing（orphan PDF: {len(plan['orphan_pdfs'])} 件）──")
        for o in plan["orphan_pdfs"]:
            print(f"    {o}")
        print()

    if plan["orphan_metas"]:
        print(f"  ── orphan metadata（PDF なし: {len(plan['orphan_metas'])} 件）──")
        for o in plan["orphan_metas"]:
            print(f"    {o}")
        print()

    if plan["unknown_cats"]:
        print(f"  ── category 不明 → Other にフォールバック（{len(plan['unknown_cats'])} 件）──")
        for u in plan["unknown_cats"]:
            print(f"    {u}")
        print()

    print("  ファイルは変更されていません（--apply で適用）")


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------

def apply_migration(plan: dict, report: bool) -> dict:
    """移行を実行する。元ファイルは削除しない（safe copy）。"""
    moved_pdfs  = 0
    moved_metas = 0
    renamed     = 0
    conflict_resolved = 0
    meta_content_updated = 0
    errors: list[str] = []
    log_entries: list[str] = []

    for m in plan["moves"]:
        pdf_src:  Path        = m["pdf_src"]
        meta_src: Optional[Path] = m["meta_src"]
        category:  str        = m["category"]
        pdf_new_name:  str    = m["pdf_new_name"]
        meta_new_name: str    = m["meta_new_name"]

        # --- PDF コピー ---
        pdf_dest_dir = get_export_pdf_dir(category)
        pdf_dest_dir.mkdir(parents=True, exist_ok=True)
        pdf_dest = safe_copy_dest(pdf_dest_dir, pdf_new_name)
        if pdf_dest.name != pdf_new_name:
            conflict_resolved += 1

        try:
            shutil.copy2(pdf_src, pdf_dest)
            moved_pdfs += 1
            if m["pdf_renamed"]:
                renamed += 1
            log_entries.append(
                f"PDF  {pdf_src.name} → {category}/{pdf_dest.name}"
                + (" [renamed]" if m["pdf_renamed"] else "")
                + (" [conflict→safe]" if pdf_dest.name != pdf_new_name else "")
            )
        except Exception as e:
            errors.append(f"PDF COPY ERROR {pdf_src.name}: {e}")
            continue

        # --- metadata コピー + 内容更新 ---
        if meta_src:
            meta_dest_dir = get_export_meta_dir(category)
            meta_dest_dir.mkdir(parents=True, exist_ok=True)
            meta_dest = safe_copy_dest(meta_dest_dir, meta_new_name)

            try:
                # metadata JSON の内容を読み込んで file_name を更新（renamed の場合）
                meta_data = _load_metadata(meta_src) or {}
                if m["pdf_renamed"] or m["meta_renamed"]:
                    meta_data["file_name"] = pdf_dest.name
                    meta_data["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    meta_content_updated += 1

                meta_dest.write_text(
                    json.dumps(meta_data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                moved_metas += 1
                log_entries.append(
                    f"META {meta_src.name} → {category}/{meta_dest.name}"
                    + (" [renamed]" if m["meta_renamed"] else "")
                )
            except Exception as e:
                errors.append(f"META COPY ERROR {meta_src.name}: {e}")

    result = {
        "moved_pdfs":   moved_pdfs,
        "moved_metas":  moved_metas,
        "renamed":      renamed,
        "conflict_resolved": conflict_resolved,
        "meta_content_updated": meta_content_updated,
        "errors":       errors,
        "log_entries":  log_entries,
        "orphan_pdfs":  plan["orphan_pdfs"],
        "orphan_metas": plan["orphan_metas"],
        "unknown_cats": plan["unknown_cats"],
        "plan_renames": plan["renames"],
    }
    return result


def print_apply_result(result: dict) -> None:
    print(f"\n=== migrate_export_v2 [APPLY 完了] ===")
    print(f"  PDF 移行      : {result['moved_pdfs']} 件")
    print(f"  metadata 移行 : {result['moved_metas']} 件")
    print(f"  ファイル名補完: {result['renamed']} 件")
    print(f"  衝突safe copy : {result['conflict_resolved']} 件")
    print(f"  metadata更新  : {result['meta_content_updated']} 件")
    if result["errors"]:
        print(f"  ERROR         : {len(result['errors'])} 件")
        for e in result["errors"]:
            print(f"    ❌ {e}")
    print()
    if result["orphan_pdfs"]:
        print(f"  ⚠ orphan PDF（metadata なし）: {len(result['orphan_pdfs'])} 件")
    if result["orphan_metas"]:
        print(f"  ⚠ orphan metadata（PDF なし）: {len(result['orphan_metas'])} 件")
    print()
    print("  ✅ 元ファイルは export/files/*.pdf / export/metadata/*.metadata.json に残っています。")
    print("     移行確認後、不要になったフラットファイルは手動で削除してください。")


# ---------------------------------------------------------------------------
# Report output
# ---------------------------------------------------------------------------

def write_report(plan: dict, result: Optional[dict], timestamp: str) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    by_cat: dict[str, list] = defaultdict(list)
    for m in plan["moves"]:
        by_cat[m["category"]].append(m)

    md_lines = [
        f"# export v2 migration report — {timestamp}",
        "",
        "## サマリー",
        "",
        f"| 項目 | 数 |",
        f"|---|---|",
        f"| 対象 PDF 件数 | {len(plan['moves'])} |",
        f"| category 補完（rename） | {len(plan['renames'])} |",
        f"| 衝突 | {len(plan['conflicts'])} |",
        f"| orphan PDF（metadata なし） | {len(plan['orphan_pdfs'])} |",
        f"| orphan metadata（PDF なし） | {len(plan['orphan_metas'])} |",
        f"| category 不明 → Other | {len(plan['unknown_cats'])} |",
        "",
        "## category 別 移行件数",
        "",
        "| category | 件数 |",
        "|---|---|",
    ]
    for cat in sorted(by_cat):
        md_lines.append(f"| {cat} | {len(by_cat[cat])} |")
    md_lines.append("")

    if plan["renames"]:
        md_lines += [
            "## category 補完（ファイル名変更）",
            "",
        ]
        for r in plan["renames"]:
            md_lines.append(f"- `{r}`")
        md_lines.append("")

    if plan["conflicts"]:
        md_lines += [
            "## 衝突ファイル（-001 付与で safe copy）",
            "",
        ]
        for c in plan["conflicts"]:
            md_lines.append(f"- `{c}`")
        md_lines.append("")

    if plan["orphan_pdfs"]:
        md_lines += [
            "## orphan PDF（metadata なし）",
            "",
        ]
        for o in plan["orphan_pdfs"]:
            md_lines.append(f"- `{o}`")
        md_lines.append("")

    if plan["orphan_metas"]:
        md_lines += [
            "## orphan metadata（PDF なし）",
            "",
        ]
        for o in plan["orphan_metas"]:
            md_lines.append(f"- `{o}`")
        md_lines.append("")

    if plan["unknown_cats"]:
        md_lines += [
            "## category 不明 → Other",
            "",
        ]
        for u in plan["unknown_cats"]:
            md_lines.append(f"- `{u}`")
        md_lines.append("")

    if result:
        md_lines += [
            "## 適用結果",
            "",
            f"| 項目 | 数 |",
            f"|---|---|",
            f"| PDF 移行 | {result['moved_pdfs']} |",
            f"| metadata 移行 | {result['moved_metas']} |",
            f"| ファイル名補完 | {result['renamed']} |",
            f"| 衝突 safe copy | {result['conflict_resolved']} |",
            f"| metadata 内容更新 | {result['meta_content_updated']} |",
            f"| エラー | {len(result['errors'])} |",
            "",
        ]
        if result["errors"]:
            md_lines += ["### エラー詳細", ""]
            for e in result["errors"]:
                md_lines.append(f"- {e}")
            md_lines.append("")

    # JSON
    json_data = {
        "timestamp": timestamp,
        "plan": {
            "total_pdfs": len(plan["moves"]),
            "renames": plan["renames"],
            "conflicts": plan["conflicts"],
            "orphan_pdfs": plan["orphan_pdfs"],
            "orphan_metas": plan["orphan_metas"],
            "unknown_cats": plan["unknown_cats"],
            "by_category": {cat: len(items) for cat, items in by_cat.items()},
        },
        "result": result,
    }
    json_path = REPORTS_DIR / f"export-v2-migration-{timestamp}.json"
    md_path   = REPORTS_DIR / f"export-v2-migration-{timestamp}.md"

    json_path.write_text(json.dumps(json_data, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text("\n".join(md_lines), encoding="utf-8")

    print(f"\nレポート保存:")
    print(f"  [JSON] {json_path.relative_to(ROOT)}")
    print(f"  [MD]   {md_path.relative_to(ROOT)}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="export/ フラット構造 → category サブディレクトリ構造（v2）へ移行する",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python scripts/migrate_export_v2.py              # dry-run（変更なし）
  python scripts/migrate_export_v2.py --report     # dry-run + レポート出力
  python scripts/migrate_export_v2.py --apply      # 実際に移行
  python scripts/migrate_export_v2.py --apply --report  # 移行 + レポート
        """,
    )
    parser.add_argument("--apply",  action="store_true", help="実際にファイルを移行する")
    parser.add_argument("--report", action="store_true", help="JSON/MD レポートを出力する")
    args = parser.parse_args()

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    print(f"=== migrate_export_v2.py  {'APPLY' if args.apply else 'DRY-RUN'}  {timestamp} ===")

    print("\n移行計画を構築中...")
    plan = build_migration_plan()

    print_dry_run(plan)

    result = None
    if args.apply:
        print("\n移行を実行します...")
        result = apply_migration(plan, report=args.report)
        print_apply_result(result)

    if args.report:
        write_report(plan, result, timestamp)


if __name__ == "__main__":
    main()
