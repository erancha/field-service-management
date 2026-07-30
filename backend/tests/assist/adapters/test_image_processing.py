"""Pillow adapter tests build tiny images in memory; no fixtures on disk."""
from __future__ import annotations

import io

import pytest
from PIL import Image

from fsm.assist.adapters.image_processing import PillowPreviewMaker
from fsm.assist.domain.errors import UnsupportedPhoto


def _image_bytes(format: str, size=(64, 48), mode="RGB") -> bytes:
    buffer = io.BytesIO()
    Image.new(mode, size, color=(200, 10, 10) if mode == "RGB" else None).save(buffer, format=format)
    return buffer.getvalue()


@pytest.mark.parametrize(
    "format,media_type",
    [("JPEG", "image/jpeg"), ("PNG", "image/png"), ("WEBP", "image/webp")],
)
def test_supported_formats_are_detected_from_the_bytes(format: str, media_type: str) -> None:
    inspected = PillowPreviewMaker().prepare(_image_bytes(format))

    assert inspected.media_type == media_type
    assert Image.open(io.BytesIO(inspected.preview_jpeg)).format == "JPEG"


def test_garbage_bytes_are_rejected() -> None:
    with pytest.raises(UnsupportedPhoto):
        PillowPreviewMaker().prepare(b"this is not an image")


def test_unsupported_format_is_rejected() -> None:
    with pytest.raises(UnsupportedPhoto):
        PillowPreviewMaker().prepare(_image_bytes("BMP"))


def test_preview_long_edge_is_bounded() -> None:
    inspected = PillowPreviewMaker().prepare(_image_bytes("JPEG", size=(4000, 1000)))

    preview = Image.open(io.BytesIO(inspected.preview_jpeg))
    assert max(preview.size) == 1280


def test_small_images_are_not_upscaled() -> None:
    inspected = PillowPreviewMaker().prepare(_image_bytes("JPEG", size=(64, 48)))

    assert Image.open(io.BytesIO(inspected.preview_jpeg)).size == (64, 48)


def test_alpha_images_flatten_to_jpeg() -> None:
    inspected = PillowPreviewMaker().prepare(_image_bytes("PNG", mode="RGBA"))

    assert Image.open(io.BytesIO(inspected.preview_jpeg)).mode == "RGB"


def test_absurd_pixel_counts_are_rejected_without_decoding() -> None:
    # A tiny file can still declare enormous dimensions; the guard reads the header only.
    with pytest.raises(UnsupportedPhoto):
        PillowPreviewMaker().prepare(_image_bytes("PNG", size=(9000, 9000), mode="1"))


def test_truncated_image_is_rejected() -> None:
    # Header is valid but pixel data is incomplete; decode fails at runtime.
    valid_bytes = _image_bytes("PNG", size=(64, 48))
    truncated = valid_bytes[:len(valid_bytes) // 2]
    with pytest.raises(UnsupportedPhoto):
        PillowPreviewMaker().prepare(truncated)
