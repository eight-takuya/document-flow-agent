# 命名規約 — Naming Convention

## 基本フォーマット

```
YYYYMMDD-Category-Document-Counterparty-AmountJPY-PaymentMethod.pdf
```

### 例

```
20260517-Tax-住民税通知.pdf
20260517-Insurance-自動車保険更新-SOMPO.pdf
20260517-Expense-会食-焼肉きんぐ-12000JPY-AMEX.pdf
20260517-Medical-診察費-山田クリニック-3500JPY-Cash.pdf
```

---

## フィールド定義

| フィールド | 必須 | 説明 |
|---|---|---|
| `YYYYMMDD` | 必須 | 書類の発行日・イベント日（西暦8桁） |
| `Category` | 必須 | 書類の大分類（`docs/categories.md` 参照） |
| `Document` | 必須 | 書類の種類・内容（日本語可） |
| `Counterparty` | 任意 | 発行元・支払先・相手先（日本語可） |
| `AmountJPY` | 任意 | 金額（例: `12000JPY`）|
| `PaymentMethod` | 任意 | 支払手段（`docs/payment-methods.md` 参照） |

---

## ルール

- **区切り文字は半角ハイフン** `-`（アンダースコアは使わない）
- **日付は YYYYMMDD** 形式（ハイフンなし8桁）
- **金額は数字 + JPY** の形式（例: `12000JPY`）。通貨記号 `¥` は使わない
- **支払手段は末尾**に記載する
- **拡張子は原則 `.pdf`**（OCR・PDF化後）
- **不明・不要な項目は省略可**。フィールド数は最小2つ（日付 + Category）から許容
- **ファイル名に使えない文字**（`/ \ : * ? " < > |` およびスペース）は削除または `-` に変換する
- **日本語はそのまま使用可**（ファイルシステム上で問題ない環境を前提）

---

## 最小形式と最大形式

```
# 最小（日付 + Category + Document のみ）
20260517-Tax-住民税通知.pdf

# 標準（Counterparty あり）
20260517-Insurance-自動車保険更新-SOMPO.pdf

# フル（全項目）
20260517-Expense-会食-焼肉きんぐ-12000JPY-AMEX.pdf
```

---

## inbox 内のファイルには適用しない

`inbox/` は自由な入口です。ここでの命名規約適用は不要です。  
命名規約は `processing/` でのリネーム時、または `archive/` / `export/` への移動時に適用します。

命名規約の適用は `scripts/rename_documents.py` が補助します。

---

## 変更履歴

| 日付 | 内容 |
|---|---|
| 2026-05-17 | 初期作成 |
