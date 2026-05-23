"""
tag_utils.py

metadata dict から tags を自動生成するユーティリティ。
generate_metadata.py / validate_metadata.py から呼び出される。

将来の Notion連携・Dropbox検索・自然言語検索・RAG検索に備えて、
文書の意味タグを安定して付与することが目的です。

Usage（外部から呼ぶ場合）:
    from tag_utils import generate_tags, merge_tags

    auto_tags = generate_tags(metadata)
    metadata["tags"] = merge_tags(metadata.get("tags", []), auto_tags)
"""

from typing import List, Set


# ---------------------------------------------------------------------------
# Category → tag
# ---------------------------------------------------------------------------

#: category 値から生成される固定タグ
CATEGORY_TAGS: dict[str, List[str]] = {
    "Receipt":    ["領収証"],
    "Utility":    ["公共料金"],
    "Finance":    ["金融"],
    "Insurance":  ["保険"],
    "School":     ["学校"],
    "Government": ["行政"],
    "Medical":    ["医療"],
    "Work":       ["業務"],
    "Contract":   ["契約"],
    "Tax":        ["税務"],
    "Other":      ["その他"],
}


# ---------------------------------------------------------------------------
# Document keyword → tag（部分一致）
# ---------------------------------------------------------------------------

#: (マッチキーワードリスト, 付与タグリスト) のペア
DOCUMENT_TAG_RULES: List[tuple] = [
    # 公共料金
    (["水道料金", "水道使用量", "水道料金案内", "水道料金領収証", "水道使用量のお知らせ"], ["水道"]),
    (["電気料金", "電気料金案内"], ["電気"]),
    (["ガス料金", "ガス料金案内"], ["ガス"]),
    # 金融
    (["クレジットカード明細", "ご利用明細", "ご利用代金明細書"], ["クレカ明細"]),
    (["引落通知", "口座明細", "振込明細"], ["口座明細"]),
    # 領収証系
    (["領収書", "領収証", "タクシー領収書"], ["支払証跡"]),
    # 契約書系
    (["請求書"], ["請求"]),
    (["御見積書", "見積書"], ["見積"]),
    (["発注書"], ["発注"]),
    (["契約書"], ["契約書"]),
    (["納品書"], ["納品"]),
    # 学校・教育
    (["成績通知"], ["学校通知"]),
    (["講師派遣依頼書", "職業講演会講師依頼書", "探究ゼミ実施要項", "職業講演会"], ["探究ゼミ"]),
    # 業務
    (["業務完了通知書", "業務報告書"], ["業務完了"]),
    # 保険
    (["保険料納入告知額通知", "保険料納入告知額"], ["保険料"]),
    (["共済加入証書", "共済"], ["共済"]),
    (["確定拠出年金掛金明細"], ["確定拠出年金"]),
    (["口座振替開始通知書"], ["口座振替"]),
    (["保険更新通知"], ["保険更新"]),
    # 行政
    (["履歴事項全部証明書"], ["登記"]),
    (["変更通知書", "適用事業所所在名称変更通知書"], ["変更通知"]),
    (["組合員証", "保険証明書"], ["証明書"]),
    # 医療
    (["診療明細書", "医療費領収書"], ["医療費"]),
    (["処方箋"], ["処方"]),
    # 税務
    (["確定申告書"], ["確定申告"]),
    (["課税通知書", "納税通知書"], ["課税通知"]),
]


# ---------------------------------------------------------------------------
# Counterparty keyword → tag（部分一致）
# ---------------------------------------------------------------------------

