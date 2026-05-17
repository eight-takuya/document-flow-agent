"""
rename_documents.py

命名規約に従ったファイル名を生成・検証する補助スクリプト。
命名規約: YYYYMMDD-Category-Document-Counterparty-AmountJPY-PaymentMethod.pdf
詳細は docs/naming-convention.md を参照。

実際のファイル移動は行わない。ファイル名の生成・検証のみ。
"""

import re
from pathlib import Path
from typing import Optional, Union

LOGS_DIR = Path(__file__).parent.parent / "logs"

UNSAFE_CHARS_PATTERN = re.compile(r'[/\\:*?"<>|\s]')
VALID_FILENAME_PATTERN = re.compile(r"^\d{8}-[A-Za-z]+-[^-].+\.pdf$")

CATEGORIES = {
    "Action", "Tax", "Insurance", "Medical", "School",
    "Contract", "Work", "Expense", "Receipt", "Utility", "Government",
    "Family", "Asset", "Other",
}

PAYMENT_METHODS = {
    "AMEX", "SMBC", "RakutenCard", "PayPay",
    "Cash", "BankTransfer", "DirectDebit", "Other",
}


def sanitize(text: str) -> str:
    """ファイル名に使用できない文字をハイフンに置換し、連続ハイフンを整理する。"""
    sanitized = UNSAFE_CHARS_PATTERN.sub("-", text)
    sanitized = re.sub(r"-{2,}", "-", sanitized)
    return sanitized.strip("-")


def format_amount(amount_jpy: Union[int, float]) -> str:
    """金額を AmountJPY 形式に整形する（例: 12000 → '12000JPY'）。"""
    return f"{int(amount_jpy)}JPY"


def build_filename(
    date: str,
    category: str,
    document: str,
    counterparty: Optional[str] = None,
    amount_jpy: Optional[Union[int, float]] = None,
    payment_method: Optional[str] = None,
) -> str:
    """
    命名規約に従ったファイル名を生成する。

    Args:
        date:           発行日・イベント日（YYYYMMDD 形式）
        category:       書類の大分類（docs/categories.md 参照）
        document:       書類の種類・内容
        counterparty:   発行元・支払先（省略可）
        amount_jpy:     金額（省略可）
        payment_method: 支払手段（省略可）

    Returns:
        生成されたファイル名（例: 20260517-Expense-会食-焼肉きんぐ-12000JPY-AMEX.pdf）
    """
    parts = [
        sanitize(date),
        sanitize(category),
        sanitize(document),
    ]

    if counterparty:
        parts.append(sanitize(counterparty))

    if amount_jpy is not None:
        parts.append(format_amount(amount_jpy))

    if payment_method:
        parts.append(sanitize(payment_method))

    return "-".join(parts) + ".pdf"


def validate_filename(filename: str) -> bool:
    """生成されたファイル名が命名規約の基本パターンに適合するか検証する。"""
    return bool(VALID_FILENAME_PATTERN.match(filename))


def validate_category(category: str) -> bool:
    return category in CATEGORIES


def validate_payment_method(method: str) -> bool:
    return method in PAYMENT_METHODS


if __name__ == "__main__":
    examples = [
        {
            "date": "20260517",
            "category": "Tax",
            "document": "住民税通知",
        },
        {
            "date": "20260517",
            "category": "Insurance",
            "document": "自動車保険更新",
            "counterparty": "SOMPO",
        },
        {
            "date": "20260517",
            "category": "Expense",
            "document": "会食",
            "counterparty": "焼肉きんぐ",
            "amount_jpy": 12000,
            "payment_method": "AMEX",
        },
        {
            "date": "20260517",
            "category": "Medical",
            "document": "診察費",
            "counterparty": "山田クリニック",
            "amount_jpy": 3500,
            "payment_method": "Cash",
        },
    ]

    print("=== rename_documents.py — filename generation examples ===")
    print()
    for kwargs in examples:
        filename = build_filename(**kwargs)
        is_valid = validate_filename(filename)
        status = "OK" if is_valid else "INVALID"
        print(f"  [{status}] {filename}")
    print()
    print("See docs/naming-convention.md for the full specification.")
