"""
process_inbox.py

inbox をスキャンし、OCR + ヒューリスティック分析で rename 候補を生成する。
レビュー対象は JSON / Markdown / HTML の3形式でレポートを出力する。

デフォルト: --dry-run（ファイル変更なし）
--apply  : review 不要ファイルを renamed/ へ safe copy + metadata 生成
--no-ocr : OCR をスキップしてファイル名分析のみ

Usage:
    python scripts/process_inbox.py              # dry-run + OCR
    python scripts/process_inbox.py --dry-run    # 同上
    python scripts/process_inbox.py --no-ocr     # dry-run, OCR なし
    python scripts/process_inbox.py --apply      # safe copy + metadata
"""

import argparse
import html as html_module
import json
import re
import shutil
import socket
import subprocess
import sys
import time
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

REPO_ROOT = Path(__file__).parent.parent
INBOX_DIR = REPO_ROOT / "inbox"
PROCESSING_DIR = REPO_ROOT / "processing"
RENAMED_DIR = PROCESSING_DIR / "renamed"
METADATA_READY_DIR = PROCESSING_DIR / "metadata-ready"
REVIEW_DIR = PROCESSING_DIR / "review-required"
OCR_ERROR_DIR = PROCESSING_DIR / "ocr-error"
LOGS_DIR = REPO_ROOT / "logs"

sys.path.insert(0, str(Path(__file__).parent))
from normalize_documents import (
    scan_inbox,
    detect_garbled,
    extract_date,
    extract_bracket_tags,
    classify_file,
)
from generate_metadata import generate_metadata, save_metadata
from ocr_extract import (
    extract_text,
    parse_rename_fields,
    build_ocr_rename_candidate,
    ensure_ocr_binary,
)

MAX_STEM_LENGTH = 80
DATE_PREFIX_PATTERN = re.compile(r"^\d{8}[_\-\s]?")
BRACKET_TAG_PATTERN = re.compile(r"【[^】]+】")
UNSAFE_CHARS_PATTERN = re.compile(r'[/\\:*?"<>|\s]')


# ---------------------------------------------------------------------------
# File analysis
# ---------------------------------------------------------------------------

def is_date_only(name: str) -> bool:
    return bool(re.match(r"^\d{8}$", Path(name).stem))


def is_too_long(name: str) -> bool:
    return len(Path(name).stem) > MAX_STEM_LENGTH


def _extract_document_portion(name: str) -> str:
    stem = Path(name).stem
    stem = BRACKET_TAG_PATTERN.sub("", stem)
    stem = DATE_PREFIX_PATTERN.sub("", stem)
    stem = UNSAFE_CHARS_PATTERN.sub("-", stem)
    stem = re.sub(r"-{2,}", "-", stem).strip("-")
    return stem


def _build_best_effort_name(name: str) -> str:
    """ファイル名ベースのベストエフォート rename 候補（Category なし）。"""
    date = extract_date(name)
    if not date:
        return name
    tags = extract_bracket_tags(name)
    doc = _extract_document_portion(name)
    parts = [date]
    if doc:
        parts.append(doc)
    if tags:
        parts.append(tags[0])
    return "-".join(parts) + ".pdf"


def analyze_file(path: Path, use_ocr: bool) -> Dict:
    """ファイルを分析してフラグ・OCR結果・rename 候補を返す。"""
    name = path.name
    kind = classify_file(path)
    date = extract_date(name)
    tags = extract_bracket_tags(name)
    garbled = detect_garbled(name)
    date_only = is_date_only(name)
    too_long = is_too_long(name)

    warnings: List[str] = []
    if garbled:
        warnings.append("OCR 文字化けの可能性あり")
    if date_only:
        warnings.append("ファイル名が日付のみ — 内容不明")
    if too_long:
        warnings.append(f"ファイル名が長すぎる ({len(Path(name).stem)} 文字)")
    if not date:
        warnings.append("日付が読み取れない")
    if kind == "IMAGE":
        warnings.append("画像ファイル — PDF 化が必要")

    needs_ocr_review = garbled
    needs_review = bool(warnings)

    # --- OCR ---
    ocr_text = ""
    ocr_fields: Dict = {}
    ocr_rename_candidate = ""

    if use_ocr and kind in ("PDF", "IMAGE"):
        ocr_text = extract_text(path)
        if ocr_text:
            ocr_fields = parse_rename_fields(ocr_text, name, tags)
            ocr_rename_candidate = build_ocr_rename_candidate(ocr_fields)

    # --- filename-based rename hint ---
    if date:
        tag_suffix = f"-{tags[0]}" if tags else ""
        rename_hint = f"{date}-[Category]-[Document]{tag_suffix}.pdf"
        best_effort_name = _build_best_effort_name(name) if not needs_review else None
    else:
        rename_hint = "(日付不明: 要確認)"
        best_effort_name = None

    # OCR が成功したなら、OCR 候補をメインの rename 候補として使う
    display_rename = ocr_rename_candidate if ocr_rename_candidate else (best_effort_name or rename_hint)

    return {
        "path": path,
        "name": name,
        "kind": kind,
        "date": date,
        "tags": tags,
        "garbled": garbled,
        "date_only": date_only,
        "too_long": too_long,
        "needs_review": needs_review,
        "needs_ocr_review": needs_ocr_review,
        "rename_hint": rename_hint,
        "best_effort_name": best_effort_name,
        "display_rename": display_rename,
        "ocr_text": ocr_text,
        "ocr_fields": ocr_fields,
        "ocr_rename_candidate": ocr_rename_candidate,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Safe copy
# ---------------------------------------------------------------------------

def _resolve_dest(dest_dir: Path, filename: str) -> Path:
    """同名ファイルがある場合は -001, -002 ... の連番を付与して返す。"""
    candidate = dest_dir / filename
    if not candidate.exists():
        return candidate
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    for i in range(1, 1000):
        candidate = dest_dir / f"{stem}-{i:03d}{suffix}"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"No free filename for {filename}")


