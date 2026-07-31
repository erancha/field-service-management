"""Pins where the shared fakes must behave exactly like the real adapters they stand in for."""
from __future__ import annotations

from tests.assist.fakes import FakePhotoStore


def test_fake_photo_store_remove_tolerates_a_missing_key() -> None:
    """S3/MinIO object deletion is idempotent, so a double remove that production tolerates
    must not fail only under test."""
    store = FakePhotoStore()
    store.put("photos/x/original", b"bytes", "image/jpeg")

    store.remove(["photos/x/original"])
    store.remove(["photos/x/original"])

    assert store.objects == {}
    assert store.removed == ["photos/x/original", "photos/x/original"]
