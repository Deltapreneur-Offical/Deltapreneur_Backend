import logging
import mimetypes
import zipfile
from io import BytesIO

from botocore.exceptions import ClientError
from fastapi import HTTPException, UploadFile

from app.core.config import settings
from app.integrations.s3.media_service import generate_media_key
from app.integrations.s3.s3_service import get_storage_client
from app.integrations.s3.supabase_storage import (
    key_from_storage_url,
    public_object_url,
)

logger = logging.getLogger(__name__)

VENTURE_VERIFICATION_ALLOWED_EXTENSIONS = {
    ".pdf",
    ".doc",
    ".docx",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
}

VENTURE_VERIFICATION_ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "image/png",
    "image/jpeg",
    "image/webp",
}


_ALLOWED_IMAGE_MIME_TYPES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
    "image/gif",
}

_JPEG_MIME = {"image/jpeg", "image/jpg"}


def _peek_upload_bytes(file: UploadFile, size: int = 96) -> bytes:
    fh = file.file
    pos = fh.tell()
    try:
        data = fh.read(size) or b""
    finally:
        fh.seek(pos)
    return data


def _sniff_image_mime(header: bytes) -> str | None:
    if len(header) >= 3 and header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(header) >= 8 and header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(header) >= 6 and header[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if (
        len(header) >= 12
        and header.startswith(b"RIFF")
        and header[8:12] == b"WEBP"
    ):
        return "image/webp"
    return None


def _sniff_document_kind(header: bytes, file: UploadFile) -> str | None:
    """Return a canonical MIME for venture verification docs, or None."""
    img = _sniff_image_mime(header)
    if img in {"image/png", "image/jpeg", "image/webp"}:
        return img
    if header.startswith(b"%PDF"):
        return "application/pdf"
    # Legacy OLE Compound File (DOC)
    if header.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return "application/msword"
    # DOCX is a ZIP package containing word/ (cap read to avoid huge uploads).
    if header.startswith(b"PK\x03\x04") or header.startswith(b"PK\x05\x06"):
        pos = file.file.tell()
        try:
            file.file.seek(0)
            raw = file.file.read(12 * 1024 * 1024)
            with zipfile.ZipFile(BytesIO(raw)) as zf:
                names = set(zf.namelist())
            if any(n.startswith("word/") for n in names):
                return (
                    "application/vnd.openxmlformats-officedocument."
                    "wordprocessingml.document"
                )
        except Exception:
            return None
        finally:
            file.file.seek(pos)
    return None


def validate_image(file: UploadFile) -> None:
    content_type = (file.content_type or "").split(";")[0].strip().lower()
    filename = (file.filename or "").lower()
    # Reject SVG and other scriptable image types even if labeled image/*.
    if filename.endswith(".svg") or content_type in {"image/svg+xml", "image/svg"}:
        raise HTTPException(
            status_code=400,
            detail="SVG images are not allowed.",
        )
    if content_type not in _ALLOWED_IMAGE_MIME_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Only JPEG, PNG, WebP, or GIF image files are allowed.",
        )

    sniffed = _sniff_image_mime(_peek_upload_bytes(file))
    if not sniffed:
        raise HTTPException(
            status_code=400,
            detail="File content does not match an allowed image format.",
        )
    if content_type in _JPEG_MIME:
        if sniffed != "image/jpeg":
            raise HTTPException(
                status_code=400,
                detail="File content does not match the declared image type.",
            )
    elif content_type != sniffed:
        raise HTTPException(
            status_code=400,
            detail="File content does not match the declared image type.",
        )