def copy_to_renamed(src: Path, dest_name: str) -> Path:
    RENAMED_DIR.mkdir(parents=True, exist_ok=True)
    dest = _resolve_dest(RENAMED_DIR, dest_name)
    shutil.copy2(src, dest)
    return dest


# ---------------------------------------------------------------------------
# Report: JSON
# ---------------------------------------------------------------------------

def _write_json_report(items: List[Dict], path: Path) -> None:
    report = {
        "generated_at": datetime.now().isoformat(),
        "count": len(items),
        "files": [
            {
                "name": item["name"],
                "warnings": item["warnings"],
                "rename_hint": item["rename_hint"],
                "ocr_rename_candidate": item.get("ocr_rename_candidate", ""),
                "ocr_fields": item.get("ocr_fields", {}),
            }
            for item in items
        ],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Report: Markdown
# ---------------------------------------------------------------------------

def _write_markdown_report(items: List[Dict], path: Path, report_type: str) -> None:
    lines = [
        f"# {report_type} レポート",
        f"",
        f"生成日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ",
        f"件数: {len(items)}",
        f"",
        f"> このファイルは人間確認用です。JSON は機械処理用として別途生成されています。",
        f"",
        f"---",
        f"",
        f"| 元ファイル | OCR 推定内容 | rename 候補 | 警告 | 人間確認 |",
        f"|---|---|---|---|---|",
    ]

    for item in items:
        name = item["name"]
        fields = item.get("ocr_fields", {})
        ocr_summary = ""
        if fields:
            parts = []
            if fields.get("document"):
                parts.append(fields["document"])
            if fields.get("counterparty"):
                parts.append(fields["counterparty"])
            if fields.get("amount_jpy"):
                parts.append(f"{fields['amount_jpy']}円")
            ocr_summary = " / ".join(parts) if parts else "（テキスト抽出済み）"
        elif item.get("ocr_text"):
            ocr_summary = item["ocr_text"][:30].replace("\n", " ") + "..."
        else:
            ocr_summary = "（OCR なし / 対象外）"

        rename = item.get("ocr_rename_candidate") or item.get("rename_hint", "")
        warnings = "、".join(item["warnings"]) if item["warnings"] else "—"

        lines.append(
            f"| `{name}` | {ocr_summary} | `{rename}` | {warnings} | □ OK / □ 修正 |"
        )

    lines += [
        "",
        "---",
        "",
        "## 詳細",
        "",
    ]

    for item in items:
        lines += [
            f"### {item['name']}",
            "",
        ]
        if item["warnings"]:
            lines.append("**警告:**")
            for w in item["warnings"]:
                lines.append(f"- ⚠ {w}")
            lines.append("")

        rename = item.get("ocr_rename_candidate") or item.get("rename_hint", "")
        lines += [
            f"**rename 候補:** `{rename}`",
            "",
        ]

        fields = item.get("ocr_fields", {})
        if fields:
            lines += [
                "**OCR 推定フィールド:**",
                "",
                f"| フィールド | 推定値 |",
                f"|---|---|",
                f"| date | {fields.get('date', '')} |",
                f"| category | {fields.get('category', '')} |",
                f"| document | {fields.get('document', '')} |",
                f"| counterparty | {fields.get('counterparty', '')} |",
                f"| amount_jpy | {fields.get('amount_jpy', '')} |",
                "",
            ]

        ocr_text = item.get("ocr_text", "")
        if ocr_text:
            snippet = ocr_text[:400].replace("\n", "  \n")
            lines += [
                "<details>",
                "<summary>OCR テキスト（クリックで展開）</summary>",
                "",
                f"```",
                snippet,
                f"```",
                "",
                "</details>",
                "",
            ]

        lines += [
            "**人間確認メモ:**",
            "",
            "```",
            "判定: [ ] OK  [ ] 修正  [ ] 廃棄",
            "修正後ファイル名:",
            "備考:",
            "```",
            "",
            "---",
            "",
        ]

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ---------------------------------------------------------------------------
# Report: HTML
# ---------------------------------------------------------------------------

def _write_html_report(items: List[Dict], path: Path, report_type: str) -> None:
    esc = html_module.escape

    cards = []
    for item in items:
        name = esc(item["name"])
        rename = esc(item.get("ocr_rename_candidate") or item.get("rename_hint", ""))
        warnings_html = "".join(
            f'<li class="warn">⚠ {esc(w)}</li>' for w in item["warnings"]
        ) if item["warnings"] else "<li>—</li>"

        fields = item.get("ocr_fields", {}) or {}
        ocr_ran = bool(fields or item.get("ocr_text"))

        # Standard field definitions: (key, Japanese label)
        FIELD_DEFS = [
            ("date",           "日付"),
            ("category",       "カテゴリ"),
            ("document",       "書類名"),
            ("counterparty",   "取引先"),
            ("amount_jpy",     "金額（円）"),
            ("payment_method", "支払手段"),
        ]
        if ocr_ran:
            fields_rows = "".join(
                f"<tr><td>{label}</td><td>{esc(str(fields.get(key) or '—'))}</td></tr>"
                for key, label in FIELD_DEFS
            )
            ocr_section_label = "OCR 推定フィールド"
        else:
            fields_rows = "<tr><td colspan='2' style='color:#aaa;font-style:italic;'>OCR 未実行（--no-ocr オプション使用 または テキスト抽出不可）</td></tr>"
            ocr_section_label = "OCR 推定フィールド（未実行）"

        # JSON-encode fields for data attribute (ensure_ascii=True → safe for HTML attribute)
        fields_json_esc = esc(json.dumps(fields, ensure_ascii=True))

        ocr_text = esc(item.get("ocr_text", "")) or "（OCR テキストなし）"
        ocr_snippet = ocr_text[:600]

        status_cls = "ocr-error" if item.get("needs_ocr_review") else "review"
        card_id = f"card-{len(cards)}"

        cards.append(f"""
  <div class="card {status_cls}" id="{card_id}"
       data-source-name="{name}"
       data-rename-candidate="{rename}"
       data-ocr-fields="{fields_json_esc}">
    <div class="card-header">
      <span class="badge {'badge-ocr' if item.get('needs_ocr_review') else 'badge-review'}">
        {'OCR ERROR' if item.get('needs_ocr_review') else 'REVIEW'}
      </span>
      <span class="filename">{name}</span>
    </div>

    <div class="section">
      <div class="label">rename 候補</div>
      <div class="rename-candidate">{rename}</div>
    </div>

    <div class="section">
      <div class="label">警告</div>
      <ul class="warn-list">{warnings_html}</ul>
    </div>

    <div class="section">
      <div class="label">{ocr_section_label}</div>
      <table class="fields">
        <tr><th>フィールド</th><th>推定値</th></tr>
        {fields_rows}
      </table>
    </div>

    <details class="ocr-details">
      <summary>OCR テキスト（クリックで展開）</summary>
      <pre class="ocr-text">{ocr_snippet}</pre>
    </details>

    <div class="section">
      <div class="label">判断</div>
      <div class="memo-area">
        <div class="radio-group">
          <label class="radio-label">
            <input type="radio" name="decision-{card_id}" value="rename-ok" onchange="onDecisionChange('{card_id}')"> OK — OCR 候補のまま rename する
          </label>
          <label class="radio-label">
            <input type="radio" name="decision-{card_id}" value="rename-custom" onchange="onDecisionChange('{card_id}')"> 修正 — ファイル名を変更して rename する
          </label>
          <label class="radio-label">
            <input type="radio" name="decision-{card_id}" value="discard" onchange="onDecisionChange('{card_id}')"> 廃棄 — このファイルは保管不要
          </label>
        </div>
        <div class="memo-input" id="custom-{card_id}" style="display:none;">
          <label style="font-size:12px;">修正後ファイル名:</label>
          <input type="text" id="approved-{card_id}" placeholder="{rename}" value="{rename}" style="width:100%">
        </div>
        <div class="memo-input" style="margin-top:6px;">
          <label style="font-size:12px;">備考:</label>
          <input type="text" id="notes-{card_id}" placeholder="メモを入力" style="width:100%">
        </div>
      </div>
    </div>
  </div>
""")

    summary_row = "".join(
        f"<tr><td><code>{esc(item['name'])}</code></td>"
        f"<td><code>{esc(item.get('ocr_rename_candidate') or item.get('rename_hint', ''))}</code></td>"
        f"<td>{'、'.join(esc(w) for w in item['warnings']) or '—'}</td></tr>"
        for item in items
    )

    html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(report_type)} — {datetime.now().strftime('%Y-%m-%d %H:%M')}</title>
