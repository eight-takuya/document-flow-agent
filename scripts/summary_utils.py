"""
summary_utils.py

metadata dict から文書サマリー（1〜2文、日本語）を自動生成するユーティリティ。
LLM API は使用せず、metadata フィールドをテンプレートに当てはめて生成する。

generate_metadata.py / validate_metadata.py から呼び出される。

Usage:
    from summary_utils import generate_summary

    summary = generate_summary(metadata)
    # 例: "千葉県企業局による水道料金領収証。2025年5月20日発行、金額は14,762円、支払方法は現金。"
"""

import re
from typing import Optional

# ---------------------------------------------------------------------------
# 表記変換テーブル
# ---------------------------------------------------------------------------

#: payment_method → 日本語表記
PAYMENT_METHOD_JA: dict[str, str] = {
    "Cash":         "現金",
    "BankTransfer": "振込",
    "DirectDebit":  "口座振替",
    "AMEX":         "クレジットカード",
    "SMBC":         "クレジットカード",
    "RakutenCard":  "クレジットカード",
    "PayPay":       "PayPay",
    "Suica":        "交通系IC",
    "Other":        "その他",
    "":             "",
}

#: category → 日本語説明（文末に使う）
CATEGORY_DESC_JA: dict[str, str] = {
    "Receipt":    "支払関連書類",
    "Utility":    "公共料金関連書類",
    "Finance":    "金融関連書類",
    "Insurance":  "保険関連書類",
    "School":     "学校・教育関連書類",
    "Government": "行政関連書類",
    "Medical":    "医療関連書類",
    "Work":       "業務関連書類",
    "Contract":   "契約関連書類",
    "Tax":        "税務関連書類",
    "Other":      "書類",
}


# ---------------------------------------------------------------------------
# 日付フォーマット
# ---------------------------------------------------------------------------

def _format_date(issue_date: str) -> str:
    """
    YYYY-MM-DD → YYYY年M月D日 に変換する。
    変換できない場合は空文字を返す。
    """
    if not issue_date:
        return ""
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", issue_date)
    if not m:
        return ""
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    return f"{y}年{mo}月{d}日"


def _format_amount(amount_jpy) -> str:
    """
    金額を「14,762円」形式に変換する。None の場合は空文字。
    """
    if amount_jpy is None:
        return ""
    try:
        return f"{int(amount_jpy):,}円"
    except (ValueError, TypeError):
        return ""


def _clean(text: str) -> str:
    """
    二重句読点・末尾の余分な句読点・空白を除去する。
    """
    # 複数の「。」を一つに
    text = re.sub(r"。{2,}", "。", text)
    # 「、。」や「，。」のような連続を修正
    text = re.sub(r"[、，]\s*。", "。", text)
    # 先頭・末尾の空白
    text = text.strip()
    # 末尾が「。」でない場合は追加
    if text and not text.endswith("。"):
        text += "。"
    return text


# ---------------------------------------------------------------------------
# category 別テンプレート生成
# ---------------------------------------------------------------------------

