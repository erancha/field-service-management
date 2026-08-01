"""Pillow-backed photo inspection and preview generation."""
from __future__ import annotations

import io

from PIL import Image, ImageOps

from fsm.assist.domain.errors import UnsupportedPhoto
from fsm.assist.ports.image_processing import InspectedPhoto

_SUPPORTED_FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}

_PREVIEW_LONG_EDGE = 1280
_PREVIEW_JPEG_QUALITY = 80

# Covers phone cameras, while a decompression bomb declaring more is rejected from the header
# alone, before any pixel is decoded. Preparing a picture at this size peaks ~135 MB above the
# process baseline — several times its raw RGB, since the decode, the transposed copy, and the RGB
# conversion are live at once — which is what the customer role's raised ceiling accommodates.
_MAX_PIXELS = 25_000_000


class PillowPreviewMaker:
    """Detects the real image type from the bytes and renders the model-sized preview.

    The preview is EXIF-transposed so orientation survives, then re-encoded to JPEG, which drops
    EXIF (including GPS) from what the model and thumbnails see; the untouched original keeps it.
    """

    def prepare(self, content: bytes) -> InspectedPhoto:
        try:
            img = Image.open(io.BytesIO(content))
            image_format = img.format
            width, height = img.size
        except Exception as exc:
            raise UnsupportedPhoto("The file is not a readable image") from exc

        media_type = _SUPPORTED_FORMATS.get(image_format or "")
        if media_type is None:
            raise UnsupportedPhoto("Photos must be JPEG, PNG, or WebP images")
        if width * height > _MAX_PIXELS:
            raise UnsupportedPhoto("The image dimensions are too large; please resize and retry")

        try:
            preview_img = ImageOps.exif_transpose(img)
            preview_img.thumbnail((_PREVIEW_LONG_EDGE, _PREVIEW_LONG_EDGE))
            buffer = io.BytesIO()
            preview_img.convert("RGB").save(buffer, format="JPEG", quality=_PREVIEW_JPEG_QUALITY)
        except Exception as exc:
            raise UnsupportedPhoto("The file is not a readable image") from exc
        return InspectedPhoto(media_type=media_type, preview_jpeg=buffer.getvalue())
