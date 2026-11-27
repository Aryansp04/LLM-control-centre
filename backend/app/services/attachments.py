"""File attachment validation, sanitization, text/PDF extraction, and vision payload prep."""

from __future__ import annotations

import base64
import io
import re
from pathlib import Path
from typing import Any, Dict, List

from pypdf import PdfReader

from app.config import get_settings
from app.core.errors import AppError
from app.providers.types import AttachmentPayload

MAX_ATTACHMENTS_PER_MESSAGE = 5
MAX_EXTRACTED_TEXT_CHARS = 40_000

TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".csv",
    ".json",
    ".yaml",
    ".yml",
    ".xml",
    ".log",
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".sql",
    ".html",
    ".css",
    ".sh",
    ".toml",
    ".ini",
}

IMAGE_MIME_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def sanitize_filename(name: str) -> str:
    base = Path(name or "attachment").name
    cleaned = re.sub(r"[^A-Za-z0-9._\- ]+", "_", base).strip()
    return cleaned[:120] or "attachment"


def _verify_image_magic_bytes(raw: bytes, mime_type: str) -> bool:
    if mime_type == "image/png":
        return raw.startswith(b"\x89PNG\r\n\x1a\n")
    if mime_type == "image/jpeg":
        return raw.startswith(b"\xff\xd8\xff")
    if mime_type == "image/gif":
        return raw.startswith((b"GIF87a", b"GIF89a"))
    if mime_type == "image/webp":
        return len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP"
    return False


def validate_and_process_attachment(
    *,
    filename: str,
    content_type: str,
    raw_bytes: bytes,
    model_supports_vision: bool = True,
) -> Dict[str, Any]:
    """Validate uploaded or base64-submitted file and convert into a safe DB/Prompt record."""
    settings = get_settings()
    safe_name = sanitize_filename(filename)
    ext = Path(safe_name).suffix.lower()
    size_bytes = len(raw_bytes)

    if size_bytes == 0:
        raise AppError("empty_attachment", f"Attached file '{safe_name}' is empty.")
    if size_bytes > settings.max_attachment_bytes:
        raise AppError(
            "attachment_too_large",
            f"File '{safe_name}' exceeds maximum size of {settings.max_attachment_bytes // (1024 * 1024)} MB.",
        )

    # 1. Image attachment
    if ext in IMAGE_MIME_BY_EXT or content_type in IMAGE_MIME_BY_EXT.values():
        expected_mime = IMAGE_MIME_BY_EXT.get(ext, content_type)
        if not _verify_image_magic_bytes(raw_bytes, expected_mime):
            raise AppError(
                "invalid_image_file",
                f"File '{safe_name}' failed binary header validation for {expected_mime}.",
            )
        if not model_supports_vision:
            raise AppError(
                "vision_not_supported",
                f"Selected model does not support image attachments ('{safe_name}'). Switch to a vision-capable model.",
            )
        return {
            "filename": safe_name,
            "mime_type": expected_mime,
            "size_bytes": size_bytes,
            "kind": "image",
            "extracted_text": None,
            "base64_data": base64.b64encode(raw_bytes).decode("ascii"),
        }

    # 2. PDF attachment
    if ext == ".pdf" or content_type == "application/pdf":
        if not raw_bytes.startswith(b"%PDF"):
            raise AppError(
                "invalid_pdf_file",
                f"File '{safe_name}' is not a valid PDF document.",
            )
        try:
            reader = PdfReader(io.BytesIO(raw_bytes))
            pages_text: List[str] = []
            for idx, page in enumerate(reader.pages[:40]):
                txt = page.extract_text() or ""
                if txt.strip():
                    pages_text.append(f"[Page {idx + 1}]\n{txt.strip()}")
            extracted = "\n\n".join(pages_text)[:MAX_EXTRACTED_TEXT_CHARS]
        except Exception as exc:
            raise AppError(
                "pdf_parse_error",
                f"Could not extract text from PDF '{safe_name}': {type(exc).__name__}",
            ) from exc

        return {
            "filename": safe_name,
            "mime_type": "application/pdf",
            "size_bytes": size_bytes,
            "kind": "pdf",
            "extracted_text": extracted or "[PDF contained no extractable text]",
            "base64_data": base64.b64encode(raw_bytes).decode("ascii")
            if size_bytes <= 2 * 1024 * 1024
            else None,
        }

    # 3. Structured / Code / Plain-text attachment
    if ext in TEXT_EXTENSIONS or content_type.startswith("text/") or content_type in (
        "application/json",
        "application/xml",
    ):
        if b"\x00" in raw_bytes[:2048]:
            raise AppError(
                "binary_file_rejected",
                f"File '{safe_name}' appears to be binary and cannot be processed as text.",
            )
        decoded = raw_bytes.decode("utf-8", errors="replace")[:MAX_EXTRACTED_TEXT_CHARS]
        return {
            "filename": safe_name,
            "mime_type": content_type or "text/plain",
            "size_bytes": size_bytes,
            "kind": "text",
            "extracted_text": decoded,
            "base64_data": None,
        }

    raise AppError(
        "unsupported_attachment_type",
        f"Unsupported file type for '{safe_name}'. Supported: text/code files, PDF, PNG, JPEG, WEBP, GIF.",
    )


def hydrate_attachment_payloads(
    raw_items: List[Dict[str, Any]] | None,
) -> List[AttachmentPayload]:
    if not raw_items:
        return []
    out: List[AttachmentPayload] = []
    for item in raw_items[:MAX_ATTACHMENTS_PER_MESSAGE]:
        out.append(
            AttachmentPayload(
                filename=str(item.get("filename") or "attachment"),
                mime_type=str(item.get("mime_type") or "text/plain"),
                size_bytes=int(item.get("size_bytes") or 0),
                kind=str(item.get("kind") or "text"),
                extracted_text=item.get("extracted_text"),
                base64_data=item.get("base64_data"),
            )
        )
    return out
