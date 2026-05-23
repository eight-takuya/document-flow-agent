"""
ocr_extract.py

macOS Vision Framework (Swift) を使った PDF/画像 OCR と、
OCR テキストからの rename フィールド推定モジュール。

依存: swiftc (macOS 標準), sips (macOS 標準)
外部 pip パッケージは不要。
"""

import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

SCRIPTS_DIR = Path(__file__).parent
SWIFT_SOURCE = SCRIPTS_DIR / "vision_ocr.swift"
OCR_BINARY = SCRIPTS_DIR / "vision_ocr"

# ---------------------------------------------------------------------------
# Category keyword mapping (優先度順)
# ---------------------------------------------------------------------------
CATEGORY_KEYWORDS: List[tuple] = [
    ("Work",       ["業務完了通知書", "完了通知書", "作業完了", "業務報告", "業務委託"]),
    ("Contract",   ["御見積書", "見積書", "発注書", "請求書", "納品書", "契約書"]),
    ("Government", ["履歴事項全部証明書", "証明書", "変更通知書", "通告制度",
                    "登記", "行政", "許可証", "所在名称変更", "適用事業所"]),
    ("Tax",        ["住民税", "所得税", "固定資産税", "課税通知", "確定申告", "納税通知"]),
    # Insurance: 社会保険・生命保険・共済を含む。「保険料」は確認票・告知書で多用するため追加
    ("Insurance",  ["保険証", "保険料納入告知", "被保険者", "共済加入", "健康保険・厚生年金",
                    "口座振替開始通知", "年金事務所", "日本年金機構"]),
    ("Medical",    ["診療明細書", "診療", "処方箋", "クリニック", "病院", "医療費"]),
    # School: 探究ゼミ・講師派遣・職業講演会を追加
    ("School",     ["成績", "通知表", "学校", "入学", "授業料",
                    "探究ゼミ", "講師派遣", "職業講演会", "浦安高等学校", "浦安中学校"]),
    ("Utility",    ["使用水量", "水道料金", "電気料金", "ガス料金", "通信費", "下水道"]),
    # Finance: クレジットカード明細・利用明細
    ("Finance",    ["カード会社", "CARD COMPANY", "ご利用明細", "クレジットカード",
                    "会員番号", "ご利用代金", "請求金額", "お支払い金額"]),
    # Receipt: レシート・領収書・タクシー・交通費領収書を含む
    ("Receipt",    ["領収書", "レシート", "領収証",
                    "タクシー", "個人タクシー", "ハイヤー"]),
    ("Other",      []),  # fallback
]

# ---------------------------------------------------------------------------
# 有効な年の範囲（日付バリデーション）
# ---------------------------------------------------------------------------
VALID_YEAR_MIN = 1900
VALID_YEAR_MAX = 2099

# ---------------------------------------------------------------------------
# OCR 誤認識テキスト置換マップ
# ---------------------------------------------------------------------------
OCR_REPLACE_MAP: List[Tuple[str, str]] = [
    # ホテル名
    ("カン夕オ",           "カンデオ"),
    ("カンダオ",           "カンデオ"),
    ("カンデォ",           "カンデオ"),
    ("カスピタリティ",     "ホスピタリティ"),
    ("マコジメント",       "マネジメント"),
    ("マヨジント",         "マネジメント"),
    ("マネジュメント",     "マネジメント"),
    # タクシー組合
    ("日循漣",             "日個連"),
    ("日衞連",             "日個連"),
    ("日偲連",             "日個連"),
    # コストコ
    ("木ールセール",       "ホールセール"),
    ("コールセール",       "ホールセール"),
    # 役職名
    ("代表取締後",         "代表取締役"),
    ("代表取締按",         "代表取締役"),
]

# ---------------------------------------------------------------------------
# document blocklist（無意味な文書名を除外）
# ---------------------------------------------------------------------------
DOCUMENT_BLOCKLIST = {
    "001", "002", "003", "004", "005", "006", "007", "008", "009",
    "株式会社", "有限会社", "合同会社", "",
}

