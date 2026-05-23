# metadata schema v1

Document Flow Agent の `.metadata.json` スキーマ定義。

**バージョン**: `v1`  
**作成日**: 2026-05-23  
**適用対象**: `processing/metadata-ready/*.metadata.json`

---

## 概要

metadata は以下の目的で使用します：

| 目的 | 使用フィールド |
|---|---|
| Notion DB 連携 | `category`, `document`, `counterparty`, `issue_date`, `amount_jpy`, `status`, `tags` |
| Dropbox 検索 | `source_file`, `file_name`, `category`, `issue_date`, `export_path` |
| discard 管理 | `discard_date`, `retention`, `status` |
| 月次整理 | `issue_date`, `category`, `export_path`, `archive_path` |
| 将来 RAG 検索 | `category`, `document`, `counterparty`, `issue_date`, `amount_jpy`, `tags`, `notes` |

---

## フィールド定義

### 必須フィールド

| フィールド | 型 | 説明 |
|---|---|---|
| `schema_version` | `string` | スキーマバージョン（`"v1"` 固定） |
| `file_name` | `string` | rename 後のファイル名（例: `20260523-Receipt-領収書-山手タクシー-300JPY.pdf`） |
| `source_file` | `string` | inbox での元ファイル名（例: `20260323_山手タクシー.jpg`） |
| `file_type` | `"PDF"` | 処理後は常に PDF |
| `original_extension` | `string` | 元ファイルの拡張子（例: `.jpg` `.pdf`） |
| `normalized_pdf` | `boolean` | 画像→PDF 変換が行われたか |
| `category` | `CategoryEnum` | 文書カテゴリ（下記 enum 参照） |
| `document` | `string` | 文書種別（category ごとに推奨値あり、下記参照） |
| `issue_date` | `string` | 書類の発行日 `YYYY-MM-DD` 形式（空文字=不明） |
| `status` | `StatusEnum` | 処理状態（下記 enum 参照） |
| `created_at` | `string` | metadata 生成日時 `YYYY-MM-DD HH:MM:SS` |

### 任意フィールド

| フィールド | 型 | 説明 |
|---|---|---|
| `counterparty` | `string` | 取引先・発行元（個人名・会社名）。住所・登録番号は除外 |
| `amount_jpy` | `integer \| null` | 金額（円）。不明の場合 `null` |
| `payment_method` | `PaymentMethodEnum` | 支払手段（空文字=不明） |
| `retention` | `string` | 保存期間（例: `"5年"`）。category から自動計算 |
| `discard_date` | `string` | 廃棄予定日 `YYYY-MM-DD`。`issue_date + retention` から計算 |
| `confidence` | `float \| null` | OCR 推定信頼度 `0.0〜1.0`。ファイル名由来の場合は `null` |
| `ocr_engine` | `string` | OCR エンジン（`"vision"` / `"filename"` / `"none"`） |
| `archive_path` | `string` | `archive/original-input/` 配下の相対パス |
| `export_path` | `string` | `export/files/` 配下の相対パス |
| `tags` | `string[]` | 自動生成タグ + 手動タグ（後述の Tags 仕様を参照） |
| `notion_registered` | `boolean` | Notion 登録済みか |
| `dropbox_exported` | `boolean` | Dropbox 転送済みか |
| `notes` | `string` | 補足メモ（自由記述） |
| `updated_at` | `string` | 最終更新日時 `YYYY-MM-DD HH:MM:SS` |

### 分割 PDF 専用フィールド（split_pdf が true の場合）

| フィールド | 型 | 説明 |
|---|---|---|
| `split_pdf` | `boolean` | 複数ページ PDF から分割された場合 `true` |
| `split_source` | `string` | 分割元の元ファイル名 |
| `split_page` | `integer` | 分割元の何ページ目か |
| `split_total` | `integer` | 分割元の総ページ数 |

---

## Category Enum

