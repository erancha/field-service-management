"""Checks how the compose files wire the roles, the data services and the edge, here and on EC2.

Docker publishes on every host interface by default, which bypasses common host firewalls and
exposes a port to the whole LAN. Postgres, Redis (no auth) and the object store are published on
the loopback interface only, so a psql or a backend started on the host still reaches them at
localhost; photos never leave the stack through the object store directly, since phones fetch
them through the role APIs. The nginx edge is the deliberate exception: it is the one entry
point, one port per role. The role replicas publish nothing.

Compose runs against the EC2 instance's Docker daemon from this machine, where a bind mount would
name a path the instance lacks, so the stack mounts no file of this machine. Each container
receives only the keys it reads, learns the in-network addresses from compose rather than from the
host forms of the settings files, and on EC2 builds its sign-in callbacks from its role's
CloudFront address.
"""

from pathlib import Path
from typing import Any

import yaml
from pydantic import AliasChoices

from fsm.platform.config import Settings
from fsm.platform.logging import ENV_PREFIX

ROOT = Path(__file__).resolve().parents[2]
LOOPBACK = "127.0.0.1:"
DB_PUBLISH = "${DB_HOST_PORT:?set in stack-params.sh}:${DB_PORT:?set in stack-params.sh}"
ROLES = {"technician": "8001", "customer": "8002", "backoffice": "8003"}
BACKENDS = {*ROLES, "worker"}
EDGE_PORTS = [
    "${EDGE_TECHNICIAN_HOST_PORT:?set in stack-params.sh}:8001",
    "${EDGE_CUSTOMER_HOST_PORT:?set in stack-params.sh}:8002",
    "${EDGE_BACKOFFICE_HOST_PORT:?set in stack-params.sh}:8003",
]
# Read from the process environment rather than by Settings.
ENVIRONMENT_KEYS = {f"{ENV_PREFIX}LOG_LEVEL", f"{ENV_PREFIX}LOG_LEVELS"}


class _ComposeLoader(yaml.SafeLoader):
    """Reads an override file's !override tag as the plain value it replaces the base value with."""


_ComposeLoader.add_constructor(
    "!override", lambda loader, node: loader.construct_sequence(node)  # type: ignore[arg-type]
)


def _compose(name: str) -> dict[str, Any]:
    return yaml.load((ROOT / name).read_text(encoding="utf-8"), Loader=_ComposeLoader)


COMPOSE = _compose("docker-compose.yml")
SERVICES = COMPOSE["services"]
EC2_SERVICES = _compose("docker-compose.ec2.yml")["services"]


def _env_name(field: str) -> str:
    """The variable a Settings field is read from: its first alias, else its own name."""
    alias = Settings.model_fields[field].validation_alias
    name = alias.choices[0] if isinstance(alias, AliasChoices) else field
    assert isinstance(name, str)
    return name.upper()


def test_only_the_edge_and_the_data_services_publish_and_those_on_loopback() -> None:
    published = {name: spec["ports"] for name, spec in SERVICES.items() if "ports" in spec}
    assert published == {
        "db": [LOOPBACK + DB_PUBLISH],
        "redis": [LOOPBACK + "${REDIS_HOST_PORT:?set in stack-params.sh}:6379"],
        "objectstore": [LOOPBACK + "${OBJECT_STORE_HOST_PORT:?set in stack-params.sh}:9000"],
        "nginx": EDGE_PORTS,
    }


def test_on_ec2_no_service_publishes_anything_else() -> None:
    assert not [name for name, spec in EC2_SERVICES.items() if "ports" in spec]


def test_no_service_mounts_a_file_of_this_machine() -> None:
    for name, spec in SERVICES.items():
        for volume in spec.get("volumes", []):
            assert volume.split(":")[0] in COMPOSE["volumes"], (name, volume)
        assert "env_file" not in spec, name


def test_every_image_built_here_has_an_ec2_tag_for_arm() -> None:
    built = {name for name, spec in SERVICES.items() if "build" in spec}
    assert built == {"migrate", "nginx", *BACKENDS}
    for name in built:
        assert EC2_SERVICES[name]["image"].endswith(":ec2"), name
        assert EC2_SERVICES[name]["platform"] == "linux/arm64", name


def test_the_long_running_services_restart_on_ec2() -> None:
    restarting = {name for name, spec in EC2_SERVICES.items() if "restart" in spec}
    assert restarting == set(SERVICES) - {"migrate"}


def test_each_role_signs_in_at_its_own_cloudfront_address_on_ec2() -> None:
    for role in ROLES:
        environment = EC2_SERVICES[role]["environment"]
        assert environment["APP_ENV"] == "prod", role
        assert environment["GOOGLE_REDIRECT_URI"] == (
            f"${{EC2_{role.upper()}_URL:?set by scripts/common.sh}}/auth/google/callback"
        )
    calendar = EC2_SERVICES["technician"]["environment"]["GOOGLE_CALENDAR_REDIRECT_URI"]
    assert calendar == "${EC2_TECHNICIAN_URL:?set by scripts/common.sh}/calendar/connect/callback"
    worker = EC2_SERVICES["worker"]["environment"]
    assert worker["TECHNICIAN_APP_URL"] == "${EC2_TECHNICIAN_URL:?set by scripts/common.sh}"


def test_the_network_addresses_override_the_host_forms() -> None:
    for name in (*BACKENDS, "migrate"):
        environment = SERVICES[name]["environment"]
        assert "@db:${DB_PORT" in environment["DATABASE_URL"], name
    for name in BACKENDS:
        environment = SERVICES[name]["environment"]
        assert environment["REDIS_URL"] == "redis://redis:6379/0", name
        assert environment["MINIO_ENDPOINT"] == "objectstore:9000", name


def test_each_container_receives_only_the_keys_it_reads() -> None:
    settings_keys = {_env_name(field) for field in Settings.model_fields}
    for name in BACKENDS:
        assert set(SERVICES[name]["environment"]) == settings_keys | ENVIRONMENT_KEYS, name
        assert SERVICES[name]["environment"]["FSM_ROLE"] == name, name
    assert set(SERVICES["migrate"]["environment"]) == {"DATABASE_URL"}


def test_the_database_user_and_name_come_from_the_settings_in_every_use() -> None:
    db = yaml.dump({"db": SERVICES["db"], "database": COMPOSE["x-database-env"]})
    assert "fsm" not in db.replace("fsm_pgdata", "")


def test_the_object_store_credentials_come_from_the_settings() -> None:
    environment = SERVICES["objectstore"]["environment"]
    assert environment == {
        "RUSTFS_ACCESS_KEY": "${MINIO_ACCESS_KEY:?set in stack-params.sh}",
        "RUSTFS_SECRET_KEY": "${MINIO_SECRET_KEY:?set in secrets.sh}",
    }