<style>
  body {{ font-family: -apple-system, 'Hiragino Sans', sans-serif; margin: 0; background: #f5f5f7; color: #1d1d1f; font-size: 14px; }}
  h1 {{ background: #1d1d1f; color: #fff; margin: 0; padding: 16px 24px; font-size: 18px; font-weight: 600; }}
  .meta {{ background: #fff; padding: 12px 24px; border-bottom: 1px solid #e0e0e0; color: #555; font-size: 12px; }}
  .summary-table {{ margin: 20px 24px; background: #fff; border-radius: 8px; box-shadow: 0 1px 4px rgba(0,0,0,.08); overflow: hidden; }}
  .summary-table h2 {{ margin: 0; padding: 12px 16px; font-size: 14px; background: #f0f0f0; border-bottom: 1px solid #ddd; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th {{ background: #f7f7f7; padding: 8px 12px; text-align: left; border-bottom: 1px solid #ddd; }}
  td {{ padding: 8px 12px; border-bottom: 1px solid #f0f0f0; }}
  tr:last-child td {{ border-bottom: none; }}
  .cards {{ padding: 0 24px 24px; }}
  .card {{ background: #fff; border-radius: 10px; box-shadow: 0 1px 4px rgba(0,0,0,.10); margin-bottom: 20px; overflow: hidden; }}
  .card-header {{ padding: 12px 16px; background: #f7f7f7; border-bottom: 1px solid #e8e8e8; display: flex; align-items: center; gap: 10px; }}
  .filename {{ font-weight: 600; font-size: 13px; word-break: break-all; }}
  .badge {{ padding: 3px 8px; border-radius: 4px; font-size: 11px; font-weight: 700; }}
  .badge-review {{ background: #fff3cd; color: #856404; }}
  .badge-ocr {{ background: #f8d7da; color: #842029; }}
  .section {{ padding: 10px 16px; border-bottom: 1px solid #f5f5f5; }}
  .section:last-child {{ border-bottom: none; }}
  .label {{ font-size: 11px; color: #888; text-transform: uppercase; letter-spacing: .5px; margin-bottom: 4px; }}
  .rename-candidate {{ font-family: monospace; font-size: 13px; background: #f0f7ff; padding: 6px 10px; border-radius: 4px; border-left: 3px solid #0071e3; word-break: break-all; }}
  .warn-list {{ margin: 0; padding-left: 18px; }}
  .warn {{ color: #c0392b; }}
  .fields {{ width: 100%; font-size: 12px; border-collapse: collapse; }}
  .fields th, .fields td {{ padding: 4px 8px; text-align: left; border: 1px solid #eee; }}
  .fields th {{ background: #f7f7f7; }}
  .ocr-details {{ padding: 10px 16px; border-top: 1px solid #f5f5f5; }}
  .ocr-details summary {{ cursor: pointer; color: #0071e3; font-size: 12px; }}
  .ocr-text {{ font-size: 12px; background: #f9f9f9; padding: 10px; border-radius: 4px; white-space: pre-wrap; word-break: break-all; max-height: 200px; overflow-y: auto; margin-top: 8px; }}
  .memo-area {{ background: #fafff4; border: 1px solid #d4edda; border-radius: 6px; padding: 10px 14px; }}
  .radio-group {{ display: flex; flex-direction: column; gap: 6px; margin-bottom: 8px; }}
  .radio-label {{ display: flex; align-items: center; gap: 8px; cursor: pointer; font-size: 13px; }}
  .radio-label input[type=radio] {{ margin: 0; cursor: pointer; }}
  .memo-input {{ display: flex; flex-direction: column; gap: 4px; font-size: 12px; }}
  input[type=text] {{ border: 1px solid #ccc; border-radius: 4px; padding: 4px 8px; font-size: 12px; }}
  code {{ background: #f0f0f0; padding: 1px 4px; border-radius: 3px; font-size: 12px; }}
  .action-panel {{ position: sticky; bottom: 0; background: #fff; border-top: 2px solid #0071e3; padding: 16px 24px; display: flex; gap: 12px; align-items: flex-start; box-shadow: 0 -2px 8px rgba(0,0,0,.10); }}
  .action-left {{ flex: 1; display: flex; flex-direction: column; gap: 8px; }}
  .action-panel textarea {{ width: 100%; height: 100px; font-family: monospace; font-size: 12px; border: 1px solid #ccc; border-radius: 6px; padding: 8px; resize: vertical; box-sizing: border-box; }}
  .save-status {{ font-size: 13px; padding: 6px 10px; border-radius: 4px; min-height: 30px; display: flex; align-items: center; }}
  .save-status.ok {{ background: #d4edda; color: #155724; }}
  .save-status.error {{ background: #f8d7da; color: #721c24; }}
  .save-status.saving {{ background: #fff3cd; color: #856404; }}
  .btn {{ padding: 8px 18px; border: none; border-radius: 6px; cursor: pointer; font-size: 13px; font-weight: 600; white-space: nowrap; }}
  .btn-primary {{ background: #0071e3; color: #fff; }}
  .btn-primary:hover {{ background: #005bb5; }}
  .btn-secondary {{ background: #e0e0e0; color: #333; }}
  .btn-secondary:hover {{ background: #c8c8c8; }}
  .btn-col {{ display: flex; flex-direction: column; gap: 8px; }}
</style>
</head>
<body>
<h1>📋 {esc(report_type)}</h1>
<div class="meta">
  生成日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} &nbsp;|&nbsp;
  件数: {len(items)} &nbsp;|&nbsp;
  ⚠ rename 候補はあくまで OCR 推定です。必ず内容を確認してください。
</div>

<div class="summary-table">
  <h2>サマリー</h2>
  <table>
    <tr><th>元ファイル</th><th>rename 候補</th><th>警告</th></tr>
    {summary_row}
  </table>
</div>

<div class="cards">
{"".join(cards)}
</div>

<div class="action-panel">
  <div class="action-left">
    <div class="save-status" id="save-status"></div>
    <textarea id="json-output" readonly placeholder="「コピー」ボタン押下時、または保存サーバー未起動時のフォールバック用JSONがここに表示されます。&#10;python scripts/review_server.py を起動すると「保存」ボタンで直接ファイルに書き込めます。"></textarea>
  </div>
  <div class="btn-col">
    <button class="btn btn-primary" onclick="saveReview(event)">保存</button>
    <button class="btn btn-secondary" onclick="copyJSON(event)">コピー</button>
  </div>
</div>

<script>
  window.onbeforeprint = () => document.querySelectorAll('details').forEach(d => d.open = true);
  window.onafterprint = () => document.querySelectorAll('details').forEach(d => d.open = false);

  function onDecisionChange(cardId) {{
    var radios = document.querySelectorAll('input[name="decision-' + cardId + '"]');
    var selected = '';
    radios.forEach(function(r) {{ if (r.checked) selected = r.value; }});
    var customDiv = document.getElementById('custom-' + cardId);
    customDiv.style.display = (selected === 'rename-custom') ? 'flex' : 'none';
  }}

  function buildPayload() {{
    var now = new Date();
    var pad = function(n) {{ return n.toString().padStart(2, '0'); }};
    var reviewedAt = now.getFullYear() + '-' + pad(now.getMonth()+1) + '-' + pad(now.getDate()) +
      'T' + pad(now.getHours()) + ':' + pad(now.getMinutes()) + ':' + pad(now.getSeconds());

    var cards = document.querySelectorAll('.card[data-source-name]');
    var items = [];
    cards.forEach(function(card) {{
      var cardId = card.id;
      var sourceName = card.dataset.sourceName;
      var renameCandidateAttr = card.dataset.renameCandidate || '';

      var radios = document.querySelectorAll('input[name="decision-' + cardId + '"]');
      var selected = '';
      radios.forEach(function(r) {{ if (r.checked) selected = r.value; }});

      var decision, approvedFileName;
      if (selected === 'rename-ok') {{
        decision = 'rename';
        approvedFileName = renameCandidateAttr;
      }} else if (selected === 'rename-custom') {{
        decision = 'rename';
        var inp = document.getElementById('approved-' + cardId);
        approvedFileName = inp ? inp.value.trim() : renameCandidateAttr;
      }} else if (selected === 'discard') {{
        decision = 'discard';
        approvedFileName = '';
      }} else {{
        decision = 'skip';
        approvedFileName = '';
      }}

      var notesInp = document.getElementById('notes-' + cardId);
      var notes = notesInp ? notesInp.value.trim() : '';

      var ocrFields = {{}};
      try {{ ocrFields = JSON.parse(card.dataset.ocrFields || '{{}}'); }} catch(e) {{}}

      items.push({{
        source_file_name: sourceName,
        decision: decision,
        approved_file_name: approvedFileName,
        ocr_fields: ocrFields,
        notes: notes
      }});
    }});

    return {{ reviewed_at: reviewedAt, items: items }};
  }}

  function saveReview(evt) {{
    var payload = buildPayload();
    var statusEl = document.getElementById('save-status');
    statusEl.textContent = '保存中...';
    statusEl.className = 'save-status saving';

    fetch('/save-review', {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify(payload)
    }}).then(function(res) {{ return res.json(); }})
    .then(function(data) {{
      if (data.ok) {{
        statusEl.textContent = '保存しました → ' + data.path;
        statusEl.className = 'save-status ok';
        document.getElementById('json-output').value = JSON.stringify(payload, null, 2);
      }} else {{
        throw new Error(data.error || '不明なエラー');
      }}
    }}).catch(function(err) {{
      statusEl.textContent = '保存失敗: ' + err.message + ' — サーバー未起動の場合は「コピー」を使用してください';
      statusEl.className = 'save-status error';
      document.getElementById('json-output').value = JSON.stringify(payload, null, 2);
    }});
  }}

  function copyJSON(evt) {{
    var payload = buildPayload();
    var json = JSON.stringify(payload, null, 2);
    document.getElementById('json-output').value = json;
    try {{
      navigator.clipboard.writeText(json).catch(function() {{
        var ta = document.getElementById('json-output');
        ta.select();
        document.execCommand('copy');
      }});
    }} catch(e) {{
      var ta = document.getElementById('json-output');
      ta.select();
      document.execCommand('copy');
    }}
    var btn = evt.target;
    var orig = btn.textContent;
    btn.textContent = 'コピーしました';
    setTimeout(function() {{ btn.textContent = orig; }}, 1500);
  }}
</script>
</body>
</html>"""

    with open(path, "w", encoding="utf-8") as f:
        f.write(html)


# ---------------------------------------------------------------------------
# Report writers (orchestrator)
# ---------------------------------------------------------------------------

def write_review_reports(items: List[Dict], timestamp: str) -> Dict[str, Path]:
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    base = f"review-report-{timestamp}"
    paths = {}

    json_path = REVIEW_DIR / f"{base}.json"
    _write_json_report(items, json_path)
    paths["json"] = json_path

    md_path = REVIEW_DIR / f"{base}.md"
    _write_markdown_report(items, md_path, "REVIEW REQUIRED")
    paths["md"] = md_path

    html_path = REVIEW_DIR / f"{base}.html"
    _write_html_report(items, html_path, "REVIEW REQUIRED")
    paths["html"] = html_path

    return paths


def write_ocr_error_reports(items: List[Dict], timestamp: str) -> Dict[str, Path]:
    OCR_ERROR_DIR.mkdir(parents=True, exist_ok=True)
    base = f"ocr-error-report-{timestamp}"
    paths = {}

    json_path = OCR_ERROR_DIR / f"{base}.json"
    _write_json_report(items, json_path)
    paths["json"] = json_path

    md_path = OCR_ERROR_DIR / f"{base}.md"
    _write_markdown_report(items, md_path, "OCR ERROR")
    paths["md"] = md_path

    html_path = OCR_ERROR_DIR / f"{base}.html"
    _write_html_report(items, html_path, "OCR ERROR")
    paths["html"] = html_path

    return paths


# ---------------------------------------------------------------------------
# Log writer
# ---------------------------------------------------------------------------

def _write_log(
    mode: str, timestamp: str, total: int, normal_count: int,
    copied: int, review_count: int, ocr_count: int,
    metadata_count: int, use_ocr: bool, details: List[Dict],
) -> Path:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOGS_DIR / f"process-inbox-{timestamp}.log"
    lines = [
        "=== process_inbox.py log ===",
        f"timestamp   : {datetime.now().isoformat()}",
        f"mode        : {mode}",
        f"ocr         : {'enabled' if use_ocr else 'disabled (--no-ocr)'}",
        "",
        "[counts]",
        f"  total files     : {total}",
        f"  rename 候補     : {normal_count}",
        f"  copy 実行数     : {copied}",
        f"  review-required : {review_count}",
        f"  ocr-error       : {ocr_count}",
        f"  metadata 生成数 : {metadata_count}",
        "",
        "[detail]",
    ]
    for d in details:
        status = d.get("status", "-")
        src = d.get("src", "")
        dest = d.get("dest", "")
        warn = ", ".join(d.get("warnings", []))
        ocr_ok = "OCR:OK" if d.get("ocr_ok") else ("OCR:FAIL" if d.get("ocr_fail") else "")
        suffix = f"  [{ocr_ok}]" if ocr_ok else ""
        if dest:
            lines.append(f"  [{status}] {src} → {dest}{suffix}")
        elif warn:
            lines.append(f"  [{status}] {src}  ⚠ {warn}{suffix}")
        else:
            lines.append(f"  [{status}] {src}{suffix}")

    with open(log_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return log_path


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def _sep(char: str = "=", width: int = 60) -> None:
    print(char * width)


# ---------------------------------------------------------------------------
# Review server launcher
# ---------------------------------------------------------------------------

REVIEW_SERVER_PORT = 8765
REVIEW_SERVER_SCRIPT = Path(__file__).parent / "review_server.py"


def _port_in_use(port: int) -> bool:
    """指定ポートが既に使用中かを確認する。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("localhost", port)) == 0


def _launch_review_server(review_count: int) -> None:
    """
    review-required がある場合にレビューサーバーを起動してブラウザを開く。

    ポートが既に使用中の場合は既存サーバーが動いていると判断し、
    ブラウザだけ開く。webbrowser.open() が失敗しても処理は止まらない。
    """
    url = f"http://localhost:{REVIEW_SERVER_PORT}"

    print()
    print(f"  Review required: {review_count} file(s)")

    if _port_in_use(REVIEW_SERVER_PORT):
        print(f"  既存のレビューサーバーを検出しました（ポート {REVIEW_SERVER_PORT}）")
    else:
        print("  Starting review server...")
        subprocess.Popen(
            [sys.executable, str(REVIEW_SERVER_SCRIPT), "--no-browser",
             "--port", str(REVIEW_SERVER_PORT)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        # サーバーが起動するまで最大3秒待つ
        for _ in range(15):
            time.sleep(0.2)
            if _port_in_use(REVIEW_SERVER_PORT):
                break

    print(f"  Review server running: {url}")
    print(f"  If browser does not open automatically, run:")
    print(f"    open {url}")
    try:
        webbrowser.open(url)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(apply: bool, use_ocr: bool, open_review: bool = True) -> None:
    mode = "apply" if apply else "dry-run"
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    if use_ocr and not ensure_ocr_binary():
        print("⚠ OCR バイナリのコンパイルに失敗しました。--no-ocr で再実行するか、")
        print("  swiftc scripts/vision_ocr.swift -o scripts/vision_ocr を手動実行してください。")
        use_ocr = False

    classified = scan_inbox(INBOX_DIR)
    all_files = classified["PDF"] + classified["IMAGE"] + classified["UNSUPPORTED"]

    _sep()
    print(f"[SCAN]  mode={mode}  ocr={'on' if use_ocr else 'off'}")
    _sep()
    print(f"Found {len(all_files)} files in inbox/")
    if use_ocr:
        print(f"Running OCR on {len(classified['PDF']) + len(classified['IMAGE'])} files ...")
    print()

    analyses = []
    for f in all_files:
        sys.stdout.write(f"  Analyzing: {f.name[:50]!s:<52}\r")
        sys.stdout.flush()
        analyses.append(analyze_file(f, use_ocr))
    sys.stdout.write(" " * 60 + "\r")

    normal = [a for a in analyses if not a["needs_review"]]
    review_needed = [a for a in analyses if a["needs_review"] and not a["needs_ocr_review"]]
    ocr_errors = [a for a in analyses if a["needs_ocr_review"]]

    log_details: List[Dict] = []
    copied_count = 0
    metadata_count = 0

    # -----------------------------------------------------------------------
    # Normal files — SUGGEST or APPLY
    # -----------------------------------------------------------------------
    label = "[APPLY] — safe copy to renamed/" if apply else "[SUGGEST] — rename 候補（dry-run: 変更なし）"
    print(label)
    _sep("-")
    for item in normal:
        tags_info = f" [tag: {', '.join(item['tags'])}]" if item["tags"] else ""
        rename = item["display_rename"]
        ocr_info = " (OCR推定)" if item.get("ocr_rename_candidate") else " (filename推定)"

        if apply:
            dest_path = copy_to_renamed(item["path"], rename)
            dest_rel = dest_path.relative_to(REPO_ROOT)
            metadata = generate_metadata(dest_path.name, source_filename=item["name"])
            metadata["status"] = "renamed"
            meta_path = save_metadata(metadata, METADATA_READY_DIR)
            meta_rel = meta_path.relative_to(REPO_ROOT)
            copied_count += 1
            metadata_count += 1
            print(f"  [COPY]  {item['name']}{tags_info}")
            print(f"          → {dest_rel}{ocr_info}")
            print(f"  [META]  → {meta_rel}")
            log_details.append({"status": "COPY", "src": item["name"], "dest": str(dest_rel),
                                 "ocr_ok": bool(item.get("ocr_text"))})
        else:
            print(f"  {item['name']}{tags_info}")
            print(f"  → {rename}{ocr_info}")
            log_details.append({"status": "DRY-RUN", "src": item["name"], "dest": rename,
                                 "ocr_ok": bool(item.get("ocr_text"))})
    print()

    # -----------------------------------------------------------------------
    # OCR errors
    # -----------------------------------------------------------------------
    if ocr_errors:
        print("[WARNING] — OCR 文字化けの可能性あり（--apply でも処理対象外）")
        _sep("-")
        for item in ocr_errors:
            print(f"  {item['name']}")
            for w in item["warnings"]:
                print(f"    ⚠ {w}")
            rename = item.get("ocr_rename_candidate") or item["rename_hint"]
            print(f"    → rename 候補: {rename}")
            log_details.append({"status": "OCR-ERROR", "src": item["name"],
                                 "warnings": item["warnings"], "ocr_ok": bool(item.get("ocr_text"))})
        print()
        ocr_rpts = write_ocr_error_reports(ocr_errors, timestamp)
        print(f"  レポート保存:")
        for fmt, p in ocr_rpts.items():
            print(f"    [{fmt.upper()}] {p.relative_to(REPO_ROOT)}")
        print()

    # -----------------------------------------------------------------------
    # Review required
    # -----------------------------------------------------------------------
    if review_needed:
        print("[REVIEW REQUIRED] — 確認が必要なファイル（--apply でも処理対象外）")
        _sep("-")
        for item in review_needed:
            print(f"  {item['name']}")
            for w in item["warnings"]:
                print(f"    ⚠ {w}")
            rename = item.get("ocr_rename_candidate") or item["rename_hint"]
            print(f"    → rename 候補: {rename}")
            log_details.append({"status": "REVIEW", "src": item["name"],
                                 "warnings": item["warnings"], "ocr_ok": bool(item.get("ocr_text"))})
        print()
        rev_rpts = write_review_reports(review_needed, timestamp)
        print(f"  レポート保存:")
        for fmt, p in rev_rpts.items():
            print(f"    [{fmt.upper()}] {p.relative_to(REPO_ROOT)}")
        print()

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    _sep()
    print("[SUMMARY]")
    _sep()
    print(f"  mode           : {mode}")
    print(f"  ocr            : {'enabled' if use_ocr else 'disabled'}")
    print(f"  total          : {len(analyses)}")
    print(f"  rename 候補    : {len(normal)}")
    print(f"  copy 実行      : {copied_count}  {'(dry-run: 0)' if not apply else ''}")
    print(f"  metadata 生成  : {metadata_count}  {'(dry-run: 0)' if not apply else ''}")
    print(f"  ocr-error      : {len(ocr_errors)}")
    print(f"  review-required: {len(review_needed)}")
    _sep()

    log_path = _write_log(
        mode=mode, timestamp=timestamp, total=len(analyses),
        normal_count=len(normal), copied=copied_count,
        review_count=len(review_needed), ocr_count=len(ocr_errors),
        metadata_count=metadata_count, use_ocr=use_ocr, details=log_details,
    )
    print(f"\n  ログ保存: {log_path.relative_to(REPO_ROOT)}")
    print()

    if not apply:
        print("Next steps:")
        print("  1. rename 候補（OCR推定）を確認し、問題なければ --apply を実行")
        if review_needed:
            print("  2. レビュー画面で OK / 修正 / 廃棄 を選択し「保存」ボタンを押す")
            print("     → python scripts/apply_review_decisions.py で反映")
        else:
            print("  2. OCR エラー / review 対象は review-report-*.html を開いて確認")
        print("  3. python scripts/process_inbox.py --apply で safe copy 実行")
    else:
        print("Next steps:")
        print("  1. processing/renamed/ のファイル名を確認・必要なら Category を手修正")
        print("  2. processing/metadata-ready/ の .metadata.json で category 等を補完")
        if review_needed:
            print("  3. レビュー画面で OK / 修正 / 廃棄 を選択し「保存」ボタンを押す")
            print("     → python scripts/apply_review_decisions.py で反映")
        else:
            print("  3. OCR エラー / review 対象は review-report-*.html を開いて手動対応")
        print("  4. docs/export-rules.md の条件を満たしたら export/ または archive/ へ")

    if review_needed:
        if open_review:
            _launch_review_server(len(review_needed))
        else:
            # --no-open-review でも URL は常に表示する
            url = f"http://localhost:{REVIEW_SERVER_PORT}"
            print()
            print(f"  Review required: {len(review_needed)} file(s)")
            print(f"  To start review server: python scripts/review_server.py")
            print(f"  Then open: {url}")
            print(f"  Or run:    open {url}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="inbox を分析・rename・metadata 生成する",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python scripts/process_inbox.py                   # dry-run + OCR（デフォルト）
  python scripts/process_inbox.py --dry-run         # 同上
  python scripts/process_inbox.py --no-ocr          # OCR なしで高速に実行
  python scripts/process_inbox.py --apply           # renamed/ へ safe copy + metadata 生成
  python scripts/process_inbox.py --no-open-review  # レビュー画面を自動起動しない
        """,
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--dry-run", action="store_true", default=False)
    mode_group.add_argument("--apply", action="store_true", default=False)
    parser.add_argument("--no-ocr", action="store_true", default=False, help="OCR をスキップ")

    review_group = parser.add_mutually_exclusive_group()
    review_group.add_argument(
        "--open-review", action="store_true", default=False,
        help="review-required があればレビュー画面を自動起動（デフォルト動作）",
    )
    review_group.add_argument(
        "--no-open-review", action="store_true", default=False,
        help="review-required があってもレビュー画面を自動起動しない",
    )
    args = parser.parse_args()

    # --no-open-review が明示された場合のみ無効化。それ以外はデフォルトで自動起動
    open_review = not args.no_open_review
    run(apply=args.apply, use_ocr=not args.no_ocr, open_review=open_review)
