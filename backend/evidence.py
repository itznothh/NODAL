"""Private filesystem storage for complaint image evidence."""
import hashlib
import io
import os
import uuid
import warnings
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, UnidentifiedImageError

MAX_EVIDENCE_BYTES = 5 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
FORMATS = {
    "JPEG": ("image/jpeg", ".jpg"),
    "PNG": ("image/png", ".png"),
    "WEBP": ("image/webp", ".webp"),
}


class EvidenceError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


def store_evidence(data, directory):
    """Validate and write bytes under a generated name, returning DB-safe metadata."""
    if not data:
        raise EvidenceError("The attached image is empty.")
    if len(data) > MAX_EVIDENCE_BYTES:
        raise EvidenceError("Image is too large. Maximum size is 5 MB.", 413)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            image = Image.open(io.BytesIO(data))
            image_format = image.format
            width, height = image.size
            if width * height > MAX_IMAGE_PIXELS:
                raise EvidenceError("Image dimensions are too large to process.", 413)
            image.verify()
    except EvidenceError:
        raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise EvidenceError("The attached file is not a valid supported image.")
    if image_format not in FORMATS:
        raise EvidenceError("Unsupported image format. Use JPEG, PNG or WebP.", 415)

    evidence_id = uuid.uuid4().hex
    content_type, extension = FORMATS[image_format]
    generated_name = f"{evidence_id}{extension}"
    root = Path(directory).resolve()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name == "posix":
        root.chmod(0o700)
    path = root / generated_name
    try:
        with path.open("xb") as target:
            target.write(data)
        if os.name == "posix":
            path.chmod(0o600)
    except OSError:
        path.unlink(missing_ok=True)
        raise EvidenceError("Could not securely store the attached image.", 503)
    return {
        "id": evidence_id,
        "storage_key": generated_name,
        "content_type": content_type,
        "byte_size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "width": width,
        "height": height,
        "uploaded_at": datetime.now(timezone.utc),
    }


def evidence_path(directory, storage_key):
    """Resolve an internally stored key without accepting arbitrary path input."""
    root = Path(directory).resolve()
    key = Path(storage_key)
    if key.name != storage_key or key.suffix.lower() not in {".jpg", ".png", ".webp"}:
        return None
    path = (root / key.name).resolve()
    if path.parent != root or not path.is_file():
        return None
    return path