# ---------------------------------------------------------------------------
# counterparty ブロック: 住所・登録番号・QR 由来パターン
# ---------------------------------------------------------------------------
_ADDRESS_PATTERN = re.compile(
    r"(〒\d{3}[-－]\d{4}"          # 郵便番号
    r"|\d+丁目|\d+番地|番[0-9]|号室"  # 番地・丁目・号室
    r"|[-－]\d{1,4}[-－]\d{1,4}"   # 住所番地ハイフン連続
    r"|[0-9]{1,2}[－−-][0-9]{1,2}[－−-][0-9]{1,2}"  # X-Y-Z 形式
    r"|浦安市[^\s]|江東区[^\s])"    # 具体的な住所地名（直後に文字が続く場合のみ）
)
_REGISTRATION_PATTERN = re.compile(
    r"(登録番号|T\d{13}|法人番号|\d{13}|作成地[：:])"
)
_URL_PATTERN = re.compile(
    r"(https?://|www\.|\.co\.jp|\.com|\.jp)"
)

# ---------------------------------------------------------------------------
# 日本語元号 → 西暦変換
# ---------------------------------------------------------------------------
ERA_TABLE = {
    "令和": 2018,
    "平成": 1988,
    "昭和": 1925,
    "大正": 1911,
}

DATE_PATTERNS = [
    re.compile(r"(令和|平成|昭和|大正)(\d{1,2})年\s*(\d{1,2})月\s*(\d{1,2})日"),
    re.compile(r"(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日"),
    re.compile(r"(\d{4})/(\d{1,2})/(\d{1,2})"),
    re.compile(r"(\d{4})-(\d{2})-(\d{2})"),
]

AMOUNT_PATTERN = re.compile(r"(\d{1,3}(?:,\d{3})*)\s*円")
AMOUNT_YEN_PATTERN = re.compile(r"¥\s*(\d{1,3}(?:,\d{3})*)")
# OCR が「,」を「.」と誤認識した場合の補足パターン（例: ¥232.814円 → 232814）
AMOUNT_YEN_PERIOD_PATTERN = re.compile(r"¥\s*(\d{1,3})\.(\d{3})\s*円")
# 「金額」ラベル直後の数値（郵便局払込控などで「円」が別行の場合）
AMOUNT_LABEL_PATTERN = re.compile(r"金額\s*\n\s*(\d{1,3}(?:,\d{3})*)")

COMPANY_PATTERNS = [
    re.compile(r"株式会社[\s　]*([\w぀-鿿＀-￯]+)"),
    re.compile(r"([\w぀-鿿＀-￯]+)[\s　]*株式会社"),
    re.compile(r"合同会社[\s　]*([\w぀-鿿＀-￯]+)"),
]

# 都道府県企業局・市区町村水道局検出パターン
# 「加入者名千葉県企業局」のようなラベル+機関名にも対応: (?:...名)? で任意のラベルを読み飛ばす
_GOVT_ENTITY_PATTERNS = [
    re.compile(r"(?:[\w぀-鿿＀-￯]+名)?([\w぀-鿿＀-￯]{1,3}(?:県|都|府|道)企業局)"),
    re.compile(r"(?:[\w぀-鿿＀-￯]+名)?([\w぀-鿿＀-￯]{1,5}(?:市|区|町|村)(?:上下水道局|水道局|下水道局))"),
]

# counterparty 誤検知を防ぐブロックリスト（OCR ゴミテキストを除外）
COUNTERPARTY_BLOCKLIST = [
    "登録商標", "QRコード", "コピーライト", "copyright", "Copyright",
    "無断複製", "無断転載", "All Rights", "registered",
    "会社法人等番号",   # 履歴事項全部証明書でフィールドラベルが誤検知される
    "代表取締役",       # 役職名そのものは取引先ではない
    "代表取締後",       # OCR 誤認識版
    "登録番号",         # T始まり登録番号
    "会員番号",         # クレカ会員番号ラベル
    "作成地",           # 「作成地：○○」形式
    "取引日時",         # レシートの取引日時ラベル
    "会社名",           # クレカ明細のフィールドラベル
]

