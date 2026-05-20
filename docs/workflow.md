# ワークフロー — Document Flow Workflow

このドキュメントは、Document Flow Agent の処理フローと役割分担を定義します。

Claude Cowork が月次運用を行う際の手順書として使用してください。

---

## OCR 起点 rename の思想

**ファイル名ではなく、PDFの中身を見てrename候補を作る。**

- ファイル名が日付のみ（`20260517.pdf`）でも、PDF を開いて OCR し、内容から Category・Document・Counterparty を推定する
- ファイル名が文字化けしていても、OCR テキストから正しい内容を取得できる場合がある
- OCR 候補はあくまで **推定** であり、人間の確認が前提
- `--apply` はOCR候補を使ってファイルをコピーするが、review-required は対象外

### OCR の仕組み

```
PDF / 画像ファイル
       |
       | 画像の場合: scripts/normalize_images.py（Pillow）
       |   .jpg/.jpeg/.png → processing/normalized/ に単一ページ PDF を生成
       |   元画像は変更しない
       ↓
  正規化済み PDF（または元 PDF）
       |
       | sips（macOS 標準）で1ページ目を JPEG に変換
       ↓
  JPEG 画像
       |
       | scripts/vision_ocr（macOS Vision Framework / Swift）
       | 日本語・英語 OCR
       ↓
  OCR テキスト
       |
       | scripts/ocr_extract.py（ヒューリスティック解析）
       | 日付・Category・Document・Counterparty・金額を推定
       ↓
  rename 候補
```

### レポートの使い分け

| 形式 | 目的 | 用途 |
|---|---|---|
| `.json` | 機械処理用 | スクリプトからの読み取り |
| `.md` | 人間確認用（テキスト） | テキストエディタ・Obsidian での確認 |
| `.html` | 人間確認用（ビジュアル） | ブラウザで開く・印刷・チェック記入 |

---

## Current Flow

```
[Capture]
  iPhone でスキャン / カメラ撮影
        |
        ↓
[Inbox]
  inbox/ に配置（自由・命名規約不要）
        |
        | python scripts/normalize_documents.py
        | → ファイル一覧・文字化け検出・リネームヒント表示
        |
        |
        | 画像ファイル（.jpg/.png）は自動的に PDF へ正規化
        | → processing/normalized/ に一時保存（OCR 後は削除不要）
        ↓
[Dry-run]  ← デフォルト。必ず先に実行する
  python scripts/process_inbox.py --dry-run
  → rename 候補を表示（ファイルは変更しない）
  → OCR エラー検出 → processing/ocr-error/ にレポート
  → review 要否判定 → processing/review-required/ にレポート
  → ログ → logs/process-inbox-YYYYMMDD-HHMMSS.log
  → review-required が1件以上ある場合はレビューサーバーを自動起動してブラウザを開く
     （--no-open-review で無効化できる）
        |
        ↓
[Review]  ← 人間 / Claude Cowork による確認
  - ocr-error: PDF を開いて文字化けを修正
  - review-required: process_inbox.py 実行後にレビューサーバーが自動起動する
      表示例:
        Review required: 1 file(s)
        Review server running: http://localhost:8765
        If browser does not open automatically, run:
          open http://localhost:8765
      手動起動: python scripts/review_server.py
      1. ブラウザで http://localhost:8765 を開く
      2. 各カードのラジオボタンで OK / 修正 / 廃棄 を選択
      3. 「保存」ボタン押下 → review-decisions.json が自動保存される
      4. python scripts/apply_review_decisions.py を実行
         → 処理後に review-decisions.json は applied/ へ自動移動（再適用防止）
  - 廃棄対象: inbox から手動削除してログに記録
        |
        ↓
[Apply]  ← 人間確認後のみ実行
  python scripts/process_inbox.py --apply
  → review 不要ファイルのみ processing/renamed/ へコピー
  → inbox の元ファイルは残す（削除しない）
  → 同名ファイルは -001, -002 ... で連番付与（上書きなし）
  → metadata scaffold を processing/metadata-ready/ へ自動生成
        |
        ↓
[Rename 補完]  ← 人間 / Claude Cowork
  processing/renamed/ のファイル名を確認
  Category を正式なものに手動で補完する
  命名規約: YYYYMMDD-Category-Document-[Counterparty]-[AmountJPY]-[PaymentMethod].pdf
        |
        | python scripts/generate_metadata.py（残り分の補完）
        ↓
[Metadata 補完]
  processing/metadata-ready/ の .metadata.json を確認・補完
  - category（必須）
  - counterparty（あれば）
  - amount_jpy / payment_method（あれば）
  - discard_date（保存期間から計算）
        |
        | 人間による最終確認（docs/export-rules.md の条件を満たしたか確認）
        ↓
[Export Buffer]
  python scripts/check_export_ready.py  ← export 可能か確認
  python scripts/export_to_dropbox.py --local  ← export/files/ と export/metadata/ へコピー
  - export/files/    : renamed/ PDF のコピー
  - export/metadata/ : metadata-ready/ JSON のコピー
  ※ 元ファイル（renamed/, metadata-ready/）は削除しない
        |
        | 月次・手動
        | python scripts/export_to_dropbox.py (将来実装)
        ↓
[Archive original input]  ← export 完了後
  python scripts/archive_input.py --dry-run  ← 移動先を確認
  python scripts/archive_input.py --apply    ← inbox/ → archive/original-input/YYYYMM/ へ移動
  - ファイル名先頭の日付から月フォルダを決定
  - 日付なし → ファイルの更新日時を使用
  - 同名ファイルは -001, -002 ... で連番付与（上書きなし）
  - 処理済みファイル未検出時は安全チェックで停止（--force で強制）
        |
        ↓
[Dropbox]
  00_DocumentVault/99_Imported/ へ転送
  月次レビューで各フォルダへ振り分け
        |
        | 重要なもののみ
        ↓
[Notion]
  期限・アクション・関係者があるファイルのみ登録
```

