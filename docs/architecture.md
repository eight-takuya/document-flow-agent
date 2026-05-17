# Architecture — Document Flow Agent

## 概要

このドキュメントは、Document Flow Agent を構成する各ツールの役割と連携関係を定義します。

---

## ツール別役割定義

### Claude Code
- **役割**: 構造・スクリプト・エージェントの構築と保守
- **担当範囲**:
  - フォルダ構造の設計と変更
  - Python スクリプトの開発・改修
  - 新しい処理ロジックの実装
  - CLAUDE.md・README・アーキテクチャドキュメントの更新
- **起動タイミング**: 構造変更・スクリプト追加・バグ修正時

---

### Claude Cowork
- **役割**: 月次運用・分類支援・整理の実行
- **担当範囲**:
  - inbox の内容確認とファイル分類
  - ファイルリネームの実行支援
  - archive / export への振り分け判断
  - Notion 登録対象の選別
  - 処理ログの記録
- **起動タイミング**: 月次処理時、inbox にファイルが溜まった時
- **読むべきドキュメント**: README.md、docs/architecture.md、docs/dropbox-structure.md

---

### Dropbox
- **役割**: 静的保管庫
- **担当範囲**:
  - 処理済ファイルの長期保管
  - バックアップ
- **特記事項**:
  - Dropbox 自体は整理場所ではない
  - 月次で `export/` の中身を手動移動する
  - 構造は `docs/dropbox-structure.md` を参照

---

### Notion
- **役割**: 意味・関係性・期限の管理
- **担当範囲**:
  - 重要ファイルのメタデータ登録
  - 期限・アクション管理
  - 関係者・案件との紐付け
- **特記事項**:
  - すべてのファイルを登録しない
  - 期限・アクション・重要性がある場合のみ登録
  - `templates/metadata_template.json` をベースに登録

---

### ローカルフォルダ（このリポジトリ）
- **役割**: 動的処理領域
- **担当範囲**:
  - スキャンファイルの受け取り（inbox）
  - 処理中ファイルの一時置き場（processing）
  - ローカル保管（archive）
  - Dropbox 送出準備（export）
- **特記事項**:
  - inbox と processing は常に「流れている」状態が正常
  - 長期的にファイルが滞留していたら要確認

---

## データフロー図

```
iPhone スキャン
      |
      v
   inbox/
      |
      | Claude Cowork で分類支援
      v
 processing/  ←── 判断保留
      |
      |─────────────────────────┐
      v                         v
  archive/                  export/
（ローカル保管）          （Dropbox 送出待ち）
                               |
                               | 月次・手動移動
                               v
                           Dropbox
                        00_DocumentVault/
                               |
                               | 重要なもののみ
                               v
                            Notion
```

---

## 変更履歴

| 日付 | 内容 |
|---|---|
| 2026-05-17 | 初期作成 |