```
Receipt     領収書・レシート・タクシー領収書
Utility     水道・電気・ガスの使用量通知・料金案内
Finance     クレジットカード明細・口座引落・振込明細
Insurance   保険証・保険料通知・共済・確定拠出年金
School      学校関連・講師派遣・探究ゼミ・職業講演会
Government  行政証明書・登記・変更通知・組合員証
Medical     診療明細・処方箋・医療費
Work        業務完了通知・業務報告
Contract    見積書・請求書・発注書・納品書・契約書
Tax         住民税・所得税・固定資産税・課税通知
Other       上記に分類できないもの
```

---

## Document 推奨値（category ごと）

document が以下の推奨値に一致しない場合、validator は WARNING を出します。  
推奨値以外（自由記述）も許容されますが、Notion 連携・検索の精度が下がります。

### Receipt
- `領収書`
- `領収証`
- `レシート`
- `タクシー領収書`

### Utility
- `水道使用量のお知らせ`
- `水道料金案内`
- `水道料金領収証`
- `電気料金案内`
- `ガス料金案内`
- `使用量のお知らせ`

### Finance
- `クレジットカード明細`
- `ご利用明細`
- `引落通知`
- `振込明細`
- `口座明細`

### Insurance
- `保険証`
- `保険料納入告知額通知`
- `共済加入証書`
- `確定拠出年金掛金明細`
- `口座振替開始通知書`
- `保険更新通知`

### School
- `講師派遣依頼書`
- `探究ゼミ実施要項`
- `職業講演会講師依頼書`
- `Teams接続情報`
- `成績通知`

### Government
- `履歴事項全部証明書`
- `変更通知書`
- `適用事業所所在名称変更通知書`
- `交通反則通告制度案内`
- `組合員証`
- `保険証明書`

### Medical
- `診療明細書`
- `処方箋`
- `医療費領収書`

### Work
- `業務完了通知書`
- `業務報告書`

### Contract
- `御見積書`
- `請求書`
- `発注書`
- `納品書`
- `契約書`

### Tax
- `課税通知書`
- `納税通知書`
- `確定申告書`

### Other
推奨値なし（自由記述）

---

## Status Enum

| 値 | 説明 |
|---|---|
| `auto-approved` | OCR 信頼度 ≥85% で自動承認・自動 rename 済み |
| `renamed` | レビュー後に rename・metadata 生成済み |
| `document-unknown` | document が特定できなかった（旧 `[Document要確認]`） |
| `review-required` | 人間によるレビューが必要（日付不明など） |
| `ocr-error` | OCR 文字化けが検出された |
| `discarded` | 廃棄判断済み（inbox から削除） |
| `exported` | export/files/ へのコピー完了 |
| `pending` | 未処理 |

---

## PaymentMethod Enum

| 値 | 説明 |
|---|---|
| `Cash` | 現金 |
| `BankTransfer` | 振込 |
| `DirectDebit` | 口座振替 |
| `AMEX` | American Express |
| `SMBC` | 三井住友カード |
| `RakutenCard` | 楽天カード |
| `PayPay` | PayPay |
| `Suica` | Suica・交通系 IC |
| `Other` | その他 |
| `""` | 不明（空文字） |

---

## Retention（保存期間）

category ごとの法定・推奨保存期間。`discard_date = issue_date + retention` で自動計算。

| Category | 保存期間 | 根拠 |
|---|---|---|
| Tax | 7年 | 法人税法・所得税法 |
| Contract | 7年 | 商法・民法 |
| Work | 5年 | 業務委託契約 |
| Insurance | 5年 | 保険期間 + 余裕 |
| Government | 7年 | 行政書類 |
| Medical | 5年 | 医療費控除 |
| School | 3年 | 実用上の参照期間 |
| Finance | 5年 | カード明細・確定申告 |
| Receipt | 3年 | 一般領収書 |
| Utility | 3年 | 生活費管理 |
| Other | 3年 | デフォルト |

---

## サンプル（完全な v1 metadata）

