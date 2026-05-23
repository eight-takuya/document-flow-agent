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

```
[Capture]  iPhone でスキャン → inbox/
     ↓
[Image Normalize]  .jpg/.png → PDF（processing/normalized/）
     ↓
[Split Multi-page PDF]  複数ページ PDF → 1ページ=1PDF（processing/splitted/）
     ↓
[OCR]  macOS Vision Framework で内容認識
     ↓
[Review / Auto-approved]  高信頼度は自動承認・要確認はレビュー UI
     ↓
[Apply]  rename + metadata 生成（processing/renamed/ or auto-approved/）
     ↓
[Export]  export/files/ へコピー
     ↓
[Archive Original Input]  inbox 原本 → archive/original-input/YYYYMM/
```

### Step 1 — スキャン → inbox
iPhone でスキャン後、`inbox/` に配置する。ファイル名・形式は自由。

### Step 2 — normalize（現状確認）

```bash
python scripts/normalize_documents.py
```

ファイル一覧・文字化け検出・リネームヒントを表示する（ファイルは動かさない）。

### Step 2.5 — split（複数ページ PDF 分割）

```bash
python scripts/split_receipts.py                 # inbox の複数ページ PDF を一覧（dry-run）
python scripts/split_receipts.py --apply         # 実際に分割して processing/splitted/ へ出力
```

複数領収証が 1 つの PDF にまとめてスキャンされている場合は、`split_receipts.py` で 1ページ = 1PDF に分割する。  
`process_inbox.py` は自動的に複数ページ PDF を分割してから OCR する（`--no-split` で無効化）。

- 分割先: `processing/splitted/`
- 命名例: `20260522_receipts.pdf` → `20260522_receipts-p001.pdf`, `20260522_receipts-p002.pdf`
- 元 PDF は inbox に保持（分割後 PDF は一時生成物）
- 分割後 PDF の metadata に `split_source`, `split_page`, `split_pdf` フィールドを追加

### Step 3 — analyze / dry-run（OCR分析・レポート生成）

```bash
python scripts/process_inbox.py                   # デフォルトは --dry-run + OCR + 自動分割
python scripts/process_inbox.py --dry-run         # 同上
python scripts/process_inbox.py --no-ocr          # OCR なしで高速実行
python scripts/process_inbox.py --no-split        # 複数ページ PDF を分割しない
python scripts/process_inbox.py --no-open-review  # レビュー画面を自動起動しない
```

**`--dry-run` がデフォルト。ファイルコピーは行わない。**  
※ 複数ページ PDF の分割ファイル（`processing/splitted/`）は dry-run でも生成される（OCR に必要なため）。

- 複数ページ PDF を自動検出 → `processing/splitted/` に 1ページ = 1PDF として分割
- **ファイル名ではなく PDF の中身を OCR して** rename 候補を生成（macOS Vision Framework 使用）
- rename 候補フォーマット: `YYYYMMDD-Category-Document-Counterparty.pdf`
- 文字化け疑い → `processing/ocr-error/` に JSON / Markdown / HTML レポートを生成
- 要確認 → `processing/review-required/` に JSON / Markdown / HTML レポートを生成
- **review-required が 1 件以上ある場合はレビューサーバーを自動起動し、ブラウザでレビュー画面を開く**
- 実行ログ → `logs/process-inbox-YYYYMMDD-HHMMSS.log`

**レポートの使い分け**
- `.json` → 機械処理用（スクリプトからの読み取り）
- `.md` → テキストエディタ・Obsidian で確認
- `.html` → ブラウザで開く（OCR テキスト展開・チェックボックス付き）

### Step 4 — review（人間 + Claude Cowork による確認）

dry-run の結果を確認する。

#### 4a — OCR エラー対応

`processing/ocr-error/` レポートを確認し、該当 PDF を開いて文字化けを手動修正する。

#### 4b — review-required 対応（ローカルサーバー経由で保存）

`process_inbox.py` 実行時に review-required が発生すると、自動的にレビューサーバーが起動し以下が表示されます:

```
  Review required: 1 file(s)
  Review server running: http://localhost:8765
  If browser does not open automatically, run:
    open http://localhost:8765
```

ブラウザが自動で開かない場合（Claude Code 環境など）は手動で開いてください:

```bash
python scripts/review_server.py   # サーバーを単体起動する場合
open http://localhost:8765        # ブラウザを手動で開く
```

1. 各ファイルのカードに表示された OCR rename 候補と警告を確認する
2. 各カードのラジオボタンで判断を選ぶ:
   - **OK** — OCR 候補のまま rename する
   - **修正** — ファイル名を編集して rename する（入力欄に OCR 候補が初期値として入る）
   - **廃棄** — このファイルは保管不要
