"""Checks how docker-compose publishes the data-layer services to the host.

`db` (Postgres, default credentials) and `redis` (no auth) are published so host-mode processes can
reach them at localhost during development. Docker publishes on all host interfaces by default,
which bypasses common host firewalls and exposes them to the whole LAN. Binding the host side to
127.0.0.1 keeps the intended localhost workflow working while closing that exposure.

`minio` is the deliberate exception: a photo object has to be reachable from a device other than
this host, so it publishes on every interface, and on a host port other than MinIO's default.
"""
import re
from pathlib import Path

COMPOSE_FILE = Path(__file__).resolve().parents[2] / "docker-compose.yml"

# The published container ports for Postgres and Redis; the host side must be loopback-only.
_UNQUALIFIED_PUBLISH = re.compile(r'"(?<!127\.0\.0\.1:)(?:5432|6379):(?:5432|6379)"')

# The host side of the MinIO publish: no interface qualifier, and not MinIO's default port.
_MINIO_PUBLISH = re.compile(r'"(?P<host_port>[^":]+):9000"')


def test_postgres_and_redis_ports_are_loopback_only():
    text = COMPOSE_FILE.read_text(encoding="utf-8")
    offenders = _UNQUALIFIED_PUBLISH.findall(text)
    assert not offenders, (
        f"docker-compose publishes a data-layer port on all host interfaces: {offenders}"
    )


def test_minio_publishes_off_host_on_a_non_default_port():
    text = COMPOSE_FILE.read_text(encoding="utf-8")
    match = _MINIO_PUBLISH.search(text)
    assert match is not None, "docker-compose no longer publishes MinIO on every host interface"
    assert match["host_port"] != "9000", "the MinIO host port collides with another local S3 store"
