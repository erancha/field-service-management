"""Checks that docker-compose publishes the data-layer services on loopback only.

`db` (Postgres, default credentials), `redis` (no auth), and `minio` (fixed local credentials) are
published so host-mode processes can reach them at localhost during development. Docker publishes
on all host interfaces by default, which bypasses common host firewalls and exposes them to the
whole LAN. Binding the host side to 127.0.0.1 keeps the intended localhost workflow working while
closing that exposure.
"""
import re
from pathlib import Path

COMPOSE_FILE = Path(__file__).resolve().parents[2] / "docker-compose.yml"

# The published container ports for the data-layer services; the host side must be loopback-only.
_UNQUALIFIED_PUBLISH = re.compile(r'"(?<!127\.0\.0\.1:)(?:5432|6379|9000):(?:5432|6379|9000)"')


def test_data_layer_ports_are_loopback_only():
    text = COMPOSE_FILE.read_text(encoding="utf-8")
    offenders = _UNQUALIFIED_PUBLISH.findall(text)
    assert not offenders, (
        f"docker-compose publishes a data-layer port on all host interfaces: {offenders}"
    )
