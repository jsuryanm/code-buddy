"""Static checks of the Docker files. Nothing here builds or runs Docker."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from codebuddy.config import Settings

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).parents[2]
DOCKERFILE = (ROOT / "Dockerfile").read_text()
COMPOSE_TEXT = (ROOT / "docker-compose.yml").read_text()
COMPOSE = yaml.safe_load(COMPOSE_TEXT)
IGNORE = [
    line.strip()
    for line in (ROOT / ".dockerignore").read_text().splitlines()
    if line.strip() and not line.startswith("#")
]
CLIENT_ONLY = {"CODEBUDDY_API_URL", "CODEBUDDY_API_KEY"}


def test_compose_parses_with_expected_services():
    assert {"qdrant", "api", "ui", "api-demo", "ingest"} <= set(COMPOSE["services"])
    assert COMPOSE["services"]["api-demo"]["profiles"] == ["demo"]
    assert COMPOSE["services"]["ingest"]["profiles"] == ["ingest"]


def test_image_runs_as_non_root():
    users = re.findall(r"^USER (\S+)", DOCKERFILE, re.M)
    assert users and users[-1] not in {"root", "0"}
    for name in ("api", "ui", "ingest", "api-demo"):
        assert "user" not in COMPOSE["services"][name], "compose must not override the user"


def test_published_ports_bind_loopback():
    for name, svc in COMPOSE["services"].items():
        for port in svc.get("ports", []):
            assert str(port).startswith("127.0.0.1:"), f"{name}: {port}"


def test_no_secret_literals():
    pattern = re.compile(r"sk-[A-Za-z0-9]{8,}|gsk_[A-Za-z0-9]{8,}|pk-lf-|sk-lf-|AKIA[0-9A-Z]{12}")
    for text in (COMPOSE_TEXT, DOCKERFILE):
        assert not pattern.search(text)
    for name, svc in COMPOSE["services"].items():
        env = svc.get("environment", {})
        for key, value in env.items():
            if re.search(r"KEY|TOKEN|SECRET|PASSWORD", key):
                assert str(value).startswith("${") or value == "", f"{name}.{key} is literal"


def test_codebuddy_env_vars_exist_in_settings():
    fields = {n.lower() for n in Settings.model_fields}
    names = set(re.findall(r"CODEBUDDY_[A-Z0-9_]+", COMPOSE_TEXT + DOCKERFILE)) - CLIENT_ONLY
    assert names
    for name in names:
        assert name.removeprefix("CODEBUDDY_").lower() in fields, name


def test_dockerfile_has_healthcheck_extras_and_baked_model():
    assert re.search(r"^HEALTHCHECK ", DOCKERFILE, re.M)
    assert re.search(r'^ARG EXTRAS="--extra ui --extra trace"', DOCKERFILE, re.M)
    code = "\n".join(ln for ln in DOCKERFILE.splitlines() if not ln.lstrip().startswith("#"))
    assert "ragas" not in code.lower()
    assert "FASTEMBED_CACHE_PATH=/app/.cache/fastembed" in DOCKERFILE
    assert "Qdrant/bm25" in DOCKERFILE
    assert "COPY .streamlit" in DOCKERFILE


def test_ui_healthcheck_overrides_api_one():
    assert "_stcore/health" in str(COMPOSE["services"]["ui"]["healthcheck"])
    assert "depends_on" in COMPOSE["services"]["api"]


def test_dockerignore_rules():
    for needed in (".env", "logs/", "data/raw/", ".venv/", "tests/", "evals/"):
        assert needed in IGNORE, needed
    assert not any(line.strip("/*") == ".streamlit" for line in IGNORE)
