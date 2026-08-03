"""Outbound port for the photo object store, plus the key scheme both contexts share.

Each photo owns a key prefix; the full-resolution original and the model-sized preview are the
only objects ever written under it, so deletion is exactly photo_keys(prefix).
"""
from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Literal, Protocol, runtime_checkable

PhotoVariant = Literal["original", "preview"]


def object_prefix(photo_id: uuid.UUID) -> str:
    return f"photos/{photo_id}"


def original_key(object_key: str) -> str:
    return f"{object_key}/original"


def preview_key(object_key: str) -> str:
    return f"{object_key}/preview"


def photo_keys(object_key: str) -> tuple[str, str]:
    """Every object stored for a photo; deletion must remove exactly these."""
    return (original_key(object_key), preview_key(object_key))


def variant_object(object_key: str, media_type: str, variant: PhotoVariant) -> tuple[str, str]:
    """The stored key of one variant and the media type it is served as.

    Previews are re-encoded to JPEG when written, so the uploaded media type describes the
    original alone.
    """
    if variant == "original":
        return original_key(object_key), media_type
    return preview_key(object_key), "image/jpeg"


@runtime_checkable
class PhotoStore(Protocol):
    def put(self, key: str, content: bytes, media_type: str) -> None: ...

    def get(self, key: str) -> bytes: ...

    def remove(self, keys: Sequence[str]) -> None: ...
