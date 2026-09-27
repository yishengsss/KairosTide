"""Validate and normalize a transient user image before multimodal inference."""

from __future__ import annotations

import base64
import binascii
import hashlib
import math
import warnings
from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError


MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGE_BASE64_CHARS = 14_000_000
MAX_IMAGE_PIXELS = 20_000_000
MAX_MODEL_PIXELS = 8_388_608
SUPPORTED_IMAGE_FORMATS = {
    "image/jpeg": "JPEG",
    "image/png": "PNG",
    "image/webp": "WEBP",
}


class ImageValidationError(ValueError):
    """The uploaded bytes are not a supported, bounded image."""


@dataclass(frozen=True)
class ValidatedImage:
    mime_type: str
    data_url: str
    sha256: str
    width: int
    height: int


def validate_image(mime_type: str, data_base64: str) -> ValidatedImage:
    normalized_mime = mime_type.lower().strip()
    expected_format = SUPPORTED_IMAGE_FORMATS.get(normalized_mime)
    if expected_format is None:
        raise ImageValidationError("unsupported image format")
    if not data_base64 or len(data_base64) > MAX_IMAGE_BASE64_CHARS:
        raise ImageValidationError("image payload is empty or too large")
    try:
        raw = base64.b64decode(data_base64, validate=True)
    except (binascii.Error, ValueError):
        raise ImageValidationError("image payload is not valid base64") from None
    if not raw or len(raw) > MAX_IMAGE_BYTES:
        raise ImageValidationError("image is too large")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw)) as source:
                if source.format != expected_format or getattr(source, "n_frames", 1) != 1:
                    raise ImageValidationError("unsupported or mismatched image format")
                width, height = source.size
                if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
                    raise ImageValidationError("image exceeds the pixel limit")
                source.verify()

            with Image.open(BytesIO(raw)) as source:
                image = ImageOps.exif_transpose(source)
                image.load()
                if image.width * image.height > MAX_MODEL_PIXELS:
                    side = math.isqrt(MAX_MODEL_PIXELS)
                    image.thumbnail((side, side), Image.Resampling.LANCZOS)
                output = BytesIO()
                save_options: dict[str, object] = {}
                if expected_format == "JPEG":
                    if image.mode not in ("RGB", "L"):
                        image = image.convert("RGB")
                    save_options = {"quality": 92, "optimize": True}
                elif expected_format == "PNG":
                    save_options = {"optimize": True}
                else:
                    if image.mode not in ("RGB", "RGBA"):
                        image = image.convert("RGBA" if "transparency" in image.info else "RGB")
                    save_options = {"quality": 92, "method": 4}
                image.save(output, format=expected_format, **save_options)
                normalized = output.getvalue()
                width, height = image.size
    except ImageValidationError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ImageValidationError("image exceeds the pixel limit") from None
    except (UnidentifiedImageError, OSError, ValueError, TypeError):
        raise ImageValidationError("image could not be decoded") from None

    if len(normalized) > MAX_IMAGE_BYTES:
        raise ImageValidationError("normalized image is too large")
    encoded = base64.b64encode(normalized).decode("ascii")
    return ValidatedImage(
        mime_type=normalized_mime,
        data_url=f"data:{normalized_mime};base64,{encoded}",
        sha256=hashlib.sha256(normalized).hexdigest(),
        width=width,
        height=height,
    )
