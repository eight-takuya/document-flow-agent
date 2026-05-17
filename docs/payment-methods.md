# Payment Method 一覧

ファイル命名規約の `PaymentMethod` フィールドで使用できる支払手段の一覧です。

命名規約の詳細は `docs/naming-convention.md` を参照してください。

---

## 一覧

| PaymentMethod | 説明 |
|---|---|
| `AMEX` | American Express カード |
| `SMBC` | 三井住友銀行カード（クレジット・デビット） |
| `RakutenCard` | 楽天カード |
| `PayPay` | PayPay（QR コード決済） |
| `Cash` | 現金 |
| `BankTransfer` | 銀行振込 |
| `DirectDebit` | 口座振替（自動引き落とし） |
| `Other` | 上記以外の支払手段 |

---

## 運用上の注意

- `PaymentMethod` は省略可。支払手段が不明・不要な書類には記載しない
- カード名は略称で統一する（例: `AmericanExpress` ではなく `AMEX`）
- 新しいカード・決済手段が増えた場合はこのファイルに追記する

---

## 変更履歴

| 日付 | 内容 |
|---|---|
| 2026-05-17 | 初期作成 |
