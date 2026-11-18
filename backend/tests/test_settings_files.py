"""Checks that the settings files document exactly the keys the backend and compose read.

The settings live in three files under scripts/lib/: the committed stack-params.sh, and
params.example.sh and secrets.example.sh, which init-env.sh copies to the gitignored params.sh
and secrets.sh. A key counts as documented when a line of one of them assigns it, commented out
or not (export KEY="value" or # export KEY="value"). Every documented key is a Settings field or a
key that only compose, the logging setup, the settings guard or the EC2 scripts read; FSM_ROLE
alone is set per service by compose. scripts/init-env.sh must fill in every key it owns, leaving
the Google client for the person.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from pydantic import AliasChoices

from fsm.platform.config import SETTINGS_FILES, Settings
from fsm.platform.logging import ENV_PREFIX

REPO = Path(__file__).resolve().parents[2]
LIB = REPO / "scripts" / "lib"
STACK_PARAMS = LIB / "stack-params.sh"
EXAMPLES = (LIB / "params.example.sh", LIB / "secrets.example.sh")
SCRIPTS = REPO / "scripts"

COMPOSE_ONLY_KEYS = {
    "EDGE_TECHNICIAN_HOST_PORT",
    "EDGE_CUSTOMER_HOST_PORT",
    "EDGE_BACKOFFICE_HOST_PORT",
    "DB_PORT",
    "DB_HOST_PORT",
    "REDIS_HOST_PORT",
    "OBJECT_STORE_HOST_PORT",
    "POSTGRES_USER",
    "POSTGRES_DB",
    "POSTGRES_PASSWORD",
}
# Read by fsm.core.logging.configure_logging from the process environment.
LOGGING_KEYS = {f"{ENV_PREFIX}LOG_LEVEL", f"{ENV_PREFIX}LOG_LEVELS"}
# Read by scripts/lib/settings-guard.sh only: the address tracked files may show.
GUARD_ONLY_KEYS = {"LICENSE_CONTACT"}
# Read by scripts/lib/ec2.sh only, for deploy.sh --ec2.
EC2_ONLY_KEYS = {"EC2_STACK", "EC2_HOST_STACK"}
NOT_SETTINGS_KEYS = COMPOSE_ONLY_KEYS | LOGGING_KEYS | GUARD_ONLY_KEYS | EC2_ONLY_KEYS
# Set by compose per service, and by hand for a process started on the host.
SERVICE_SET_KEYS = {"FSM_ROLE"}

_ASSIGNMENT = re.compile(r"^(?:#\s*)?export ([A-Z][A-Z0-9_]*)=", re.MULTILINE)


def _documented_keys() -> set[str]:
    text = "".join(path.read_text(encoding="utf-8") for path in (STACK_PARAMS, *EXAMPLES))
    return set(_ASSIGNMENT.findall(text))


def _env_keys() -> dict[str, str]:
    """Key: a Settings field. Value: the variable it is read from, its first alias or its name."""
    keys = {}
    for name, field in Settings.model_fields.items():
        alias = field.validation_alias
        key = alias.choices[0] if isinstance(alias, AliasChoices) else name
        assert isinstance(key, str)
        keys[name] = key.upper()
    return keys


def _settings_keys() -> set[str]:
    return set(_env_keys().values())


def _exported_by(*files: Path) -> dict[str, str]:
    """The variables a shell holds after sourcing the files in order, as the scripts do."""
    sources = "; ".join(f'source "{path}"' for path in files)
    output = subprocess.run(
        ["bash", "-c", f"{sources}; env -0"], check=True, capture_output=True, env={}
    ).stdout.decode()
    return dict(entry.split("=", 1) for entry in output.split("\0") if "=" in entry)


def test_the_settings_files_are_the_ones_the_backend_reads() -> None:
    assert [REPO / name for name in SETTINGS_FILES] == [
        STACK_PARAMS,
        LIB / "params.sh",
        LIB / "secrets.sh",
    ]


def test_every_settings_field_is_documented() -> None:
    missing = sorted(_settings_keys() - SERVICE_SET_KEYS - _documented_keys())
    assert not missing, f"Settings fields missing from the settings files: {missing}"


def test_every_key_only_other_readers_take_is_documented() -> None:
    assert NOT_SETTINGS_KEYS <= _documented_keys()


def test_no_documented_key_is_unknown() -> None:
    unknown = sorted(_documented_keys() - _settings_keys() - NOT_SETTINGS_KEYS)
    assert not unknown, f"The settings files document keys nothing reads: {unknown}"


def test_no_secret_is_committed_in_the_stack_parameters() -> None:
    committed = set(_ASSIGNMENT.findall(STACK_PARAMS.read_text(encoding="utf-8")))
    secret = {
        _env_keys()[name]
        for name, field in Settings.model_fields.items()
        if "SecretStr" in str(field.annotation)
    } | {"POSTGRES_PASSWORD"}
    assert not committed & secret


def test_init_env_writes_the_settings_it_owns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    (root / "scripts" / "lib").mkdir(parents=True)
    for script in ("common.sh", "init-env.sh"):
        shutil.copy(SCRIPTS / script, root / "scripts" / script)
    for path in (
        STACK_PARAMS,
        LIB / "settings-guard.sh",
        LIB / "ec2.sh",
        LIB / "aws-config.example.sh",
        *EXAMPLES,
    ):
        shutil.copy(path, root / "scripts" / "lib" / path.name)
    subprocess.run([str(root / "scripts" / "init-env.sh")], check=True, capture_output=True)
    created = [root / name for name in SETTINGS_FILES]
    for path in created[1:]:
        assert path.stat().st_mode & 0o077 == 0, path.name
    env = _exported_by(*created)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    settings = Settings()  # type: ignore[call-arg]
    password = env["POSTGRES_PASSWORD"]
    assert len(password) == 32
    assert settings.database_url.get_secret_value() == (
        f"postgresql+psycopg://{env['POSTGRES_USER']}:{password}"
        f"@127.0.0.1:{env['DB_HOST_PORT']}/{env['POSTGRES_DB']}"
    )
    assert settings.session_secret is not None
    assert len(settings.session_secret.get_secret_value()) == 64
    assert settings.fsm_token_key is not None
    Fernet(settings.fsm_token_key.get_secret_value())
    assert len(settings.minio_secret_key.get_secret_value()) == 40
    # The keys init-env.sh leaves for the person to supply.
    assert settings.google_client_id is None
    assert settings.google_client_secret is None
