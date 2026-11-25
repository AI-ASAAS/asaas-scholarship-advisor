"""Safe, size-bounded text extraction for student-uploaded application files."""

from __future__ import annotations

import base64
import binascii
import io
import os
import re
import zipfile
from typing import Tuple
import xml.etree.ElementTree as ET

from core.config import settings

MAX_UPLOAD_BYTES = 2 * 1024 * 1024  # 2 MB raw file cap
MAX_DOCX_ENTRIES = 250
MAX_DOCX_UNCOMPRESSED_BYTES = 5 * 1024 * 1024  # 5 MB anti-zip-bomb limit
MAX_PDF_PAGES = 30
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")


class DocumentExtractionError(ValueError):
    """Raised when an uploaded file cannot be safely validated or extracted."""


def _clean_text(raw: str) -> Tuple[str, bool]:
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL_RE.sub(" ", text)
    lines = [_MULTI_SPACE_RE.sub(" ", line).strip() for line in text.split("\n")]
    normalized = _MULTI_NEWLINE_RE.sub("\n\n", "\n".join(lines)).strip()
    if len(normalized) < 10:
        raise DocumentExtractionError(
            "تعذّر استخراج نص مقروء كافٍ من الملف (تأكد أنه ملف نصي وليس صورة ممسوحة ضوئياً)."
        )
    max_chars = settings.DOCUMENTS_MAX_INPUT_CHARS
    if len(normalized) > max_chars:
        return normalized[:max_chars].rstrip(), True
    return normalized, False


def _decode_plain_bytes(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "utf-16", "cp1256", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise DocumentExtractionError("تعذّر فك ترميز الملف النصي؛ يرجى حفظه بترميز UTF-8.")


def _extract_docx(data: bytes) -> str:
    if not data.startswith(b"PK"):
        raise DocumentExtractionError("ملف Word (.docx) غير صالح أو تالف.")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise DocumentExtractionError("ملف Word (.docx) غير صالح أو تالف.") from exc

    with zf:
        infos = zf.infolist()
        if len(infos) > MAX_DOCX_ENTRIES:
            raise DocumentExtractionError("ملف Word يحتوي على عدد عناصر أكبر من المسموح به.")
        total_uncompressed = sum(max(0, info.file_size) for info in infos)
        if total_uncompressed > MAX_DOCX_UNCOMPRESSED_BYTES:
            raise DocumentExtractionError("حجم المحتوى غير المضغوط في ملف Word يتجاوز الحد المسموح.")

        if "word/document.xml" not in zf.namelist():
            raise DocumentExtractionError("ملف Word (.docx) لا يحتوي على مستند نصي صالح.")

        xml_bytes = zf.read("word/document.xml")

    xml_head = xml_bytes[:4096].upper()
    if b"<!DOCTYPE" in xml_head or b"<!ENTITY" in xml_head:
        raise DocumentExtractionError("محتوى XML داخل ملف Word مرفوض أمنياً.")

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise DocumentExtractionError("تعذّر قراءة بنية ملف Word (.docx).") from exc

    paragraphs = []
    for para in root.iter():
        if para.tag.endswith("}p") or para.tag == "p":
            chunks = [
                node.text
                for node in para.iter()
                if (node.tag.endswith("}t") or node.tag == "t") and node.text
            ]
            line = "".join(chunks).strip()
            if line:
                paragraphs.append(line)
    return "\n".join(paragraphs)


def _extract_pdf(data: bytes) -> str:
    if not data.startswith(b"%PDF-"):
        raise DocumentExtractionError("ملف PDF غير صالح.")
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise DocumentExtractionError(
            "مكتبة قراءة ملفات PDF غير مثبّتة على الخادم؛ يرجى لصق النص أو رفع ملف Word/TXT."
        ) from exc

    try:
        reader = PdfReader(io.BytesIO(data))
        if getattr(reader, "is_encrypted", False):
            raise DocumentExtractionError("ملف PDF محمي بكلمة سر؛ يرجى إزالة الحماية أو لصق النص.")
        pages_text = []
        for page in reader.pages[:MAX_PDF_PAGES]:
            extracted = (page.extract_text() or "").strip()
            if extracted:
                pages_text.append(extracted)
        return "\n\n".join(pages_text)
    except DocumentExtractionError:
        raise
    except Exception as exc:
        raise DocumentExtractionError("تعذّر استخراج النص من ملف PDF؛ قد يكون ملفاً مصوراً أو تالفاً.") from exc


def extract_text_from_base64_file(filename: str, content_base64: str) -> Tuple[str, bool]:
    """Validate and extract readable plain text from an uploaded PDF, DOCX, TXT, or MD file."""
    clean_name = os.path.basename((filename or "").strip())
    _, ext = os.path.splitext(clean_name.lower())
    if ext not in ALLOWED_EXTENSIONS:
        raise DocumentExtractionError(
            "صيغة الملف غير مدعومة؛ الصيغ المسموحة هي PDF وWord (.docx) وTXT وMarkdown."
        )

    b64_payload = (content_base64 or "").strip()
    if b64_payload.startswith("data:") and "," in b64_payload:
        b64_payload = b64_payload.split(",", 1)[1].strip()

    # Reject clearly oversized payloads before decoding
    if len(b64_payload) > ((MAX_UPLOAD_BYTES * 4) // 3) + 64:
        raise DocumentExtractionError("حجم الملف يتجاوز الحد الأقصى المسموح (2 ميجابايت).")

    try:
        raw_bytes = base64.b64decode(b64_payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise DocumentExtractionError("تعذّر قراءة بيانات الملف المرفوع.") from exc

    if not raw_bytes:
        raise DocumentExtractionError("الملف المرفوع فارغ.")
    if len(raw_bytes) > MAX_UPLOAD_BYTES:
        raise DocumentExtractionError("حجم الملف يتجاوز الحد الأقصى المسموح (2 ميجابايت).")

    if ext in {".txt", ".md"}:
        raw_text = _decode_plain_bytes(raw_bytes)
    elif ext == ".docx":
        raw_text = _extract_docx(raw_bytes)
    else:
        raw_text = _extract_pdf(raw_bytes)

    return _clean_text(raw_text)
