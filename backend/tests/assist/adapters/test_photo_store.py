"""Round-trips against a real MinIO container; Docker must be running (same as pg_engine)."""
from __future__ import annotations

import pytest
from minio.deleteobjects import DeleteError
from testcontainers.minio import MinioContainer

from fsm.assist.adapters.photo_store import MinioPhotoStore
from fsm.assist.ports.photo_store import PhotoStore


@pytest.fixture(scope="module")
def store():
    with MinioContainer() as container:
        config = container.get_config()
        yield MinioPhotoStore(
            endpoint=config["endpoint"],
            access_key=config["access_key"],
            secret_key=config["secret_key"],
            bucket="test-photos",
        )


def test_satisfies_the_port(store) -> None:
    assert isinstance(store, PhotoStore)


def test_put_then_get_round_trips_the_bytes(store) -> None:
    store.put("photos/x/original", b"jpeg-bytes", "image/jpeg")

    assert store.get("photos/x/original") == b"jpeg-bytes"


def test_remove_deletes_every_given_key(store) -> None:
    store.put("photos/y/original", b"a", "image/jpeg")
    store.put("photos/y/preview", b"b", "image/jpeg")

    store.remove(["photos/y/original", "photos/y/preview"])

    with pytest.raises(Exception):
        store.get("photos/y/original")


class _StubClientReportingADeletionFailure:
    """Fakes the one MinIO response shape `remove` must not swallow: a per-object error."""

    def bucket_exists(self, bucket: str) -> bool:
        return True

    def remove_objects(self, bucket: str, delete_object_list):
        return iter(
            [DeleteError(code="AccessDenied", message="denied", name="photos/z/original", version_id=None)]
        )


def test_remove_raises_when_minio_reports_a_deletion_failure() -> None:
    store = MinioPhotoStore(
        endpoint="unused:9000", access_key="unused", secret_key="unused", bucket="test-photos"
    )
    store._client = _StubClientReportingADeletionFailure()

    with pytest.raises(RuntimeError):
        store.remove(["photos/z/original"])
