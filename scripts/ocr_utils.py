"""
ocr_utils.py

OCR エンジン抽象化レイヤー。
利用可能なエンジンを順に試してテキストを抽出する。

対応エンジン（優先順）:
  1. pdftotext (poppler) — テキストベース PDF 用（任意インストール: brew install poppler）
  2. macOS Vision Framework — スキャン PDF・画像用（swiftc でコンパイル）

新しいエンジンを追加する場合はこのファイルを更新する。

Usage:
    from ocr_utils import extract_text_with_engine, OCRResult
    result = extract_text_with_engine(path)
    print(result.text, result.engine, result.success)
"""

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

SCRIPTS_DIR = Path(__file__).parent
OCR_BINARY = SCRIPTS_DIR / "vision_ocr"
SWIFT_SOURCE = SCRIPTS_DIR / "vision_ocr.swift"


@dataclass
class OCRResult:
    text: str = ""
    engine: str = "none"
    success: bool = False
    error: str = ""


def _ensure_vision_binary() -> bool:
    if OCR_BINARY.exists():
        return True
    if not SWIFT_SOURCE.exists():
        return False
    result = subprocess.run(
        ["swiftc", str(SWIFT_SOURCE), "-o", str(OCR_BINARY)],
        capture_output=True, text=True,
    )
    return result.returncode == 0 and OCR_BINARY.exists()


def _pdf_to_jpeg(pdf_path: Path) -> Optional[Path]:
    """sips で PDF 1ページ目を JPEG に変換する。"""
    tmp = Path(tempfile.mktemp(suffix=".jpg"))
    result = subprocess.run(
        ["sips", "-s", "format", "jpeg", str(pdf_path), "--out", str(tmp)],
        capture_output=True, text=True,
    )
    if result.returncode == 0 and tmp.exists():
        return tmp
    return None


def _try_pdftotext(path: Path) -> OCRResult:
    """pdftotext (poppler) でテキストを抽出する。テキストベース PDF 専用。"""
    if path.suffix.lower() != ".pdf":
        return OCRResult(error="pdftotext: not a PDF")
    check = subprocess.run(["which", "pdftotext"], capture_output=True)
    if check.returncode != 0:
        return OCRResult(error="pdftotext not installed")
    result = subprocess.run(
        ["pdftotext", "-q", str(path), "-"],
        capture_output=True, text=True, timeout=15,
    )
    text = result.stdout.strip()
    if result.returncode == 0 and len(text) > 30:
        return OCRResult(text=text, engine="pdftotext", success=True)
    return OCRResult(error="pdftotext returned insufficient text")


def _try_vision(path: Path) -> OCRResult:
    """macOS Vision Framework OCR (Swift binary) でテキストを抽出する。"""
    if not _ensure_vision_binary():
        return OCRResult(error="vision binary not available")
    ext = path.suffix.lower()
    image_path = path
    tmp_created: Optional[Path] = None
    try:
        if ext == ".pdf":
            tmp_created = _pdf_to_jpeg(path)
            if not tmp_created:
                return OCRResult(error="sips PDF→JPEG conversion failed")
            image_path = tmp_created
        result = subprocess.run(
            [str(OCR_BINARY), str(image_path)],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            return OCRResult(text=result.stdout.strip(), engine="vision", success=True)
        return OCRResult(error="vision returned empty text")
    except Exception as e:
        return OCRResult(error=str(e))
    finally:
        if tmp_created:
            tmp_created.unlink(missing_ok=True)


def extract_text_with_engine(path: Path) -> OCRResult:
    """
    利用可能な OCR エンジンを試して最初に成功した結果を返す。

    優先順:
      1. pdftotext — テキスト PDF に高速・高精度
      2. macOS Vision — スキャン PDF・画像
    """
    ext = path.suffix.lower()
    if ext == ".pdf":
        result = _try_pdftotext(path)
        if result.success:
            return result
    result = _try_vision(path)
    if result.success:
        return result
    return OCRResult(text="", engine="none", success=False, error="all engines failed")
