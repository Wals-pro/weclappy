"""MIME type inference for document uploads."""

from __future__ import annotations

import os

__all__ = ["MIME_TYPES", "infer_content_type"]

#: File-extension to MIME type mapping used by :func:`infer_content_type`.
MIME_TYPES: dict[str, str] = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".bmp": "image/bmp",
    ".tiff": "image/tiff",
    ".tif": "image/tiff",
    ".ico": "image/x-icon",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".csv": "text/csv",
    ".txt": "text/plain",
    ".xml": "application/xml",
    ".json": "application/json",
    ".zip": "application/zip",
    ".gz": "application/gzip",
    ".tar": "application/x-tar",
    ".rar": "application/vnd.rar",
    ".7z": "application/x-7z-compressed",
    ".html": "text/html",
    ".htm": "text/html",
    ".css": "text/css",
    ".js": "application/javascript",
    ".mp3": "audio/mpeg",
    ".mp4": "video/mp4",
    ".wav": "audio/wav",
    ".avi": "video/x-msvideo",
    ".mov": "video/quicktime",
    ".eml": "message/rfc822",
    ".msg": "application/vnd.ms-outlook",
}


def infer_content_type(filename: str | None) -> str | None:
    """Return the MIME type for ``filename`` by extension, or ``None`` if unknown."""
    if not filename:
        return None
    _, extension = os.path.splitext(filename)
    return MIME_TYPES.get(extension.lower())
