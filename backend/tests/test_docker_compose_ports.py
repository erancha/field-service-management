"""Checks how docker-compose publishes the data-layer services to the host.

`db` (Postgres, default credentials), `redis` (no auth) and `objectstore` (static credentials) are
published so host-mode processes can reach them at localhost during development. Docker publishes
on all host interfaces by default, which bypasses common host firewalls and exposes them to the
whole LAN. Binding the host side to 127.0.0.1 keeps the intended localhost workflow working while
closing that exposure. Photos never leave the stack through the object store directly — phones
fetch them through the role APIs — so it needs no off-host reachability either.
"""
import re
from pathlib import Path

COMPOSE_FILE = Path(__file__).resolve().parents[2] / "docker-compose.yml"

# The published ports of Postgres, Redis and the object store; the host side must be loopback-only.
_UNQUALIFIED_PUBLISH = re.compile(r'"(?<!127\.0\.0\.1:)(?:5432|6379|9100):(?:5432|6379|9000)"')

# The host side of the object-store publish, whatever interface qualifier precedes it.
_OBJECT_STORE_PUBLISH = re.compile(r'"(?:127\.0\.0\.1:)?(?P<host_port>\d+):9000"')


def test_data_layer_ports_are_loopback_only():
    text = COMPOSE_FILE.read_text(encoding="utf-8")
    offenders = _UNQUALIFIED_PUBLISH.findall(text)
    assert not offenders, (
        f"docker-compose publishes a data-layer port on all host interfaces: {offenders}"
    )


def test_object_store_publishes_on_a_non_default_host_port():
    text = COMPOSE_FILE.read_text(encoding="utf-8")
    match = _OBJECT_STORE_PUBLISH.search(text)
    assert match is not None, "docker-compose no longer publishes the object store to the host"
    assert match["host_port"] != "9000", (
        "object-store host port collides with another local S3 store"
    )
