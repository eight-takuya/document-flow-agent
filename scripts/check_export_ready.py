"""
check_export_ready.py

export 可能かどうかを判定して結果を表示する。

判定条件:
  [NG]   review-decisions.json が review-required/ に残っている
  [NG]   processing/renamed/ に PDF がない
  [WARN] 最新の review-report に未処理の可能性があるファイルが残っている
  [WARN] processing/ocr-error/ にレポートが残っている
  [WARN] PDF と metadata が対応していないペアがある
  [OK]   上記問題がなければ export 可能

Usage:
    python scripts/check_export_ready.py
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
RENAMED_DIR = ROOT / "processing" / "renamed"
AUTO_APPROVED_DIR = ROOT / "processing" / "auto-approved"
METADATA_DIR = ROOT / "processing" / "metadata-ready"
REVIEW_DIR = ROOT / "processing" / "review-required"
APPLIED_DIR = REVIEW_DIR / "applied"
DECISIONS_FILE = REVIEW_DIR / "review-decisions.json"
OCR_ERROR_DIR = ROOT / "processing" / "ocr-error"
EXPORT_DIR = ROOT / "export"


def _applied_source_names() -> set:
    """applied/ 内の全決定から処理済み source_file_name を収集する。"""
    names: set = set()
    if not APPLIED_DIR.exists():
        return names
    for f in APPLIED_DIR.glob("*.applied.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            for item in data.get("items", []):
                src = item.get("source_file_name", "")
                if src:
                    names.add(src)
        except Exception:
            pass
    return names


def _pending_review_files() -> list:
    """
    最新の review-report JSON を読んで、applied/ に記録されていない
    source_file_name を返す。処理済みか不明なファイルを WARN 対象とする。
    """
    reports = sorted(REVIEW_DIR.glob("review-report-*.json"), reverse=True)
    if not reports:
        return []

    latest = reports[0]
    try:
        data = json.loads(latest.read_text(encoding="utf-8"))
    except Exception:
        return []

    applied = _applied_source_names()
    pending = []
    for f in data.get("files", []):
        name = f.get("name", "")
        if name and name not in applied:
            pending.append(name)
    return pending


def _renamed_pdfs() -> list:
    files = []
    for d in (RENAMED_DIR, AUTO_APPROVED_DIR):
        if d.exists():
            files.extend(f for f in d.glob("*.pdf") if f.name != ".gitkeep")
    return files


def _metadata_jsons() -> list:
    if not METADATA_DIR.exists():
        return []
    return [f for f in METADATA_DIR.glob("*.metadata.json")]


def _ocr_error_report_count() -> int:
    if not OCR_ERROR_DIR.exists():
        return 0
    return len([f for f in OCR_ERROR_DIR.glob("*.html")])


def _unmatched_pdfs(pdfs: list, metadata: list) -> list:
    """PDF に対応する metadata がないファイルを返す。"""
    metadata_stems = {f.name.replace(".metadata.json", "") for f in metadata}
    return [p for p in pdfs if p.stem not in metadata_stems]


def run() -> bool:
    issues = []
    warnings = []
    infos = []

    # 1. review-decisions.json が残っていないか
    if DECISIONS_FILE.exists():
        issues.append(
            "review-decisions.json が残っています。"
            "apply_review_decisions.py を実行してください"
        )
    else:
        infos.append("review-required decisions applied")

    # 2. 最新の review-report に未処理の可能性があるファイルがないか
    pending = _pending_review_files()
    if pending:
        warnings.append(
            f"以下のファイルが review-required だったが、applied/ に決定記録がありません: "
            + ", ".join(pending)
        )

    # 3. renamed/ または auto-approved/ に PDF があるか
    renamed_pdfs = _renamed_pdfs()
    if not renamed_pdfs:
        issues.append("processing/renamed/ および processing/auto-approved/ に PDF がありません")
    else:
        infos.append(f"renamed/auto-approved files found: {len(renamed_pdfs)}")

    # 4. metadata-ready/ に metadata があるか
    metadata_jsons = _metadata_jsons()
    if metadata_jsons:
        infos.append(f"metadata files found: {len(metadata_jsons)}")
    else:
        warnings.append("processing/metadata-ready/ に metadata JSON がありません")

    # 5. PDF と metadata のペア確認
    if renamed_pdfs and metadata_jsons:
        unmatched = _unmatched_pdfs(renamed_pdfs, metadata_jsons)
        if unmatched:
            warnings.append(
                f"対応 metadata がない PDF が {len(unmatched)} 件あります: "
                + ", ".join(p.name for p in unmatched[:5])
                + (" ..." if len(unmatched) > 5 else "")
            )

    # 6. ocr-error レポートが残っているか
    ocr_count = _ocr_error_report_count()
    if ocr_count:
        warnings.append(f"ocr-error files remain: {ocr_count} (手動対応が必要です)")

    # 出力
    for msg in infos:
        print(f"[OK]      {msg}")
    for msg in warnings:
        print(f"[WARNING] {msg}")
    for msg in issues:
        print(f"[NG]      {msg}")

    export_ready = len(issues) == 0
    print()
    if export_ready:
        print("Export ready: YES")
        if warnings:
            print("  (警告あり — 内容を確認の上 export してください)")
    else:
        print("Export ready: NO")
        print("  上記 [NG] 項目を解決してから export してください")

    return export_ready


if __name__ == "__main__":
    ok = run()
    sys.exit(0 if ok else 1)
