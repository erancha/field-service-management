"""Round-trips against a real object-store container; Docker must be running (same as pg_engine).

The container runs the exact image docker-compose.yml ships, read from that file so the suite
cannot drift from the stack and silently prove the adapter against a different server.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from minio.deleteobjects import DeleteError
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import HttpWaitStrategy

from fsm.assist.adapters.photo_store import MinioPhotoStore
from fsm.assist.ports.photo_store import PhotoStore

_COMPOSE_FILE = Path(__file__).resolve().parents[4] / "docker-compose.yml"
_COMPOSE_IMAGE = re.compile(r"^\s+image:\s*(rustfs/rustfs:\S+)", re.MULTILINE)
_S3_PORT = 9000


def _shipped_image() -> str:
    match = _COMPOSE_IMAGE.search(_COMPOSE_FILE.read_text(encoding="utf-8"))
    assert match is not None, f"{_COMPOSE_FILE} no longer pins a rustfs/rustfs image"
    return match[1]


@pytest.fixture(scope="module")
def store():
    container = (
        DockerContainer(_shipped_image())
        .with_env("RUSTFS_ACCESS_KEY", "fsm")
        .with_env("RUSTFS_SECRET_KEY", "fsm-test")
        .with_command("/data")
        .with_exposed_ports(_S3_PORT)
        .waiting_for(HttpWaitStrategy(_S3_PORT, "/health"))
    )
    with container:
        endpoint = f"{container.get_container_host_ip()}:{container.get_exposed_port(_S3_PORT)}"
        yield MinioPhotoStore(
            endpoint=endpoint, access_key="fsm", secret_key="fsm-test", bucket="test-photos"
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