def _build_core(
    category: str,
    document: str,
    counterparty: str,
    date_ja: str,
    amount_str: str,
    payment_ja: str,
) -> str:
    """
    category に応じたテンプレートでコア文を生成する。
    """
    doc  = document    or "関連書類"
    cp   = counterparty or ""
    cat_desc = CATEGORY_DESC_JA.get(category, "書類")

    # --- Receipt ---
    if category == "Receipt":
        if cp and amount_str and payment_ja:
            return f"{cp}の{doc}。{date_ja}発行、金額は{amount_str}、支払方法は{payment_ja}。"
        if cp and amount_str:
            return f"{cp}の{doc}。{date_ja}発行、金額は{amount_str}。"
        if cp:
            return f"{cp}の{doc}。{date_ja}発行。"
        if amount_str:
            return f"{doc}。{date_ja}発行、金額は{amount_str}。"
        return f"{doc}。{date_ja}発行。"

    # --- Utility ---
    if category == "Utility":
        if cp and amount_str and payment_ja:
            return (
                f"{cp}による{doc}。"
                f"{date_ja}発行、金額は{amount_str}、支払方法は{payment_ja}。"
            )
        if cp and amount_str:
            return f"{cp}による{doc}。{date_ja}発行、金額は{amount_str}。"
        if cp:
            return f"{cp}による{doc}。{date_ja}発行。"
        return f"{doc}。{date_ja}発行。"

    # --- Finance ---
    if category == "Finance":
        base = f"{cp}に関する{doc}。" if cp else f"{doc}。"
        return f"{base}{date_ja}発行、{cat_desc}として保管。"

    # --- Insurance ---
    if category == "Insurance":
        if cp and amount_str:
            return (
                f"{cp}に関する{doc}。"
                f"{date_ja}発行、金額は{amount_str}、{cat_desc}として保管。"
            )
        base = f"{cp}に関する{doc}。" if cp else f"{doc}。"
        return f"{base}{date_ja}発行、{cat_desc}として保管。"

    # --- School ---
    if category == "School":
        base = f"{cp}に関する{doc}。" if cp else f"{doc}。"
        return f"{base}{date_ja}発行、{cat_desc}として保管。"

    # --- Government ---
    if category == "Government":
        if cp:
            return f"{cp}による{doc}。{date_ja}発行、{cat_desc}として保管。"
        return f"{doc}。{date_ja}発行、{cat_desc}として保管。"

    # --- Medical ---
    if category == "Medical":
        if cp and amount_str:
            return (
                f"{cp}による{doc}。"
                f"{date_ja}発行、金額は{amount_str}、{cat_desc}として保管。"
            )
        if cp:
            return f"{cp}による{doc}。{date_ja}発行、{cat_desc}として保管。"
        return f"{doc}。{date_ja}発行、{cat_desc}として保管。"

    # --- Work ---
    if category == "Work":
        base = f"{cp}に関する{doc}。" if cp else f"{doc}。"
        return f"{base}{date_ja}発行、{cat_desc}として保管。"

    # --- Contract ---
    if category == "Contract":
        if cp and amount_str:
            return (
                f"{cp}に関する{doc}。"
                f"{date_ja}発行、金額は{amount_str}、{cat_desc}として保管。"
            )
        base = f"{cp}に関する{doc}。" if cp else f"{doc}。"
        return f"{base}{date_ja}発行、{cat_desc}として保管。"

    # --- Tax ---
    if category == "Tax":
        if cp and amount_str:
            return f"{cp}からの{doc}。{date_ja}発行、金額は{amount_str}、{cat_desc}として保管。"
        base = f"{cp}からの{doc}。" if cp else f"{doc}。"
        return f"{base}{date_ja}発行、{cat_desc}として保管。"

    # --- Other / fallback ---
    if cp:
        return f"{cp}に関する{doc}。{date_ja}発行。分類未確定のため内容確認を推奨。"
    return f"{doc}。{date_ja}発行。分類未確定のため内容確認を推奨。"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_summary(metadata: dict) -> str:
    """
    metadata dict から文書サマリーを生成して返す（1〜2文、日本語）。

    LLM を使わず、metadata フィールドのテンプレート埋め込みで生成する。
    空フィールドは自然に省略される。

    Args:
        metadata: metadata dict（schema v1 形式）

    Returns:
        サマリー文字列（80〜160文字程度）。生成不可の場合は空文字。
    """
    category       = str(metadata.get("category") or "Other")
    document       = str(metadata.get("document") or "").strip()
    counterparty   = str(metadata.get("counterparty") or "").strip()
    issue_date     = str(metadata.get("issue_date") or "").strip()
    amount_jpy     = metadata.get("amount_jpy")
    payment_method = str(metadata.get("payment_method") or "").strip()

    # 日付フォーマット
    date_ja    = _format_date(issue_date)
    amount_str = _format_amount(amount_jpy)
    payment_ja = PAYMENT_METHOD_JA.get(payment_method, payment_method)

    # 最低限の情報がない場合は空文字
    if not document and not counterparty and not date_ja:
        return ""

    raw = _build_core(category, document, counterparty, date_ja, amount_str, payment_ja)
    return _clean(raw)
