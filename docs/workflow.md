# ワークフロー — Document Flow Workflow

このドキュメントは、Document Flow Agent の処理フローと役割分担を定義します。

Claude Cowork が月次運用を行う際の手順書として使用してください。

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
        ↓
[Normalize & Analyze]
  python scripts/process_inbox.py
  → rename 候補提示
  → OCR エラー検出 → processing/ocr-error/ にレポート
  → review 要否判定 → processing/review-required/ にレポート
        |
        ↓
[Review]  ← 人間 / Claude Cowork による確認
  - ocr-error: PDF を開いて文字化けを修正
  - review-required: 内容確認・Category 決定
  - 廃棄対象: inbox から削除してログに記録
        |
        | 手動コピー（inbox のファイルは削除しない）
        ↓
[Rename]
  processing/renamed/ に命名規約ファイル名でコピー
  命名規約: YYYYMMDD-Category-Document-[Counterparty]-[AmountJPY]-[PaymentMethod].pdf
        |
        | python scripts/generate_metadata.py
        ↓
[Metadata]
  processing/metadata-ready/ に .metadata.json を生成
  metadata を目視確認・補完（Counterparty・金額・廃棄日など）
        |
        | 人間による最終確認（docs/export-rules.md の条件を満たしたか確認）
        ↓
[Export Buffer]
  export/ または archive/ へ手動移動
  - export/  : Dropbox 送出予定
  - archive/ : ローカル保管のみ
        |
        | 月次・手動
        | python scripts/export_to_dropbox.py (将来実装)
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
| Analyze | **Claude Cowork** | `process_inbox.py` 実行・レポート確認 |
| Review | **Human + Claude Cowork** | 文字化け修正・Category 決定・廃棄判断 |
| Rename | **Claude Cowork** | 命名規約に従ってファイルを renamed/ へコピー |
| Metadata | **Claude Cowork** | `generate_metadata.py` 実行・metadata 補完 |
| Export Buffer | **Human** | export-rules を確認して export/ または archive/ へ移動 |
| Dropbox | **Human** | 月次で export/ → Dropbox へ手動転送 |
| Notion | **Human** | 重要ファイルのみ登録 |
| 開発・保守 | **Claude Code** | スクリプト改修・構造変更 |

---

## 月次運用チェックリスト（Claude Cowork 向け）

```
[ ] 1. normalize_documents.py を実行して inbox のファイル一覧を確認
[ ] 2. process_inbox.py を実行して分析レポートを生成
[ ] 3. ocr-error/ レポートを確認 → 文字化けファイルを目視修正
[ ] 4. review-required/ レポートを確認 → Category を決定
[ ] 5. 廃棄対象ファイルを inbox から削除（ログに記録）
[ ] 6. 残りのファイルを renamed/ へ手動コピー（命名規約のファイル名で）
[ ] 7. generate_metadata.py を実行して metadata scaffold を生成
[ ] 8. metadata-ready/ の .metadata.json を開いて不足項目を補完
[ ] 9. docs/export-rules.md の export 可能条件を確認
[ ] 10. 条件を満たしたファイルを export/ または archive/ へ移動
[ ] 11. export/ が Dropbox へ転送済みか確認（月次手動作業）
[ ] 12. 重要ファイルを Notion に登録
```

---

## フォルダ状態の正常系

| フォルダ | 月次処理後の理想状態 |
|---|---|
| `inbox/` | 処理済みファイルのみ残る（次のスキャン分が来るまで保持） |
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
