from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1]
DOCKERFILE = APP_DIR / "Dockerfile"
DOCKERIGNORE = APP_DIR / ".dockerignore"
EXPECTED_BASE = (
    "docker.io/library/python@sha256:"
    "afc139a0a640942491ec481ad8dda10f2c5b753f5c969393b12480155fe15a63"
)


def dockerfile_text() -> str:
    return DOCKERFILE.read_text()


def dockerignore_lines() -> set[str]:
    return {
        line.strip()
        for line in DOCKERIGNORE.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }


def test_base_image_is_pinned_by_digest() -> None:
    first_line = dockerfile_text().splitlines()[0]

    assert first_line == f"FROM {EXPECTED_BASE}"
    assert "@sha256:" in first_line


def test_no_latest_tag_is_used() -> None:
    assert ":latest" not in dockerfile_text()


def test_runtime_user_is_non_root_with_uid_10001() -> None:
    contents = dockerfile_text()

    assert "useradd --create-home --uid 10001 app" in contents
    assert "USER app" in contents
    assert "USER root" not in contents


def test_port_8000_is_exposed() -> None:
    assert "EXPOSE 8000" in dockerfile_text()


def test_uvicorn_command_targets_gateway_app() -> None:
    contents = dockerfile_text()

    assert '"uvicorn"' in contents
    assert '"llm_gateway.main:app"' in contents
    assert '"--host", "0.0.0.0"' in contents
    assert '"--port", "8000"' in contents


def test_dockerfile_copies_only_package_inputs() -> None:
    contents = dockerfile_text()

    assert "COPY pyproject.toml ./" in contents
    assert "COPY src ./src" in contents
    assert "COPY tests" not in contents
    assert "COPY . ." not in contents
    assert "ADD . ." not in contents


def test_dockerfile_installs_local_package_without_cache() -> None:
    contents = dockerfile_text()

    assert "pip install --no-cache-dir ." in contents
    assert "pip install --no-cache-dir --upgrade pip" not in contents


def test_dockerignore_contains_required_exclusions() -> None:
    lines = dockerignore_lines()

    assert {
        ".venv/",
        "venv/",
        "__pycache__/",
        "*.py[cod]",
        ".pytest_cache/",
        "tests/",
        ".git/",
        ".vscode/",
        ".idea/",
        ".env",
        ".env.*",
        "htmlcov/",
        ".coverage",
        "coverage.xml",
    }.issubset(lines)
