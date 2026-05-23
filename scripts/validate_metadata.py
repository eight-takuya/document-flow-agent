"""
validate_metadata.py

processing/metadata-ready/ の .metadata.json ファイルを
docs/metadata-schema.md (v1) に照らして検証し、問題レポートを出力する。

Usage:
    python scripts/validate_metadata.py               # 全件検証
    python scripts/validate_metadata.py --fix         # 自動修正可能な問題を修正
    python scripts/validate_metadata.py --report      # JSON/MD レポートを生成
    python scripts/validate_metadata.py path/to.json  # 単一ファイル検証
"""

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# tag_utils は同ディレクトリにある
_SCRIPTS_DIR = Path(__file__).parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
from tag_utils import generate_tags, merge_tags  # noqa: E402
from summary_utils import generate_summary       # noqa: E402

REPO_ROOT = Path(__file__).parent.parent
METADATA_READY_DIR = REPO_ROOT / "processing" / "metadata-ready"
REPORTS_DIR = REPO_ROOT / "processing" / "metadata-reports"

# ---------------------------------------------------------------------------
# Schema constants
# ---------------------------------------------------------------------------

VALID_CATEGORIES = {
    "Receipt", "Utility", "Finance", "Insurance",
    "School", "Government", "Medical",
    "Work", "Contract", "Tax", "Other",
}

# 旧カテゴリ → v1 カテゴリの自動修正マップ
CATEGORY_MIGRATION_MAP = {
    "Expense": "Other",        # 非標準 category
}

VALID_STATUS = {
    "auto-approved", "renamed", "document-unknown",
    "review-required", "ocr-error", "discarded", "exported", "pending",
}

VALID_PAYMENT_METHODS = {
    "Cash", "BankTransfer", "DirectDebit", "AMEX", "SMBC",
    "RakutenCard", "PayPay", "Suica", "Other", "",
}

DOCUMENT_RECOMMENDATIONS: Dict[str, List[str]] = {
    "Receipt":    ["領収書", "領収証", "レシート", "タクシー領収書"],
    "Utility":    ["水道使用量のお知らせ", "水道料金案内", "水道料金領収証",
                   "電気料金案内", "ガス料金案内", "使用量のお知らせ"],
    "Finance":    ["クレジットカード明細", "ご利用明細", "引落通知", "振込明細", "口座明細"],
    "Insurance":  ["保険証", "保険料納入告知額通知", "共済加入証書",
                   "確定拠出年金掛金明細", "口座振替開始通知書", "保険更新通知"],
    "School":     ["講師派遣依頼書", "探究ゼミ実施要項", "職業講演会講師依頼書",
                   "Teams接続情報", "成績通知"],
    "Government": ["履歴事項全部証明書", "変更通知書", "適用事業所所在名称変更通知書",
                   "交通反則通告制度案内", "組合員証", "保険証明書"],
    "Medical":    ["診療明細書", "処方箋", "医療費領収書"],
    "Work":       ["業務完了通知書", "業務報告書"],
    "Contract":   ["御見積書", "請求書", "発注書", "納品書", "契約書"],
    "Tax":        ["課税通知書", "納税通知書", "確定申告書"],
    "Other":      [],  # 推奨値なし
}

RETENTION_YEARS = {
    "Tax": 7, "Contract": 7, "Work": 5, "Insurance": 5,
    "Medical": 5, "School": 3, "Government": 7, "Finance": 5,
    "Receipt": 3, "Utility": 3, "Other": 3,
}