# ファイル名に含まれる支払手段キーワード → 正規化名
PAYMENT_METHOD_FROM_FILENAME: List[tuple] = [
    ("AMEX", "AMEX"),
    ("SMBC", "SMBC"),
    ("PayPay", "PayPay"),
    ("RakutenCard", "RakutenCard"),
    ("楽天カード", "RakutenCard"),
    ("BankTransfer", "BankTransfer"),
    ("振込", "BankTransfer"),
    ("DirectDebit", "DirectDebit"),
    ("口座振替", "DirectDebit"),
    ("Cash", "Cash"),
    ("現金", "Cash"),
]


# ---------------------------------------------------------------------------
# OCR binary management
# ---------------------------------------------------------------------------

def ensure_ocr_binary() -> bool:
    """Swift OCR バイナリが存在しなければコンパイルする。利用可否を返す。"""
    if OCR_BINARY.exists():
        return True
    if not SWIFT_SOURCE.exists():
        return False
    result = subprocess.run(
        ["swiftc", str(SWIFT_SOURCE), "-o", str(OCR_BINARY)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return False
    return OCR_BINARY.exists()


def _run_vision_ocr(image_path: Path) -> str:
    """Vision OCR バイナリを実行してテキストを返す。"""
    result = subprocess.run(
        [str(OCR_BINARY), str(image_path)],
        capture_output=True, text=True, timeout=30,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _pdf_first_page_to_image(pdf_path: Path) -> Optional[Path]:
    """sips を使って PDF の1ページ目を JPEG に変換する。"""
    tmp = Path(tempfile.mktemp(suffix=".jpg"))
    result = subprocess.run(
        ["sips", "-s", "format", "jpeg", str(pdf_path), "--out", str(tmp)],
        capture_output=True, text=True,
    )
    if result.returncode == 0 and tmp.exists():
        return tmp
    return None


def extract_text(file_path: Path) -> str:
    """
    PDF または画像ファイルから OCR テキストを抽出する。

    Returns:
        抽出テキスト。OCR 不可の場合は空文字。
    """
    if not ensure_ocr_binary():
        return ""

    ext = file_path.suffix.lower()
    try:
        if ext == ".pdf":
            img = _pdf_first_page_to_image(file_path)
            if img:
                text = _run_vision_ocr(img)
                img.unlink(missing_ok=True)
                return text
        elif ext in {".png", ".jpg", ".jpeg"}:
            return _run_vision_ocr(file_path)
    except Exception:
        pass
    return ""


# ---------------------------------------------------------------------------
# Heuristic parsing of OCR text
# ---------------------------------------------------------------------------

def _is_valid_year(year: int) -> bool:
    """年が有効な範囲（1900〜2099）かどうかを返す。"""
    return VALID_YEAR_MIN <= year <= VALID_YEAR_MAX


def _extract_date(text: str, fallback_filename: str) -> str:
    """
    OCR テキストから日付を抽出し YYYYMMDD 形式で返す。
    年が 1900〜2099 の範囲外の場合は無効とし次のパターンへ。
    すべて無効な場合はファイル名先頭8桁にフォールバック
    （ファイル名日付も年バリデーションを行う）。
    """
    for pat in DATE_PATTERNS:
        m = pat.search(text)
        if m:
            groups = m.groups()
            if len(groups) == 4:
                era, year_n, month, day = groups
                base = ERA_TABLE.get(era, 0)
                year = base + int(year_n)
            elif len(groups) == 3:
                year, month, day = groups
                year = int(year)
            else:
                continue
            try:
                year_int = int(year)
                if not _is_valid_year(year_int):
                    continue  # 1900-2099 範囲外はスキップ
                return f"{year_int:04d}{int(month):02d}{int(day):02d}"
            except (ValueError, TypeError):
                continue

    # filename の先頭8桁にフォールバック（年バリデーションあり）
    m = re.match(r"^(\d{8})", fallback_filename)
    if m:
        date_str = m.group(1)
        fn_year = int(date_str[:4])
        if _is_valid_year(fn_year):
            return date_str
    return ""


def _extract_category(text: str) -> str:
    """キーワードマッピングで Category を推定する。"""
    for category, keywords in CATEGORY_KEYWORDS:
        for kw in keywords:
            if kw in text:
                return category
    return "Other"


def _is_counterparty_blocked(name: str) -> bool:
    """
    ブロックリストに含まれる OCR ゴミテキストを弾く。
    住所・登録番号・URL パターンも除外する。
    """
    if any(blocked in name for blocked in COUNTERPARTY_BLOCKLIST):
        return True
    if _ADDRESS_PATTERN.search(name):
        return True
    if _REGISTRATION_PATTERN.search(name):
        return True
    if _URL_PATTERN.search(name):
        return True
    return False


def _apply_ocr_replace_map(text: str) -> str:
    """OCR 誤認識テキストを正しい表記に置換する。"""
    for wrong, correct in OCR_REPLACE_MAP:
        text = text.replace(wrong, correct)
    return text


def _extract_govt_entity(text: str) -> str:
    """
    都道府県企業局・市区町村水道局を OCR テキストから抽出する。
    「加入者名千葉県企業局」のようなラベル付き表記でも group(1) で機関名のみ取得できる。
    """
    for pat in _GOVT_ENTITY_PATTERNS:
        m = pat.search(text)
        if m and m.group(1):
            return m.group(1)
    return ""


def _extract_counterparty(text: str, bracket_tags: List[str]) -> str:
    """
    OCR テキストから発行元・取引先を推定する。
    括弧タグがあればそちらを優先。
    """
    if bracket_tags:
        return bracket_tags[0]

    for pat in COMPANY_PATTERNS:
        m = pat.search(text)
        if m:
            name = m.group(1).strip()
            if 1 < len(name) < 20 and not _is_counterparty_blocked(name):
                return name

    # 都道府県企業局・水道局（水道料金など公的機関）
    govt = _extract_govt_entity(text)
    if govt:
        return govt

    # 「御中」の直前の行を相手先と見なす
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if "御中" in line and i > 0:
            candidate = lines[i - 1].strip()
            candidate = re.sub(r"株式会社|合同会社|有限会社", "", candidate).strip()
            if 1 < len(candidate) < 20 and not _is_counterparty_blocked(candidate):
                return candidate

    return ""


def _extract_amount(text: str) -> Optional[int]:
    """OCR テキストから金額（円）を抽出する。最大値を返す。"""
    amounts = []
    # OCR で「,」→「.」誤認識のパターンを最初にチェック（例: ¥232.814円 → 232814）
    for m in AMOUNT_YEN_PERIOD_PATTERN.finditer(text):
        try:
            val = int(m.group(1) + m.group(2))  # 上位3桁 + 下位3桁を結合
            if val > 0:
                amounts.append(val)
        except ValueError:
            pass
    for pat in [AMOUNT_PATTERN, AMOUNT_YEN_PATTERN, AMOUNT_LABEL_PATTERN]:
        for m in pat.finditer(text):
            try:
                val = int(m.group(1).replace(",", ""))
                if val > 0:
                    amounts.append(val)
            except ValueError:
                pass
    return max(amounts) if amounts else None


def _extract_document_name(text: str, category: str) -> str:
    """カテゴリに関連する文書名キーワードを OCR テキストから探す。"""
    doc_keywords = {
        "Work": ["業務完了通知書", "完了通知書", "業務報告書"],
        "Contract": ["御見積書", "見積書", "請求書", "発注書", "納品書"],
        "Government": ["履歴事項全部証明書", "変更通知書", "適用事業所所在名称変更通知書",
                       "交通反則通告制度案内"],
        "Tax": ["住民税通知書", "課税通知書", "納税通知書"],
        "Insurance": ["保険証券", "保険更新通知", "保険料納入告知額", "口座振替開始通知書",
                      "共済加入証書", "保険料納入告知書"],
        "Medical": ["診療明細書", "領収書", "処方箋"],
        "School": ["成績通知", "通知表", "探究ゼミ実施要項", "講師派遣依頼書",
                   "職業講演会", "Teams接続情報"],
        "Utility": [
            "水道料金領収証", "水道料金領収書",
            "水道料金案内", "水道料金のお知らせ", "水道料金促状",
            "使用水量のお知らせ", "電気ご使用量のお知らせ", "ガス使用量のお知らせ",
        ],
        "Receipt": ["領収書", "領収証"],
        "Finance": ["クレジットカード明細", "ご利用明細", "ご利用代金明細書"],
        "Other": [],
    }
    for kw in doc_keywords.get(category, []):
        if kw in text:
            return kw
    return ""


def parse_rename_fields(
    ocr_text: str,
    source_filename: str,
    bracket_tags: Optional[List[str]] = None,
) -> Dict:
    """
    OCR テキストとソースファイル名から rename フィールドを推定する。

    優先順位:
    - 日付: ファイル名の YYYYMMDD を最優先。日付のみファイル名のときのみ OCR 日付を使用
            ※ 年が 1900〜2099 の範囲外はファイル名・OCR ともに無効とする
    - Category: OCR テキスト → ファイル名テキストの順で判定
    - Document: OCR テキスト → ファイル名から推定（blocklist に該当するものは除外）
    - Counterparty: Bracket tag → OCR テキスト（住所・登録番号は除外）
    """
    tags = bracket_tags or []

    # --- OCR テキスト前処理: 誤認識を正規表現で置換 ---
    ocr_text = _apply_ocr_replace_map(ocr_text)

    # --- 日付: ファイル名を最優先（年バリデーションあり）---
    filename_date = re.match(r"^(\d{8})", source_filename)
    stem = Path(source_filename).stem
    fn_date_valid = False
    if filename_date:
        fn_year = int(filename_date.group(1)[:4])
        fn_date_valid = _is_valid_year(fn_year)

    if fn_date_valid and stem != filename_date.group(1):
        # ファイル名に日付 + 他のテキストがある、かつ年が有効 → ファイル名の日付を使う
        date = filename_date.group(1)
    else:
        # 日付のみファイル名 or 日付なし or 年が範囲外 → OCR から取得
        date = _extract_date(ocr_text, source_filename)

    # --- Category: OCR → ファイル名順 ---
    combined_text = ocr_text + " " + source_filename
    category = _extract_category(combined_text)

    # --- Counterparty ---
    counterparty = _extract_counterparty(ocr_text, tags)

    # --- Amount ---
    amount_jpy = _extract_amount(ocr_text)

    # --- Document: OCR → ファイル名推定 ---
    document = _extract_document_name(combined_text, category)
    if not document:
        # ファイル名の日付/タグを除いた部分を document として使う
        doc_from_name = re.sub(r"【[^】]+】", "", stem)
        doc_from_name = re.sub(r"^\d{8}[_\-]?", "", doc_from_name).strip("-_")
        # split ページ suffix (-p001 など) を除去
        doc_from_name = re.sub(r"-p\d{3}$", "", doc_from_name)
        if doc_from_name:
            document = doc_from_name[:25]  # 25文字上限（長文タイトルを短縮）

    # --- Document blocklist: 無意味な文書名を除外 ---
    if document in DOCUMENT_BLOCKLIST:
        document = ""

    # --- Payment method: ファイル名から抽出 ---
    payment_method = ""
    for keyword, normalized in PAYMENT_METHOD_FROM_FILENAME:
        if keyword in source_filename:
            payment_method = normalized
            break

    return {
        "date": date,
        "category": category,
        "document": document,
        "counterparty": counterparty,
        "amount_jpy": amount_jpy,
        "payment_method": payment_method,
    }


# categories.md に定義された有効カテゴリ一覧
# "Expense" などの非標準 category が混入した場合は "Other" に正規化する
VALID_CATEGORIES = {
    "Work", "Contract", "Government", "Tax", "Insurance",
    "Medical", "School", "Utility", "Finance", "Receipt", "Other",
}


def build_ocr_rename_candidate(fields: Dict) -> str:
    """
    parse_rename_fields の結果から rename 候補ファイル名を生成する。
    Category が確定していない部分は [要確認] を残す。
    非標準 category（Expense 等）は Other に正規化する。
    """
    date = fields.get("date") or "[日付不明]"
    category = fields.get("category") or "Other"
    # 非標準 category を正規化
    if category not in VALID_CATEGORIES:
        category = "Other"
    document = fields.get("document") or "[Document要確認]"
    counterparty = fields.get("counterparty", "")
    amount_jpy = fields.get("amount_jpy")
    payment = fields.get("payment_method", "")

    parts = [date, category, document]
    if counterparty:
        parts.append(counterparty)
    if amount_jpy:
        parts.append(f"{amount_jpy}JPY")
    if payment:
        parts.append(payment)

    return "-".join(parts) + ".pdf"


# ---------------------------------------------------------------------------
# Pattern matching
# ---------------------------------------------------------------------------

def load_patterns(patterns_path: Optional[Path] = None) -> list:
    """config/patterns.json を読み込んでパターンリストを返す。"""
    if patterns_path is None:
        patterns_path = Path(__file__).parent.parent / "config" / "patterns.json"
    if not patterns_path.exists():
        return []
    try:
        import json as _json
        with open(patterns_path, encoding="utf-8") as f:
            config = _json.load(f)
        return config.get("patterns", [])
    except Exception:
        return []


def apply_patterns(
    text: str,
    filename: str,
    fields: Dict,
    patterns: Optional[list] = None,
) -> tuple:
    """
    パターンを適用して fields を更新する。

    Returns: (updated_fields: Dict, matched_reasons: List[str])
    """
    if patterns is None:
        patterns = load_patterns()

    combined = text + " " + filename
    matched_reasons: List[str] = []
    updated = dict(fields)

    for pattern in patterns:
        keywords = pattern.get("keywords", [])
        for keyword in keywords:
            if keyword in combined:
                pat_category = pattern.get("category", "")
                pat_document = pattern.get("document", "")
                pat_counterparty = pattern.get("counterparty", "")

                changed = False

                # ファイル名でキーワードが見つかった場合は文書種別の強いシグナル。
                # 例: 「講師派遣について（依頼）」がファイル名に含まれる →
                #       OCR 本文が探究ゼミ実施要項に言及していても「講師派遣依頼書」を優先
                # 誤上書き防止のため、5文字以上のキーワードに限定
                keyword_in_filename = (keyword in filename) and len(keyword) >= 5

                # --- Category ---
                # OCR 本文でキーワードが見つかり、かつキーワードが5文字以上の場合は
                # parse_rename_fields の暫定分類よりパターンを優先して上書きする。
                # （例: 水道料金通知に「請求書に記載の…」という記述が含まれ Contract に
                #   誤分類された場合でも、「使用水量のお知らせ」9文字で Utility に訂正できる）
                # 短いキーワード（3〜4文字: 領収証・請求書など）は誤上書きを避けるため除外。
                if pat_category:
                    current_cat = updated.get("category", "")
                    keyword_in_ocr = keyword in text  # ファイル名ではなく OCR 本文での一致
                    can_override_cat = keyword_in_ocr and len(keyword) >= 5
                    if (not current_cat
                            or current_cat == "Other"
                            or can_override_cat):
                        if current_cat != pat_category:
                            updated["category"] = pat_category
                            changed = True

                # --- Document ---
                # スラグ（ファイル名由来の仮称・数字のみ・角括弧表記・
                #         マイナス記号付き住所・20文字超の長いファイル名断片）か
                # カテゴリが変わった場合、またはキーワードがファイル名に直接含まれる場合は上書き可
                existing_doc = updated.get("document", "")
                doc_is_slug = bool(re.search(
                    r"[_\-]\d|JPY|現金|領収証_|案内_|^\d+$|^〈|[−]\d|\d[−]",
                    existing_doc
                )) or len(existing_doc) > 20
                if pat_document and (not existing_doc or doc_is_slug or changed
                                     or keyword_in_filename):
                    updated["document"] = pat_document
                    changed = True

                # --- Counterparty ---
                # 空の場合か、短い ASCII のみ文字列（OCR ゴミ）の場合に上書き
                existing_cp = updated.get("counterparty", "")
                cp_is_ocr_garbage = bool(
                    existing_cp
                    and re.match(r'^[A-Za-z0-9]+$', existing_cp)
                    and len(existing_cp) < 8
                )
                if pat_counterparty and (not existing_cp or cp_is_ocr_garbage):
                    updated["counterparty"] = pat_counterparty
                    changed = True

                if changed or (pat_category and updated.get("category") == pat_category):
                    matched_reasons.append(f"pattern: {keyword} → {pat_category}/{pat_document}")
                break  # 1パターン1マッチのみ

    return updated, matched_reasons


# ---------------------------------------------------------------------------
# Confidence scoring
# ---------------------------------------------------------------------------

AUTO_APPROVE_THRESHOLD = 0.85

CONFIDENCE_WEIGHTS = {
    "date":           0.20,
    "category":       0.20,
    "document":       0.25,
    "counterparty":   0.15,
    "amount_jpy":     0.10,
    "payment_method": 0.10,
}
PENALTY_GARBLED    = -0.30
PENALTY_DATE_ONLY  = -0.20
PENALTY_PLACEHOLDER = -0.30
BONUS_PATTERN_MATCH = 0.05


def compute_confidence(
    fields: Dict,
    garbled: bool,
    date_only: bool,
    ocr_rename_candidate: str,
    pattern_matched: bool = False,
) -> tuple:
    """
    OCR 推定結果の confidence スコアを計算する。

    Returns: (score: float, reasons: List[str])
    """
    score = 0.0
    reasons: List[str] = []

    if fields.get("date"):
        score += CONFIDENCE_WEIGHTS["date"]
        reasons.append(f"date detected: {fields['date']} (+{CONFIDENCE_WEIGHTS['date']})")

    category = fields.get("category", "Other")
    if category and category != "Other":
        score += CONFIDENCE_WEIGHTS["category"]
        reasons.append(f"category detected: {category} (+{CONFIDENCE_WEIGHTS['category']})")

    if fields.get("document"):
        score += CONFIDENCE_WEIGHTS["document"]
        reasons.append(f"document detected: {fields['document']} (+{CONFIDENCE_WEIGHTS['document']})")

    if fields.get("counterparty"):
        score += CONFIDENCE_WEIGHTS["counterparty"]
        reasons.append(f"counterparty detected: {fields['counterparty']} (+{CONFIDENCE_WEIGHTS['counterparty']})")

    if fields.get("amount_jpy") is not None:
        score += CONFIDENCE_WEIGHTS["amount_jpy"]
        reasons.append(f"amount detected: {fields['amount_jpy']} (+{CONFIDENCE_WEIGHTS['amount_jpy']})")

    if fields.get("payment_method"):
        score += CONFIDENCE_WEIGHTS["payment_method"]
        reasons.append(f"payment_method detected (+{CONFIDENCE_WEIGHTS['payment_method']})")

    if garbled:
        score += PENALTY_GARBLED
        reasons.append(f"OCR garbled suspected ({PENALTY_GARBLED})")

    if date_only:
        score += PENALTY_DATE_ONLY
        reasons.append(f"date-only filename ({PENALTY_DATE_ONLY})")

    if "[Document要確認]" in ocr_rename_candidate or "[日付不明]" in ocr_rename_candidate:
        score += PENALTY_PLACEHOLDER
        reasons.append(f"placeholder in rename candidate ({PENALTY_PLACEHOLDER})")

    if pattern_matched:
        score += BONUS_PATTERN_MATCH
        reasons.append(f"pattern match bonus (+{BONUS_PATTERN_MATCH})")

    score = max(0.0, min(1.0, round(score, 2)))
    return score, reasons


def is_auto_approvable(
    fields: Dict,
    garbled: bool,
    date_only: bool,
    ocr_rename_candidate: str,
    confidence: float,
) -> bool:
    """
    auto-approved の条件を満たすか判定する。
    confidence >= 0.85 かつ以下をすべて満たす:
      - Category が推定されている（Other 以外）
      - Document が推定されている
      - OCR 文字化けなし
      - 日付のみファイル名でない
      - rename 候補にプレースホルダーなし
    """
    if confidence < AUTO_APPROVE_THRESHOLD:
        return False
    if garbled:
        return False
    if date_only:
        return False
    if not fields.get("category") or fields.get("category") == "Other":
        return False
    if not fields.get("document"):
        return False
    if "[Document要確認]" in ocr_rename_candidate or "[日付不明]" in ocr_rename_candidate:
        return False
    return True