---

## 役割分担

| フェーズ | 担当 | 作業内容 |
|---|---|---|
| Capture | **Human** | iPhone でスキャン・撮影 |
| Inbox | **Human** | inbox/ にファイルを配置 |
| Normalize | **Claude Cowork** | `normalize_documents.py` 実行・結果確認 |
| Dry-run | **Claude Cowork** | `process_inbox.py --dry-run` 実行・レポート確認 |
| Review | **Human + Claude Cowork** | 文字化け修正・Category 決定・廃棄判断 |
| Apply | **Human 確認後に Claude Cowork** | `process_inbox.py --apply` で safe copy + metadata 自動生成 |
| Rename 補完 | **Human / Claude Cowork** | renamed/ のファイル名に Category を手動追加 |
| Metadata 補完 | **Claude Cowork** | `.metadata.json` を開いて category 等を補完 |
| Export Buffer | **Human** | export-rules を確認して export/ または archive/ へ移動 |
| Archive Input | **Claude Cowork** | `archive_input.py --apply` で inbox 原本を月別アーカイブ |
| Dropbox | **Human** | 月次で export/ → Dropbox へ手動転送 |
| Notion | **Human** | 重要ファイルのみ登録 |
| 開発・保守 | **Claude Code** | スクリプト改修・構造変更 |

---

## 月次運用チェックリスト（Claude Cowork 向け）

```
[ ] 1.  python scripts/normalize_documents.py
        → inbox のファイル一覧・文字化け検出を確認

[ ] 2.  python scripts/process_inbox.py --dry-run
        → rename 候補・ocr-error・review-required を確認（ファイルは変更されない）

[ ] 3.  processing/ocr-error/ のレポートを確認
        → 該当 PDF を開いて文字化けを修正 → 手動で renamed/ へコピー

[ ] 4.  python scripts/review_server.py を起動
        → ブラウザで http://localhost:8765 を開く
        → 各カードで OK / 修正 / 廃棄 を選択
        → 「保存」ボタン押下（review-decisions.json に自動保存）
        → python scripts/apply_review_decisions.py を実行

[ ] 5.  廃棄対象を inbox から削除（ログに「廃棄」として記録）

[ ] 6.  python scripts/process_inbox.py --apply
        → review 不要ファイルを renamed/ へ safe copy
        → metadata scaffold を metadata-ready/ へ自動生成

[ ] 7.  processing/renamed/ のファイル名を確認
        → Category が入っていないファイルはファイル名を手動で修正

[ ] 8.  processing/metadata-ready/ の .metadata.json を開いて不足項目を補完
        → category, counterparty, discard_date など

[ ] 9.  python scripts/check_export_ready.py
        → Export ready: YES になることを確認
        → [NG] があれば解決してから先に進む

[ ] 10. python scripts/export_to_dropbox.py --local --dry-run
        → コピー対象ファイルを確認（ファイル変更なし）

[ ] 11. python scripts/export_to_dropbox.py --local
        → export/files/ と export/metadata/ へコピー
        → ログ: logs/export-YYYYMMDD-HHMMSS.log

[ ] 12. export/ の内容を Dropbox の 99_Imported/ へ月次手動転送

[ ] 13. python scripts/archive_input.py --dry-run
        → 移動先（archive/original-input/YYYYMM/）を確認

[ ] 14. python scripts/archive_input.py --apply
        → inbox/ の処理済み原本を月別フォルダへ移動
        → inbox が空になることを確認

[ ] 15. 重要ファイルを Notion に登録
```

---

## フォルダ状態の正常系

| フォルダ | 月次処理後の理想状態 |
|---|---|
| `inbox/` | `archive_input.py --apply` 実行後は空（次のスキャン分が来るまで） |
| `archive/original-input/YYYYMM/` | 月別アーカイブ済み原本（累積） |
| `processing/normalized/` | 一時的な正規化済み PDF（画像→PDF 変換結果。次のスキャンまで保持可） |
| `processing/review-required/` | レポート JSON のみ（PDF は移動しない） |
| `processing/renamed/` | 処理中 PDF のみ（metadata 生成後は metadata-ready へ） |
| `processing/metadata-ready/` | PDF + .metadata.json のペア |
| `processing/ocr-error/` | レポート JSON のみ（修正済みファイルは renamed へ） |
| `export/` | 月次 Dropbox 転送後は空 |
| `archive/` | 累積していく（定期的にレビュー） |

---

## 参照ドキュメント

| ドキュメント | 内容 |
|---|---|
| [`docs/naming-convention.md`](naming-convention.md) | ファイル命名規約 |
| [`docs/categories.md`](categories.md) | Category 一覧と分類ガイド |
| [`docs/payment-methods.md`](payment-methods.md) | 支払手段一覧 |
| [`docs/export-rules.md`](export-rules.md) | export 可能条件と処理フロー |
| [`docs/dropbox-structure.md`](dropbox-structure.md) | Dropbox フォルダ構造 |
| [`docs/architecture.md`](architecture.md) | ツール別役割定義 |

---

## 変更履歴

| 日付 | 内容 |
|---|---|
| 2026-05-17 | 初期作成 |