```json
{
  "schema_version": "v1",
  "file_name": "20260420-Receipt-領収書-志太交通-2700JPY.pdf",
  "source_file": "20260420_志太交通（株）.jpg",
  "file_type": "PDF",
  "original_extension": ".jpg",
  "normalized_pdf": true,
  "category": "Receipt",
  "document": "領収書",
  "counterparty": "志太交通",
  "issue_date": "2026-04-20",
  "amount_jpy": 2700,
  "payment_method": "",
  "retention": "3年",
  "discard_date": "2029-04-20",
  "confidence": 0.95,
  "ocr_engine": "vision",
  "status": "auto-approved",
  "archive_path": "archive/original-input/202604/20260420_志太交通（株）.jpg",
  "export_path": "export/files/20260420-Receipt-領収書-志太交通-2700JPY.pdf",
  "tags": [],
  "notion_registered": false,
  "dropbox_exported": false,
  "notes": "",
  "created_at": "2026-05-23 17:16:46",
  "updated_at": "2026-05-23 17:16:46"
}
```

---

---

## Tags 仕様

### ルール

- 型: `list[str]`
- 重複禁止（`merge_tags` で重複排除）
- 空でも可（`[]`）だが、可能な限り自動生成する
- 日本語タグ中心・検索しやすい短い語
- `validate_metadata.py --fix` / `generate_metadata.py` が自動補完
- **既存タグは絶対に削除しない**（追加のみ）
- Notion 連携・Dropbox 検索・RAG 検索に使用

### 自動生成ロジック（scripts/tag_utils.py）

| 情報源 | 例 |
|---|---|
| category | `Receipt` → `領収証` / `Utility` → `公共料金` / `Finance` → `金融` |
| document | `クレジットカード明細` → `クレカ明細` / `領収書` → `支払証跡` |
| counterparty | `日本年金機構` → `年金` / `千葉県企業局` → `水道, 公共料金` |
| amount_jpy | `> 0` → `金額あり` / `≥ 100,000` → `高額` |
| payment_method | `AMEX/SMBC/RakutenCard` → `クレジットカード` / `Cash` → `現金` |
| retention | `7年` → `7年保管` / `5年` → `5年保管` |

### タグ一覧（自動生成されうるタグ）

**カテゴリ由来**
`領収証` / `公共料金` / `金融` / `保険` / `学校` / `行政` / `医療` / `業務` / `契約` / `税務` / `その他`

**文書・取引先由来**
`水道` / `電気` / `ガス` / `クレカ明細` / `口座明細` / `支払証跡` / `請求` / `見積` / `発注` / `契約書` / `納品` / `探究ゼミ` / `学校通知` / `業務完了` / `保険料` / `共済` / `確定拠出年金` / `口座振替` / `保険更新` / `登記` / `変更通知` / `証明書` / `医療費` / `処方` / `確定申告` / `課税通知`

**counterparty由来**
`年金` / `共済` / `浦安` / `東京都` / `健康保険` / `社会保険` / `教育` / `交通費` / `医療` / `小売` / `宿泊`

**金額・支払由来**
`金額あり` / `高額` / `現金` / `振込` / `口座振替` / `クレジットカード` / `電子マネー` / `交通系IC`

**保存期間由来**
`3年保管` / `5年保管` / `7年保管` / `10年保管` / `永久保存`

### サンプル

```json
{
  "tags": ["公共料金", "水道", "現金", "金額あり", "3年保管"]
}
```

```json
{
  "tags": ["保険", "保険料", "年金", "金額あり", "高額", "5年保管"]
}
```

```json
{
  "tags": ["領収証", "交通費", "支払証跡", "金額あり", "クレジットカード", "3年保管"]
}
```

---

## 変更履歴

| 日付 | バージョン | 内容 |
|---|---|---|
| 2026-05-23 | v1 | 初版。Finance カテゴリ追加、status enum 整備、document-unknown 分離、discard_date 自動計算 |
| 2026-05-23 | v1.1 | tags 自動生成機能追加（scripts/tag_utils.py）、Tags 仕様セクション追加 |