#: (マッチキーワードリスト, 付与タグリスト) のペア
COUNTERPARTY_TAG_RULES: List[tuple] = [
    # 公共・行政
    (["千葉県企業局"],            ["水道", "公共料金"]),
    (["日本年金機構"],            ["年金"]),
    (["千葉県民共済"],            ["共済"]),
    (["浦安市"],                  ["浦安"]),
    (["東京都"],                  ["東京都"]),
    (["国民健康保険"],            ["健康保険"]),
    (["社会保険"],                ["社会保険"]),
    # 学校・教育機関
    (["小学校", "中学校", "高校", "高等学校", "大学", "学校", "教育委員会"], ["教育"]),
    # 交通系
    (["タクシー", "個人タクシー", "交通", "鉄道", "バス",
      "JR", "東海旅客鉄道", "山手タクシー", "志太交通",
      "交栄個人タクシー", "両毛自動車", "松村運輸"],             ["交通費"]),
    # 医療系
    (["病院", "クリニック", "医院", "薬局", "歯科"],            ["医療"]),
    # 小売・コンビニ
    (["コストコ", "イオン", "セブン", "ローソン", "ファミリーマート"], ["小売"]),
    # ホテル・宿泊
    (["ホテル", "旅館", "カンデオ", "ホスピタリティ"],           ["宿泊"]),
]


# ---------------------------------------------------------------------------
# payment_method → tag
# ---------------------------------------------------------------------------

#: payment_method enum → タグリスト
PAYMENT_METHOD_TAGS: dict[str, List[str]] = {
    "Cash":         ["現金"],
    "BankTransfer": ["振込"],
    "DirectDebit":  ["口座振替"],
    "AMEX":         ["クレジットカード"],
    "SMBC":         ["クレジットカード"],
    "RakutenCard":  ["クレジットカード"],
    "PayPay":       ["電子マネー"],
    "Suica":        ["電子マネー", "交通系IC"],
    "Other":        [],
    "":             [],
}


# ---------------------------------------------------------------------------
# Retention → tag
# ---------------------------------------------------------------------------

#: retention 文字列 → タグリスト
RETENTION_TAGS: dict[str, List[str]] = {
    "7年":  ["7年保管"],
    "5年":  ["5年保管"],
    "3年":  ["3年保管"],
    "10年": ["10年保管"],
    "永久": ["永久保存"],
}


# ---------------------------------------------------------------------------
# Main function
# ---------------------------------------------------------------------------

def generate_tags(metadata: dict) -> List[str]:
    """
    metadata dict から自動タグリストを生成して返す。

    - 重複排除済み・ソート済み
    - 既存の tags は考慮しない（呼び出し元で merge_tags を使ってマージすること）

    Args:
        metadata: metadata dict（schema v1 形式）

    Returns:
        自動生成タグのリスト（日本語・ソート済み）
    """
    tags: Set[str] = set()

    category       = str(metadata.get("category") or "")
    document       = str(metadata.get("document") or "")
    counterparty   = str(metadata.get("counterparty") or "")
    amount_jpy     = metadata.get("amount_jpy")
    payment_method = str(metadata.get("payment_method") or "")
    retention      = str(metadata.get("retention") or "")

    # --- category → tag ---
    for tag in CATEGORY_TAGS.get(category, []):
        tags.add(tag)

    # --- document → tag（部分一致）---
    for keywords, doc_tags in DOCUMENT_TAG_RULES:
        if document and any(kw in document for kw in keywords):
            tags.update(doc_tags)

    # --- counterparty → tag（部分一致）---
    for keywords, cp_tags in COUNTERPARTY_TAG_RULES:
        if counterparty and any(kw in counterparty for kw in keywords):
            tags.update(cp_tags)

    # --- amount → tag ---
    if isinstance(amount_jpy, (int, float)) and amount_jpy > 0:
        tags.add("金額あり")
        if amount_jpy >= 100_000:
            tags.add("高額")

    # --- payment_method → tag ---
    for tag in PAYMENT_METHOD_TAGS.get(payment_method, []):
        tags.add(tag)

    # --- retention → tag ---
    for tag in RETENTION_TAGS.get(retention, []):
        tags.add(tag)

    return sorted(tags)


def merge_tags(existing: List[str], generated: List[str]) -> List[str]:
    """
    既存タグと自動生成タグをマージする。

    - 既存タグを先頭に保持（順序を崩さない）
    - 重複排除（既存にあるタグは再追加しない）
    - 既存タグは絶対に削除しない

    Args:
        existing:  現在の tags リスト
        generated: generate_tags() の結果

    Returns:
        マージ済みタグリスト
    """
    existing_set = set(existing)
    merged = list(existing)
    for tag in generated:
        if tag not in existing_set:
            merged.append(tag)
            existing_set.add(tag)
    return merged