3. 「**保存**」ボタンを押す → `processing/review-required/review-decisions.json` に自動保存
4. 以下を実行して rename / metadata 生成を適用する:

```bash
python scripts/apply_review_decisions.py
```

5. 適用後、`review-decisions.json` は `processing/review-required/applied/` へ自動移動される（再適用防止）
6. 廃棄判断したファイルは inbox から手動削除してログに記録する

> **サーバーを使わない場合:** 「コピー」ボタンで JSON をクリップボードに取得し、  
> `processing/review-required/review-decisions.json` にテキストエディタで貼り付けて保存する。

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

### Step 6 — export 準備確認と export/ へのコピー

#### export 可能条件

- `review-decisions.json` が残っていない（apply 済み）
- `processing/renamed/` に PDF が存在する
- `processing/metadata-ready/` に metadata JSON が存在する

まず export 可能か判定します:

```bash
python3 scripts/check_export_ready.py
```

出力例:
```
[OK]      review-required decisions applied
[OK]      renamed files found: 13
[OK]      metadata files found: 16
[WARNING] ocr-error files remain: 3 (手動対応が必要です)

Export ready: YES
```

`Export ready: YES` になったら export を実行します:

```bash
python3 scripts/export_to_dropbox.py --local --dry-run  # 確認のみ（ファイル変更なし）
python3 scripts/export_to_dropbox.py --local            # 実際にコピー
```

コピー先:
- `processing/renamed/*.pdf` → `export/files/`
- `processing/metadata-ready/*.metadata.json` → `export/metadata/`

> **ocr-error** が残っていても WARNING 扱いで export 可能です。  
> **review-decisions.json** が残っている場合は export 不可（`apply_review_decisions.py` を先に実行）。

### Step 7 — 月次で Dropbox へ手動転送

`export/files/` と `export/metadata/` の内容を Dropbox の `00_DocumentVault/99_Imported/` へ手動移動する。

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

- **正規化**: `.jpg` / `.png` / `.jpeg` を単一ページ PDF へ自動変換（`processing/normalized/` に一時保存）
- **OCR**: 正規化済み PDF からテキストを抽出する（Vision Framework）
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
| `normalize_images.py` | .jpg/.png を PDF へ変換（process_inbox から自動呼び出し） | process_inbox 内部 |
| `split_receipts.py` | 複数ページ PDF を 1ページ=1PDF に分割（process_inbox から自動呼び出し） | process_inbox 内部 |
| `process_inbox.py` | 分析・rename 候補・レポート生成 | normalize の次 |
| `rename_documents.py` | 命名規約のファイル名生成・検証 | rename 時に参照 |
| `generate_metadata.py` | metadata scaffold 生成 | renamed/ 配置後 |
| `review_server.py` | review-report HTML 表示・保存用ローカルサーバー | review-required 確認時 |
| `apply_review_decisions.py` | review-decisions.json を処理して rename/discard/skip を実行 | review HTML 確認後 |
| `check_export_ready.py` | export 可能か判定（review 残・renamed 有無・metadata 対応） | export 前 |
| `export_to_dropbox.py` | renamed/ と metadata-ready/ を export/ へコピー（--local） | check 後 |
| `archive_input.py` | inbox 原本を archive/original-input/YYYYMM/ へ月別アーカイブ | export 後 |
| `scan_inbox_watcher.py` | inbox 監視（将来実装） | 常駐 |

---

## inbox 原本アーカイブ

処理完了後、inbox 原本を月別フォルダへ退避する。

```bash
python3 scripts/archive_input.py --dry-run   # 移動先確認（ファイルは変更しない）
python3 scripts/archive_input.py --apply     # 実際に移動（export 後に実行）
```

アーカイブ先: `archive/original-input/YYYYMM/`

- ファイル名先頭の日付（YYYYMMDD）から月フォルダを決定
- 日付が取れない場合はファイルの更新日時を使用
- 同名ファイルがある場合は `-001`, `-002` を付与（上書き禁止）
- `export/files/` または `processing/renamed/` または `processing/auto-approved/` に処理済みファイルがない場合は安全チェックで停止
- 強制実行: `--force` オプション

---

## 運用ルール（Claude Cowork 向け）

- 月次処理は `docs/workflow.md` のチェックリストに沿って進める
- **inbox の原本は export 完了後に `archive_input.py --apply` で退避する**（export 前は削除不可）
- 分類・リネームは `docs/naming-convention.md` と `docs/categories.md` を参照する
- export は `docs/export-rules.md` の条件を満たしたもののみ
- `logs/` には処理日時・ファイル名・アクションを記録する
- `Other` カテゴリが溜まってきたら新しい Category 追加を検討する