DOCUMENT_PLACEHOLDER_RE = re.compile(r"^\[.*要確認.*\]$|^\[Document.*\]$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# ---------------------------------------------------------------------------
# Issue types
# ---------------------------------------------------------------------------

class Severity:
    ERROR   = "ERROR"    # 修正必須（Notion/検索に支障）
    WARNING = "WARNING"  # 推奨（品質向上）
    INFO    = "INFO"     # 参考情報

class Issue:
    def __init__(self, severity: str, field: str, message: str, fixable: bool = False, fix_value=None):
        self.severity = severity
        self.field = field
        self.message = message
        self.fixable = fixable      # --fix で自動修正可能か
        self.fix_value = fix_value  # 修正値

    def __repr__(self):
        tag = f"[{self.severity}]"
        fix = " (auto-fixable)" if self.fixable else ""
        return f"  {tag:12s} {self.field}: {self.message}{fix}"


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------

def calc_discard_date(issue_date: str, category: str) -> str:
    """issue_date + retention から discard_date を計算する。"""
    if not issue_date or not DATE_RE.match(issue_date):
        return ""
    years = RETENTION_YEARS.get(category, 3)
    try:
        y, mo, d = int(issue_date[:4]), int(issue_date[5:7]), int(issue_date[8:10])
        return f"{y + years:04d}-{mo:02d}-{d:02d}"
    except (ValueError, IndexError):
        return ""


def validate_metadata(data: dict, filepath: Path, summary_refresh: bool = False) -> Tuple[List[Issue], dict]:
    """
    metadata dict を検証し (issues, fixed_data) を返す。
    fixed_data は --fix 用の修正済みコピー（修正がない場合は元の dict をそのまま）。
    """
    issues: List[Issue] = []
    fixed = dict(data)

    # --- schema_version ---
    if not data.get("schema_version"):
        fixed["schema_version"] = "v1"
        issues.append(Issue(
            Severity.INFO, "schema_version",
            f"schema_version が未設定。\"v1\" を付与します。",
            fixable=True, fix_value="v1",
        ))

    # --- file_name ---
    if not data.get("file_name"):
        issues.append(Issue(Severity.ERROR, "file_name", "file_name が空です。"))

    # --- source_file（旧: source_file_name）---
    source = data.get("source_file") or data.get("source_file_name", "")
    if not source:
        issues.append(Issue(Severity.WARNING, "source_file", "source_file が空（元ファイル名不明）。"))
    elif "source_file_name" in data and "source_file" not in data:
        # 旧フィールド名を新フィールド名に移行
        fixed["source_file"] = source
        fixed.pop("source_file_name", None)
        issues.append(Issue(
            Severity.INFO, "source_file",
            f"source_file_name → source_file にフィールド名を移行します。",
            fixable=True,
        ))

    # --- category ---
    category = data.get("category", "")
    if not category:
        issues.append(Issue(Severity.ERROR, "category", "category が空です。"))
    elif category in CATEGORY_MIGRATION_MAP:
        new_cat = CATEGORY_MIGRATION_MAP[category]
        fixed["category"] = new_cat
        issues.append(Issue(
            Severity.WARNING, "category",
            f"非標準 category \"{category}\" → \"{new_cat}\" に移行します。",
            fixable=True, fix_value=new_cat,
        ))
        category = new_cat
    elif category not in VALID_CATEGORIES:
        # 文書名がカテゴリに誤入力されているパターン（旧バージョンの generate_metadata バグ）
        issues.append(Issue(
            Severity.ERROR, "category",
            f"無効な category \"{category}\"。VALID_CATEGORIES: {sorted(VALID_CATEGORIES)}",
            fixable=True, fix_value="Other",
        ))
        fixed["category"] = "Other"
        category = "Other"

    # --- document ---
    document = data.get("document", "")
    if DOCUMENT_PLACEHOLDER_RE.match(document):
        fixed["document"] = ""
        if fixed.get("status") not in ("document-unknown", "review-required", "ocr-error"):
            fixed["status"] = "document-unknown"
        issues.append(Issue(
            Severity.WARNING, "document",
            f"document が要確認プレースホルダー \"{document}\"。"
            f"document を空にし status=document-unknown に変更します。",
            fixable=True,
        ))
        document = ""
    elif document and category in DOCUMENT_RECOMMENDATIONS:
        recs = DOCUMENT_RECOMMENDATIONS[category]
        if recs and document not in recs:
            issues.append(Issue(
                Severity.INFO, "document",
                f"\"{document}\" は {category} の推奨値外。"
                f"推奨: {recs}",
            ))

    # document が空で status が auto-approved / renamed の場合
    if not document and data.get("status") in ("auto-approved", "renamed"):
        if fixed.get("status") not in ("document-unknown",):
            fixed["status"] = "document-unknown"
            issues.append(Issue(
                Severity.WARNING, "document",
                "document が空で status が処理済みのため、status=document-unknown に変更。",
                fixable=True,
            ))

    # --- issue_date（旧: event_date）---
    issue_date = data.get("issue_date") or data.get("event_date", "")
    if not issue_date:
        issues.append(Issue(Severity.WARNING, "issue_date", "issue_date が空（書類日付不明）。"))
    elif not DATE_RE.match(issue_date):
        issues.append(Issue(Severity.ERROR, "issue_date",
                            f"issue_date の形式が不正: \"{issue_date}\"（YYYY-MM-DD 形式を使用）。"))
    # 旧フィールド名移行
    if "event_date" in data and "issue_date" not in data:
        fixed["issue_date"] = issue_date
        fixed.pop("event_date", None)
        issues.append(Issue(
            Severity.INFO, "issue_date",
            "event_date → issue_date にフィールド名を移行します。",
            fixable=True,
        ))

    # --- discard_date ---
    discard_date = data.get("discard_date", "")
    if not discard_date:
        if issue_date and DATE_RE.match(issue_date):
            computed = calc_discard_date(issue_date, category)
            if computed:
                fixed["discard_date"] = computed
                issues.append(Issue(
                    Severity.INFO, "discard_date",
                    f"discard_date が未設定。{computed} を自動計算します（{category}: "
                    f"{RETENTION_YEARS.get(category, 3)}年保存）。",
                    fixable=True, fix_value=computed,
                ))
        else:
            issues.append(Issue(Severity.INFO, "discard_date",
                                "discard_date が未設定（issue_date 不明のため計算不可）。"))
    elif discard_date and not DATE_RE.match(discard_date):
        issues.append(Issue(Severity.ERROR, "discard_date",
                            f"discard_date の形式が不正: \"{discard_date}\"。"))

    # --- status ---
    status = data.get("status", "")
    if not status:
        fixed["status"] = "pending"
        issues.append(Issue(Severity.WARNING, "status",
                            "status が空。\"pending\" を設定します。",
                            fixable=True, fix_value="pending"))
    elif status not in VALID_STATUS:
        issues.append(Issue(Severity.ERROR, "status",
                            f"無効な status \"{status}\"。VALID_STATUS: {sorted(VALID_STATUS)}"))

    # --- payment_method ---
    pm = data.get("payment_method", "")
    if pm not in VALID_PAYMENT_METHODS:
        issues.append(Issue(Severity.WARNING, "payment_method",
                            f"無効な payment_method \"{pm}\"。"
                            f"VALID: {sorted(v for v in VALID_PAYMENT_METHODS if v)}"))

    # --- amount_jpy ---
    amount = data.get("amount_jpy")
    if amount is not None and not isinstance(amount, (int, float)):
        issues.append(Issue(Severity.ERROR, "amount_jpy",
                            f"amount_jpy は integer または null である必要があります。値: {amount!r}"))

    # --- confidence ---
    conf = data.get("confidence")
    if conf is not None:
        if not isinstance(conf, (int, float)) or not (0.0 <= conf <= 1.0):
            issues.append(Issue(Severity.ERROR, "confidence",
                                f"confidence は 0.0〜1.0 の数値または null である必要があります。値: {conf!r}"))

    # --- tags （型チェック + 自動補完）---
    tags = fixed.get("tags")
    if tags is not None and not isinstance(tags, list):
        fixed["tags"] = []
        tags = []
        issues.append(Issue(Severity.WARNING, "tags",
                            f"tags はリスト型である必要があります。値: {tags!r}",
                            fixable=True, fix_value=[]))

    # tags 自動補完: generate_tags で不足タグを追加
    current_tags: List[str] = fixed.get("tags") or []
    auto_tags = generate_tags(fixed)
    merged = merge_tags(current_tags, auto_tags)
    added = [t for t in merged if t not in set(current_tags)]
    if added:
        fixed["tags"] = merged
        issues.append(Issue(
            Severity.INFO, "tags",
            f"tags を自動補完: {added} を追加（既存: {current_tags}）",
            fixable=True, fix_value=merged,
        ))

    # --- summary（自動補完）---
    existing_summary: str = str(fixed.get("summary") or "").strip()
    if summary_refresh or not existing_summary:
        new_summary = generate_summary(fixed)
        if new_summary and new_summary != existing_summary:
            action = "再生成（--summary-refresh）" if summary_refresh and existing_summary else "自動補完"
            fixed["summary"] = new_summary
            issues.append(Issue(
                Severity.INFO, "summary",
                f"summary を{action}: 「{new_summary[:40]}{'…' if len(new_summary) > 40 else ''}」",
                fixable=True, fix_value=new_summary,
            ))

    # --- schema_version の付与（最後に確認）---
    if "schema_version" not in fixed:
        fixed["schema_version"] = "v1"

    # updated_at を更新（fix 時のみ）
    if fixed != data:
        fixed["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return issues, fixed


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def run_validation(
    target_dir: Path = METADATA_READY_DIR,
    fix: bool = False,
    single_file: Optional[Path] = None,
    summary_refresh: bool = False,
) -> dict:
    """全 metadata ファイルを検証し、結果サマリを返す。"""

    if single_file:
        files = [single_file]
    else:
        files = sorted(target_dir.glob("*.metadata.json"))

    if not files:
        print(f"metadata ファイルが見つかりません: {target_dir}")
        return {}

    results = []
    total_errors = 0
    total_warnings = 0
    total_infos = 0
    fixed_count = 0
    total_tags_added = 0
    tag_counter: Counter = Counter()
    files_without_tags = 0
    representative_new_tags: List[str] = []
    # summary 統計
    summary_added = 0
    summary_refreshed = 0
    summary_missing = 0
    summary_category_count: Counter = Counter()
    summary_examples: List[str] = []

    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"  [ERROR] JSON 解析エラー: {f.name} — {e}")
            continue

        issues, fixed_data = validate_metadata(data, f, summary_refresh=summary_refresh)

        errors   = [i for i in issues if i.severity == Severity.ERROR]
        warnings = [i for i in issues if i.severity == Severity.WARNING]
        infos    = [i for i in issues if i.severity == Severity.INFO]

        total_errors   += len(errors)
        total_warnings += len(warnings)
        total_infos    += len(infos)

        # tags 統計収集
        final_tags: List[str] = fixed_data.get("tags") or []
        original_tags: List[str] = data.get("tags") or []
        added_tags = [t for t in final_tags if t not in set(original_tags)]
        total_tags_added += len(added_tags)
        tag_counter.update(final_tags)
        if not final_tags:
            files_without_tags += 1
        for t in added_tags:
            if t not in representative_new_tags:
                representative_new_tags.append(t)

        # summary 統計
        orig_summary = str(data.get("summary") or "").strip()
        new_summary  = str(fixed_data.get("summary") or "").strip()
        cat = str(data.get("category") or "Other")
        if not new_summary:
            summary_missing += 1
        elif not orig_summary and new_summary:
            summary_added += 1
            summary_category_count[cat] += 1
            if len(summary_examples) < 5:
                summary_examples.append(new_summary)
        elif orig_summary and new_summary != orig_summary:
            summary_refreshed += 1
            summary_category_count[cat] += 1
            if len(summary_examples) < 5:
                summary_examples.append(new_summary)
        else:
            summary_category_count[cat] += 1

        result_entry = {
            "file": f.name,
            "errors": len(errors),
            "warnings": len(warnings),
            "infos": len(infos),
            "issues": [
                {"severity": i.severity, "field": i.field, "message": i.message, "fixable": i.fixable}
                for i in issues
            ],
            "fixed": False,
            "tags_added": added_tags,
            "summary_added": not orig_summary and bool(new_summary),
            "summary_refreshed": bool(orig_summary and new_summary != orig_summary),
        }

        if issues:
            status_icon = "❌" if errors else ("⚠️ " if warnings else "ℹ️ ")
            print(f"{status_icon} {f.name}")
            for issue in issues:
                print(repr(issue))

            if fix and fixed_data != data:
                f.write_text(json.dumps(fixed_data, ensure_ascii=False, indent=2), encoding="utf-8")
                fixed_count += 1
                result_entry["fixed"] = True
                print(f"     → ✅ 自動修正しました")
        else:
            print(f"  ✅ {f.name}")

        results.append(result_entry)
        if issues:
            print()

    result_summary = {
        "total_files": len(files),
        "files_with_errors": sum(1 for r in results if r["errors"] > 0),
        "files_with_warnings": sum(1 for r in results if r["warnings"] > 0),
        "total_errors": total_errors,
        "total_warnings": total_warnings,
        "total_infos": total_infos,
        "fixed_count": fixed_count,
        "results": results,
        # tags 統計
        "tags_added_total": total_tags_added,
        "tag_frequency": dict(tag_counter.most_common(20)),
        "files_without_tags": files_without_tags,
        "representative_new_tags": representative_new_tags[:20],
        # summary 統計
        "summary_added": summary_added,
        "summary_refreshed": summary_refreshed,
        "summary_missing": summary_missing,
        "summary_category_count": dict(summary_category_count.most_common()),
        "summary_examples": summary_examples,
    }

    return result_summary


def write_report(summary: dict, timestamp: str) -> None:
    """JSON + Markdown レポートを processing/metadata-reports/ に出力する。"""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    # JSON
    json_path = REPORTS_DIR / f"metadata-validation-{timestamp}.json"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    # Markdown
    md_path = REPORTS_DIR / f"metadata-validation-{timestamp}.md"
    lines = [
        f"# metadata validation report — {timestamp}",
        "",
        f"| 項目 | 数 |",
        f"|---|---|",
        f"| 検証ファイル数 | {summary['total_files']} |",
        f"| ERROR あり | {summary['files_with_errors']} |",
        f"| WARNING あり | {summary['files_with_warnings']} |",
        f"| 自動修正済み | {summary['fixed_count']} |",
        f"| ERROR 総数 | {summary['total_errors']} |",
        f"| WARNING 総数 | {summary['total_warnings']} |",
        "",
    ]

    # tags 統計セクション
    lines += [
        "## Tags 自動生成サマリー",
        "",
        f"| 項目 | 数 |",
        f"|---|---|",
        f"| tags 追加件数（合計） | {summary.get('tags_added_total', 0)} |",
        f"| tags なし metadata 件数 | {summary.get('files_without_tags', 0)} |",
        "",
        "### tag 別件数 TOP20",
        "",
    ]
    tag_freq = summary.get("tag_frequency", {})
    if tag_freq:
        lines.append("| tag | 件数 |")
        lines.append("|---|---|")
        for tag, count in tag_freq.items():
            lines.append(f"| {tag} | {count} |")
    else:
        lines.append("*(タグなし)*")
    lines.append("")

    new_tags = summary.get("representative_new_tags", [])
    if new_tags:
        lines += [
            "### 新規追加された代表タグ",
            "",
            ", ".join(f"`{t}`" for t in new_tags),
            "",
        ]

    # summary 統計セクション
    lines += [
        "## Summary 自動生成サマリー",
        "",
        f"| 項目 | 数 |",
        f"|---|---|",
        f"| summary 新規追加件数 | {summary.get('summary_added', 0)} |",
        f"| summary 再生成件数（--summary-refresh） | {summary.get('summary_refreshed', 0)} |",
        f"| summary 未生成件数 | {summary.get('summary_missing', 0)} |",
        "",
    ]
    cat_count = summary.get("summary_category_count", {})
    if cat_count:
        lines += [
            "### category 別 summary 生成件数",
            "",
            "| category | 件数 |",
            "|---|---|",
        ]
        for cat, cnt in cat_count.items():
            lines.append(f"| {cat} | {cnt} |")
        lines.append("")
    examples = summary.get("summary_examples", [])
    if examples:
        lines += [
            "### 代表 summary 例",
            "",
        ]
        for ex in examples:
            lines.append(f"- {ex}")
        lines.append("")

    lines += [
        "## 問題ファイル一覧",
        "",
    ]

    for r in summary["results"]:
        if not r["issues"]:
            continue
        icon = "❌" if r["errors"] > 0 else "⚠️"
        lines.append(f"### {icon} {r['file']}")
        lines.append("")
        for issue in r["issues"]:
            tag = f"[{issue['severity']}]"
            fix_note = " *(auto-fixable)*" if issue["fixable"] else ""
            lines.append(f"- `{tag}` **{issue['field']}**: {issue['message']}{fix_note}")
        if r.get("tags_added"):
            lines.append(f"- tags 追加: {r['tags_added']}")
        if r["fixed"]:
            lines.append("")
            lines.append("→ ✅ 自動修正済み")
        lines.append("")

    md_path.write_text("\n".join(lines), encoding="utf-8")

    print()
    print(f"レポート保存:")
    print(f"  [JSON] {json_path.relative_to(REPO_ROOT)}")
    print(f"  [MD]   {md_path.relative_to(REPO_ROOT)}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="metadata-ready/ の .metadata.json を schema v1 で検証する",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python scripts/validate_metadata.py                           # 全件検証（変更なし）
  python scripts/validate_metadata.py --fix                     # 自動修正可能な問題を修正
  python scripts/validate_metadata.py --fix --summary-refresh   # summary も再生成
  python scripts/validate_metadata.py --report                  # JSON/MD レポートを出力
  python scripts/validate_metadata.py --fix --report            # 修正 + レポート
  python scripts/validate_metadata.py path/to.json              # 単一ファイル検証
        """,
    )
    parser.add_argument("file", nargs="?", help="単一ファイルを検証")
    parser.add_argument("--fix", action="store_true", help="自動修正可能な問題を修正する")
    parser.add_argument("--summary-refresh", action="store_true",
                        help="既存 summary があっても再生成して上書きする（--fix と併用）")
    parser.add_argument("--report", action="store_true", help="JSON/MD レポートを出力する")
    parser.add_argument("--dir", type=Path, default=METADATA_READY_DIR,
                        help=f"検証対象ディレクトリ（デフォルト: {METADATA_READY_DIR}）")
    args = parser.parse_args()

    single_file = Path(args.file) if args.file else None
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    summary_refresh = getattr(args, "summary_refresh", False)

    fix_label = "fix=ON" if args.fix else "dry-run"
    if summary_refresh:
        fix_label += " + summary-refresh"
    print(f"=== validate_metadata.py  {fix_label}  {timestamp} ===")
    print()

    summary = run_validation(
        target_dir=args.dir,
        fix=args.fix,
        single_file=single_file,
        summary_refresh=summary_refresh,
    )

    if not summary:
        sys.exit(1)

    # サマリー表示
    print()
    print("=" * 60)
    print("[SUMMARY]")
    print("=" * 60)
    print(f"  検証ファイル数   : {summary['total_files']}")
    print(f"  ERROR あり       : {summary['files_with_errors']}")
    print(f"  WARNING あり     : {summary['files_with_warnings']}")
    print(f"  INFO             : {summary['total_infos']}")
    print(f"  自動修正済み     : {summary['fixed_count']}")
    print(f"  tags 追加件数    : {summary.get('tags_added_total', 0)}")
    print(f"  tags なし件数    : {summary.get('files_without_tags', 0)}")
    tag_freq = summary.get("tag_frequency", {})
    if tag_freq:
        top5 = list(tag_freq.items())[:5]
        print(f"  tag TOP5         : {', '.join(f'{t}({c})' for t, c in top5)}")
    new_tags = summary.get("representative_new_tags", [])
    if new_tags:
        print(f"  新規追加タグ例   : {', '.join(new_tags[:8])}")
    print(f"  summary 追加件数 : {summary.get('summary_added', 0)}")
    print(f"  summary 再生成   : {summary.get('summary_refreshed', 0)}")
    print(f"  summary 未生成   : {summary.get('summary_missing', 0)}")
    examples = summary.get("summary_examples", [])
    if examples:
        print(f"  summary 例       : {examples[0][:60]}{'…' if len(examples[0]) > 60 else ''}")
    print()

    if summary["total_errors"] == 0 and summary["total_warnings"] == 0:
        print("  ✅ 全ファイル問題なし")
    elif summary["total_errors"] == 0:
        print("  ⚠️  WARNING のみ（ERRORなし）")
    else:
        print(f"  ❌ ERROR {summary['total_errors']} 件あり — 要対応")

    if args.report:
        write_report(summary, timestamp)

    sys.exit(0 if summary["total_errors"] == 0 else 1)


if __name__ == "__main__":
    main()
