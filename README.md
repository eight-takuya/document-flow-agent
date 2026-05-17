# Document Flow Agent

紙書類を「整理する」のではなく、「流す」ための処理基盤。

---

## コンセプト

このエージェントは、紙書類の電子化から保管までの一連の流れを自動化・半自動化するためのものです。

- **整理ではなく流れ** — ファイルを完璧に分類することが目的ではない。まず電子化し、inbox に入れ、流れを止めないことが優先
- **まず電子化** — iPhone でスキャンしてすぐ inbox へ。判断は後でよい
- **AI で軽く分類** — Claude Cowork が分類・リネームを支援。人間の判断が必要なものだけ止める
- **必要なものだけ意味付け** — すべてを Notion に登録しない。重要度・期限があるものだけ
- **月次で静的保管** — Dropbox は「流れ先」であり「整理場所」ではない

---

## 役割分離

| ツール | 役割 |
|---|---|
| Claude Code | Agent・スクリプト・構造の構築・保守 |
| Claude Cowork | 月次運用・分類支援・整理の実行 |
| Dropbox | 静的保管庫（処理済ファイルの最終置き場） |
| Notion | 意味・関係性・期限の管理（重要ファイルのみ） |
| ローカルフォルダ | 動的処理領域（inbox → processing → archive/export） |

---

## フォルダ構造

```
document-flow-agent/
├── inbox/          # iPhone スキャン PDFの投入先
├── processing/     # 分類・OCR・リネーム処理中
├── archive/        # ローカル整理済ファイル
├── export/         # Dropbox 移動予定ファイル
├── scripts/        # Python スクリプト群
├── logs/           # 処理ログ
├── templates/      # metadata テンプレート
└── docs/           # 運用方針・アーキテクチャメモ
```

---

## 処理フロー

### Step 1 — スキャン
iPhone で書類をスキャンする（PDF 推奨）。

### Step 2 — inbox へ格納
スキャンした PDF を `inbox/` フォルダへ移動する。
ファイル名は仮でよい（例: `scan_20260517.pdf`）。

### Step 3 — Claude Cowork で分類支援
Claude Cowork を起動し、inbox のファイルを確認。
カテゴリ・タイトル・保存期間を元に分類・リネームを行う。
`scripts/classify_documents.py` と `scripts/rename_documents.py` を活用する。

### Step 4 — archive または export へ移動
- ローカルに残すもの → `archive/`
- Dropbox へ送るもの → `export/`

### Step 5 — 月次で Dropbox へ手動移動
`export/` 内のファイルを Dropbox の対応フォルダへ移動する。
移動後は `export/` を空にする。

### Step 6 — 必要なもののみ Notion へ登録
期限・アクション・重要性があるファイルだけ Notion に登録する。
`templates/metadata_template.json` をベースにメタデータを付与する。

---

## 運用ルール（Claude Cowork 向け）

- inbox にファイルがある場合、最初に一覧を確認してから処理を開始する
- ファイル名は `YYYYMMDD_カテゴリ_相手先_概要.pdf` 形式を推奨
- 判断できないファイルは `processing/` に留め置き、コメントをログに残す
- `logs/` には処理日時・ファイル名・アクションを記録する
- 月次処理後、`export/` が空になっていることを確認する
