"""MinIO-backed photo object store."""
from __future__ import annotations

import io
from collections.abc import Sequence

from minio import Minio
from minio.deleteobjects import DeleteObject


class MinioPhotoStore:
    """Stores photo objects in one bucket, created on first use.

    The client holds no connection at construction time, so building the store at app startup
    does not require MinIO to be reachable; an unreachable endpoint surfaces on the first photo
    operation instead of blocking every deployment that never uses photos.
    """

    def __init__(
        self, endpoint: str, access_key: str, secret_key: str, bucket: str, secure: bool = False
    ) -> None:
        self._client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)
        self._bucket = bucket
        self._bucket_ensured = False

    def _ensure_bucket(self) -> None:
        if not self._bucket_ensured:
            if not self._client.bucket_exists(self._bucket):
                self._client.make_bucket(self._bucket)
            self._bucket_ensured = True

    def put(self, key: str, content: bytes, media_type: str) -> None:
        self._ensure_bucket()
        self._client.put_object(
            self._bucket, key, io.BytesIO(content), len(content), content_type=media_type
        )

    def get(self, key: str) -> bytes:
        self._ensure_bucket()
        response = self._client.get_object(self._bucket, key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def remove(self, keys: Sequence[str]) -> None:
        """Raises RuntimeError if MinIO reports a failure for any individual key."""
        self._ensure_bucket()
        errors = list(
            self._client.remove_objects(self._bucket, [DeleteObject(key) for key in keys])
        )
        if errors:
            raise RuntimeError(f"MinIO refused to delete {len(errors)} object(s): {errors[0]}")
