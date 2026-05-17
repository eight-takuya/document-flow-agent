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
├── inbox/                    # iPhone スキャン PDFの投入先（自由・生状態）
├── processing/               # 分類・OCR・リネーム処理中
│   ├── review-required/      # 確認が必要なファイルのレポート
│   ├── renamed/              # リネーム済みファイル
│   ├── metadata-ready/       # metadata JSON 生成済みファイル
│   └── ocr-error/            # 文字化け疑いのレポート
├── archive/                  # ローカル整理済ファイル
├── export/                   # Dropbox 移動予定ファイル（人間確認済みバッファ）
├── scripts/                  # Python スクリプト群
├── logs/                     # 処理ログ
├── templates/                # metadata テンプレート
└── docs/                     # 運用方針・アーキテクチャメモ
```

---

## 処理フロー（半自動レビュー運用）

完全自動化ではなく、**安全確認付き半自動運用**が基本方針です。  
詳細は [`docs/workflow.md`](docs/workflow.md) を参照してください。

### Step 1 — スキャン → inbox
iPhone でスキャン後、`inbox/` に配置する。ファイル名・形式は自由。

### Step 2 — normalize（現状確認）

```bash
python scripts/normalize_documents.py
```

ファイル一覧・文字化け検出・リネームヒントを表示する（ファイルは動かさない）。

### Step 3 — analyze / dry-run（OCR分析・レポート生成）

```bash
python scripts/process_inbox.py          # デフォルトは --dry-run + OCR
python scripts/process_inbox.py --dry-run
python scripts/process_inbox.py --no-ocr # OCR なしで高速実行
```

**`--dry-run` がデフォルト。ファイルは一切変更しない。**

- **ファイル名ではなく PDF の中身を OCR して** rename 候補を生成（macOS Vision Framework 使用）
- rename 候補フォーマット: `YYYYMMDD-Category-Document-Counterparty.pdf`
- 文字化け疑い → `processing/ocr-error/` に JSON / Markdown / HTML レポートを生成
- 要確認 → `processing/review-required/` に JSON / Markdown / HTML レポートを生成
- 実行ログ → `logs/process-inbox-YYYYMMDD-HHMMSS.log`

**レポートの使い分け**
- `.json` → 機械処理用（スクリプトからの読み取り）
- `.md` → テキストエディタ・Obsidian で確認
- `.html` → ブラウザで開く（OCR テキスト展開・チェックボックス付き）

### Step 4 — review（人間 + Claude Cowork による確認）

dry-run の結果を確認する。

- `ocr-error/` レポートのファイルは PDF を開いて文字化けを修正
- `review-required/` レポートのファイルは内容を確認して Category を決定
- 廃棄対象は inbox から削除

### Step 5 — apply（safe copy + metadata 自動生成）

review 不要と判断したら `--apply` を実行する。

```bash
python scripts/process_inbox.py --apply
```

- **review 不要ファイルのみ** `processing/renamed/` へコピー（inbox は残る）
- OCR エラー・review 必要なファイルは `--apply` でも処理対象外
- 同名ファイルは上書きせず連番（`-001`, `-002`）を付与
- 同時に `processing/metadata-ready/` に `.metadata.json` を自動生成
- metadata の `category` 欄は空（人間が後で補完）

### Step 6 — metadata 補完

`processing/metadata-ready/` の `.metadata.json` を開いて不足項目を補完する。

```bash
python scripts/generate_metadata.py  # renamed/ に残ったファイルの分を追加生成
```

### Step 6 — export または archive へ移動（人間による最終確認）

[`docs/export-rules.md`](docs/export-rules.md) の export 可能条件を満たしたものを移動する。

- ローカル保管 → `archive/`
- Dropbox 送出予定 → `export/`

### Step 7 — 月次で Dropbox へ手動転送

`export/` の内容を Dropbox の `00_DocumentVault/99_Imported/` へ手動移動する。

### Step 8 — 重要なもののみ Notion に登録

期限・アクション・重要性があるファイルのみ Notion に登録する。

---

## フォルダ別方針

### inbox — 自由な入口

`inbox/` は整理の入口です。完璧なファイル名・形式は求めません。

- 受け入れる形式: `.pdf` `.png` `.jpg` `.jpeg`
- ファイル名は仮のままでよい（例: `scan_20260517.pdf`、`IMG_1234.jpg`）
- iPhone スキャン・カメラ撮影・メール添付など何でも投入する
- inbox にあるファイルはスクリプトで変更しない（読み取り専用扱い）

ファイルの状態を確認するには:

```bash
python scripts/normalize_documents.py
```

---

### processing — 整える場所

`processing/` は分類・変換・リネームを行う一時領域です。

- **OCR**: 画像・スキャン PDF からテキストを抽出する
- **PDF 化**: `.png` / `.jpg` / `.jpeg` を PDF に変換する
- **リネーム**: `docs/naming-convention.md` の命名規約を適用する（`scripts/rename_documents.py` 参照）
- **metadata 生成**: `templates/metadata_template.json` に基づき `.json` を作成する

処理後は `archive/` または `export/` へ移動する。

---

### archive / export — 整理済みバッファ

- `archive/`: ローカルに残す整理済みファイル。原則 PDF 形式
- `export/`: Dropbox への移動を待つ確定ファイル。月次で手動移動する
- どちらも命名規約が適用済みの状態で格納する

---

## 命名規約

```
YYYYMMDD-Category-Document-Counterparty-AmountJPY-PaymentMethod.pdf
```

詳細は [`docs/naming-convention.md`](docs/naming-convention.md) を参照。  
Category 一覧は [`docs/categories.md`](docs/categories.md)、支払手段は [`docs/payment-methods.md`](docs/payment-methods.md) を参照。

---

## スクリプト一覧

| スクリプト | 役割 | 実行タイミング |
|---|---|---|
| `normalize_documents.py` | inbox のファイル一覧・文字化け検出 | 月次処理開始時 |
| `process_inbox.py` | 分析・rename 候補・レポート生成 | normalize の次 |
| `rename_documents.py` | 命名規約のファイル名生成・検証 | rename 時に参照 |
| `generate_metadata.py` | metadata scaffold 生成 | renamed/ 配置後 |
| `export_to_dropbox.py` | export/ → Dropbox 転送 | 月次・手動 |
| `scan_inbox_watcher.py` | inbox 監視（将来実装） | 常駐 |

---

## 運用ルール（Claude Cowork 向け）

- 月次処理は `docs/workflow.md` のチェックリストに沿って進める
- **inbox のファイルは絶対に削除・移動しない**（コピーのみ）
- 分類・リネームは `docs/naming-convention.md` と `docs/categories.md` を参照する
- export は `docs/export-rules.md` の条件を満たしたもののみ
- `logs/` には処理日時・ファイル名・アクションを記録する
- `Other` カテゴリが溜まってきたら新しい Category 追加を検討する
