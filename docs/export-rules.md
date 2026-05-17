# Export ルール — Export Rules

## 基本思想

`export/` は **「人間確認済み」の安全バッファ** です。

- export に入ったファイルは「Dropbox 送出可能」として人間が承認したもの
- スクリプトが自動的に export へ移動することはない
- Dropbox への転送は月次で手動実行する

**完全自動化は行わない。最終判断は人間が行う。**

---

## export 可能条件

以下の条件をすべて満たしたファイルのみ `export/` へ移動できます。

| 条件 | 確認方法 |
|---|---|
| ✅ rename 済み（命名規約に適合） | `scripts/rename_documents.py` でファイル名を検証 |
| ✅ Category 確定済み | ファイル名に有効な Category が含まれている |
| ✅ OCR 重大問題なし | `processing/ocr-error/` に入っていない |
| ✅ discard 判定済み（廃棄しない） | 月次レビューで保存対象と判断済み |
| ✅ metadata 生成済み | `processing/metadata-ready/` に .metadata.json が存在する |

---

## processing サブフォルダの意味

```
processing/
├── review-required/   # AI・スクリプトが判断に迷ったもの → 人間が確認する
├── renamed/           # リネーム済みファイルの置き場
├── metadata-ready/    # metadata JSON 生成済みファイル
└── ocr-error/         # OCR 誤認識・文字化け疑いのあるもの
```

### review-required/
- category が不明なもの
- ファイル名が日付のみのもの
- ファイル名が異常に長いもの
- ファイル名の文字化け疑いがあるもの
- スクリプトが判断できなかったもの

**→ Claude Cowork または人間が確認してから次の処理へ進む**

### renamed/
- `scripts/rename_documents.py` で命名規約のファイル名を確定させたもの
- この段階ではまだ metadata が生成されていない場合がある

### metadata-ready/
- `scripts/generate_metadata.py` が `.metadata.json` を生成したもの
- PDF 本体と .metadata.json がペアで存在する状態

### ocr-error/
- ファイル名または内容に文字化け・OCR 誤認識が疑われるもの
- 内容を目視確認して正しいファイル名に修正してから renamed/ へ移動する

---

## 処理フロー（processing 内部）

```
inbox/
  |
  | process_inbox.py で分析（ファイルは動かさない）
  |
  +-- 文字化け疑い --------→ processing/ocr-error/   (レポートのみ)
  |
  +-- 要確認 ---------------→ processing/review-required/ (レポートのみ)
  |
  +-- 正常 ─ 手動でコピー → processing/renamed/
                              |
                              | generate_metadata.py
                              ↓
                         processing/metadata-ready/
                              |
                              | 人間による最終確認
                              ↓
                         export/  または  archive/
                              |
                              | 月次・手動
                              ↓
                           Dropbox
```

---

## export 後の注意

- `export/` に移動したファイルは月次処理時に Dropbox へ手動移動する
- 移動後は `export/` を空にする（`scripts/export_to_dropbox.py` 参照）
- Notion 登録が必要なものは別途 Notion に登録する

---

## 変更履歴

| 日付 | 内容 |
|---|---|
| 2026-05-17 | 初期作成 |