def validate_venture_verification_document(file: UploadFile) -> None:
    filename = (file.filename or "").lower()
    extension = ""
    if "." in filename:
        extension = "." + filename.rsplit(".", 1)[-1]
    content_type = (file.content_type or "").split(";")[0].strip().lower()
    guessed, _ = mimetypes.guess_type(filename)
    allowed = (
        extension in VENTURE_VERIFICATION_ALLOWED_EXTENSIONS
        or content_type in VENTURE_VERIFICATION_ALLOWED_MIME_TYPES
        or (guessed and guessed in VENTURE_VERIFICATION_ALLOWED_MIME_TYPES)
    )
    if not allowed:
        raise HTTPException(
            status_code=400,
            detail=(
                "Unsupported document type. Allowed formats: PDF, DOC, DOCX, "
                "PNG, JPG, JPEG, WEBP."
            ),
        )

    sniffed = _sniff_document_kind(_peek_upload_bytes(file), file)
    if not sniffed or sniffed not in VENTURE_VERIFICATION_ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=400,
            detail="File content does not match an allowed document format.",
        )


def _require_storage_configured() -> None:
    if not settings.storage_configured():
        backend = settings.storage_backend()
        raise HTTPException(
            status_code=503,
            detail=(
                f"Media storage is not configured (backend={backend}). "
                "For Supabase: SUPABASE_URL, SUPABASE_STORAGE_BUCKET, and S3 keys. "
                "For AWS: STORAGE_BACKEND=aws, AWS_BUCKET_NAME, AWS_ACCESS_KEY_ID, "
                "AWS_SECRET_ACCESS_KEY, AWS_REGION."
            ),
        )


def generate_file_url(key: str) -> str:
    return public_object_url(key)


def _raise_for_storage_client_error(exc: ClientError) -> None:
    error = exc.response.get("Error", {}) if exc.response else {}
    code = str(error.get("Code") or "")
    status = (
        exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if exc.response
        else None
    )
    logger.warning(
        "Object storage upload failed backend=%s code=%s status=%s",
        settings.storage_backend(),
        code or status,
        status,
        exc_info=exc,
    )
    if code == "540" or status == 540:
        raise HTTPException(
            status_code=503,
            detail=(
                "Media storage is unavailable because the Supabase project is paused. "
                "Restore it in the Supabase dashboard, or set STORAGE_BACKEND=aws with "
                "valid AWS S3 credentials for local development."
            ),
        ) from exc
    if code in {"NoSuchBucket", "NotFound"}:
        raise HTTPException(
            status_code=503,
            detail=(
                f"Media storage bucket not found ({settings.resolved_storage_bucket()}). "
                "Check SUPABASE_STORAGE_BUCKET or AWS_BUCKET_NAME."
            ),
        ) from exc
    if code in {"AccessDenied", "403", "SignatureDoesNotMatch", "InvalidAccessKeyId"}:
        raise HTTPException(
            status_code=503,
            detail="Media storage credentials are invalid or lack upload permission.",
        ) from exc
    raise HTTPException(
        status_code=503,
        detail="Media storage upload failed. Please try again later.",
    ) from exc


async def _upload_file(
    file: UploadFile,
    folder: str,
    *,
    content_type: str | None = None,
) -> str:
    _require_storage_configured()
    key = generate_media_key(folder, file.filename)
    client = get_storage_client()
    extra_args = {"ContentType": content_type or file.content_type or "application/octet-stream"}
    try:
        client.upload_fileobj(
            file.file,
            settings.resolved_storage_bucket(),
            key,
            ExtraArgs=extra_args,
        )
    except ClientError as exc:
        _raise_for_storage_client_error(exc)
    return generate_file_url(key)


async def upload_image(file: UploadFile, folder: str) -> str:
    """Upload to Supabase Storage via S3-compatible API."""
    validate_image(file)
    return await _upload_file(file, folder)


async def upload_venture_verification_document(file: UploadFile, folder: str) -> str:
    validate_venture_verification_document(file)
    return await _upload_file(file, folder)


def delete_image(image_url: str, folder: str) -> None:
    if not settings.storage_configured():
        return
    try:
        key = key_from_storage_url(image_url, folder)
        if not key:
            logger.warning(
                "Could not parse storage key from url=%s folder=%s",
                image_url,
                folder,
            )
            return
        get_storage_client().delete_object(
            Bucket=settings.resolved_storage_bucket(),
            Key=key,
        )
    except Exception:
        logger.warning(
            "Failed to delete storage object for url=%s folder=%s",
            image_url,
            folder,
            exc_info=True,
        )
