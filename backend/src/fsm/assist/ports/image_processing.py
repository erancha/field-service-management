"""Outbound port for turning an uploaded file into a stored photo's derived pieces."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class InspectedPhoto:
    """What upload processing learned: the detected media type of the original bytes and the
    downscaled, EXIF-free JPEG the model and thumbnails consume."""

    media_type: str
    preview_jpeg: bytes


@runtime_checkable
class PreviewMaker(Protocol):
    def prepare(self, content: bytes) -> InspectedPhoto:
        """Raises UnsupportedPhoto for undecodable, unsupported, or absurdly large images."""
        ...
