import json
import os
import subprocess
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "import-k3d-image-digest.sh"
DIGEST = "sha256:" + "a" * 64
IMAGE = "karyaquest/llm-gateway:dev-123"


@pytest.fixture
def fake_tools(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "commands.jsonl"
    state = tmp_path / "state"
    state.mkdir()

    sudo = bin_dir / "sudo"
    sudo.write_text(
        """#!/usr/bin/env python3
import json, os, pathlib, sys
log = pathlib.Path(os.environ['FAKE_LOG'])
with log.open('a') as f:
    f.write(json.dumps(sys.argv[1:]) + '\\n')
args = sys.argv[1:]
fail = os.environ.get('FAKE_FAIL', '')
if fail and ' '.join(args).startswith(fail):
    sys.exit(19)
if args[:3] == ['k3d', 'cluster', 'list']:
    print(os.environ.get('FAKE_CLUSTERS', 'dev 1/1 0/0'))
elif args[:3] == ['k3d', 'node', 'list']:
    print(os.environ.get('FAKE_NODES', 'k3d-dev-server-0 server dev running'))
elif args[:3] == ['k3d', 'image', 'import']:
    pass
elif args[:3] == ['docker', 'image', 'inspect']:
    if os.environ.get('FAKE_IMAGE_MISSING') == '1':
        sys.exit(1)
    digest = os.environ.get('FAKE_LOCAL_DIGEST', os.environ['TEST_DIGEST'])
    print(json.dumps(['karyaquest/llm-gateway@' + digest]))
elif len(args) >= 7 and args[:2] == ['docker', 'exec'] and args[3:7] == ['ctr', '--namespace', 'k8s.io', 'images'] and args[7:] == ['list']:
    if os.environ.get('FAKE_NODE_MISSING') == args[2]:
        sys.exit(1)
    digest = os.environ.get('FAKE_NODE_DIGEST', os.environ['TEST_DIGEST'])
    default_list = '\\n'.join([
        'REF TYPE DIGEST SIZE PLATFORMS LABELS',
        f'docker.io/karyaquest/llm-gateway:dev-123 application/vnd.oci.image.manifest.v1+json {digest} 1.0MiB linux/amd64 -',
        f'registry.example.test:5000/team/gateway:build_1 application/vnd.oci.image.manifest.v1+json {digest} 1.0MiB linux/amd64 -',
    ])
    print(os.environ.get('FAKE_IMAGE_LIST', default_list))
elif len(args) >= 9 and args[:2] == ['docker', 'exec'] and args[3:8] == ['ctr', '--namespace', 'k8s.io', 'images', 'tag']:
    pass
else:
    sys.exit(97)
"""
    )
    sudo.chmod(0o755)
    env = os.environ.copy()
    env.update(
        PATH=f"{bin_dir}:{env['PATH']}",
        FAKE_LOG=str(log),
        TEST_DIGEST=DIGEST,
    )
    return env, log


def run(fake_tools, *args, **env_updates):
    env, _ = fake_tools
    env = env | {key: str(value) for key, value in env_updates.items()}
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        text=True,
        capture_output=True,
        env=env,
        timeout=10,
    )


def commands(fake_tools):
    _, log = fake_tools
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text().splitlines()]


def standard_args(image=IMAGE):
    return ["--image", image, "--digest", DIGEST]


def test_fake_executable_handles_cluster_list_and_multiline_image_list(fake_tools):
    env, _ = fake_tools
    cluster_result = subprocess.run(
        ["sudo", "k3d", "cluster", "list", "--no-headers"],
        text=True,
        capture_output=True,
        env=env,
        timeout=10,
    )
    assert cluster_result.returncode == 0
    assert cluster_result.stdout == "dev 1/1 0/0\n"

    image_list = "\n".join(
        [
            "REF TYPE DIGEST",
            f"docker.io/example/first:tag application/vnd.oci.image.manifest.v1+json {DIGEST}",
            f"docker.io/example/second:tag application/vnd.oci.image.manifest.v1+json {DIGEST}",
        ]
    )
    list_result = subprocess.run(
        ["sudo", "docker", "exec", "k3d-dev-server-0", "ctr", "--namespace", "k8s.io", "images", "list"],
        text=True,
        capture_output=True,
        env=env | {"FAKE_IMAGE_LIST": image_list},
        timeout=10,
    )
    assert list_result.returncode == 0
    assert list_result.stdout == image_list + "\n"


def test_help(fake_tools):
    result = run(fake_tools, "--help")
    assert result.returncode == 0
    assert "Usage:" in result.stdout
    assert commands(fake_tools) == []


@pytest.mark.parametrize("args", [[], ["--image", IMAGE], ["--digest", DIGEST], ["--image"]])
def test_missing_arguments(fake_tools, args):
    result = run(fake_tools, *args)
    assert result.returncode != 0
    assert "Error:" in result.stderr


def test_unknown_argument(fake_tools):
    assert run(fake_tools, *standard_args(), "--wat").returncode != 0


def test_latest_tag_rejected(fake_tools):
    assert run(fake_tools, *standard_args("karyaquest/llm-gateway:latest")).returncode != 0


def test_missing_tag_rejected(fake_tools):
    assert run(fake_tools, *standard_args("karyaquest/llm-gateway")).returncode != 0


@pytest.mark.parametrize("digest", ["sha256:123", "sha512:" + "a" * 64, "sha256:" + "G" * 64])
def test_invalid_digest_rejected(fake_tools, digest):
    result = run(fake_tools, "--image", IMAGE, "--digest", digest)
    assert result.returncode != 0


def test_zero_clusters(fake_tools):
    result = run(fake_tools, *standard_args(), FAKE_CLUSTERS="")
    assert result.returncode != 0
    assert "no k3d clusters" in result.stderr


def test_multiple_clusters(fake_tools):
    result = run(fake_tools, *standard_args(), FAKE_CLUSTERS="one 1/1 0/0\ntwo 1/1 0/0")
    assert result.returncode != 0
    assert "multiple k3d clusters" in result.stderr


def test_explicit_cluster_not_found(fake_tools):
    result = run(fake_tools, *standard_args(), "--cluster", "other")
    assert result.returncode != 0
    assert "cluster not found" in result.stderr


def test_local_image_missing(fake_tools):
    result = run(fake_tools, *standard_args(), FAKE_IMAGE_MISSING=1)
    assert result.returncode != 0
    assert "local image not found" in result.stderr


def test_local_digest_mismatch(fake_tools):
    result = run(fake_tools, *standard_args(), FAKE_LOCAL_DIGEST="sha256:" + "b" * 64)
    assert result.returncode != 0
    assert "digest does not match" in result.stderr


def test_successful_one_cluster_import_and_output(fake_tools):
    result = run(fake_tools, *standard_args())
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "cluster verified",
        "local image verified",
        "image imported",
        "1 nodes verified",
        "digest alias created",
    ]
    assert ["k3d", "image", "import", "-c", "dev", IMAGE] in commands(fake_tools)


def test_docker_hub_normalization(fake_tools):
    result = run(fake_tools, *standard_args())
    assert result.returncode == 0
    calls = commands(fake_tools)
    assert any("docker.io/karyaquest/llm-gateway:dev-123" in call for call in calls)
    assert any(f"docker.io/karyaquest/llm-gateway@{DIGEST}" in call for call in calls)


def test_qualified_registry_is_preserved(fake_tools):
    image = "registry.example.test:5000/team/gateway:build_1"
    result = run(fake_tools, *standard_args(image))
    assert result.returncode == 0
    calls = commands(fake_tools)
    assert any("registry.example.test:5000/team/gateway:build_1" in call for call in calls)
    assert not any("docker.io/registry.example.test" in part for call in calls for part in call)


def test_node_digest_mismatch(fake_tools):
    result = run(fake_tools, *standard_args(), FAKE_NODE_DIGEST="sha256:" + "b" * 64)
    assert result.returncode != 0
    assert "digest mismatch" in result.stderr
    assert not any("tag" in call for call in commands(fake_tools) if call[:2] == ["docker", "exec"])


def test_exact_matching_image_list_row_is_used(fake_tools):
    image_list = "\n".join(
        [
            "REF TYPE DIGEST SIZE PLATFORMS LABELS",
            f"docker.io/karyaquest/llm-gateway:dev-123 application/vnd.oci.image.manifest.v1+json {DIGEST} 1.0MiB linux/amd64 -",
        ]
    )
    result = run(fake_tools, *standard_args(), FAKE_IMAGE_LIST=image_list)
    assert result.returncode == 0


def test_image_tag_missing_from_list(fake_tools):
    image_list = f"REF TYPE DIGEST\ndocker.io/other/image:dev application/vnd.oci.image.manifest.v1+json {DIGEST}"
    result = run(fake_tools, *standard_args(), FAKE_IMAGE_LIST=image_list)
    assert result.returncode != 0
    assert "image tag missing" in result.stderr


def test_similarly_named_repository_does_not_match(fake_tools):
    similar = f"docker.io/karyaquest/llm-gateway-extra:dev-123 application/vnd.oci.image.manifest.v1+json {DIGEST}"
    result = run(fake_tools, *standard_args(), FAKE_IMAGE_LIST=f"REF TYPE DIGEST\n{similar}")
    assert result.returncode != 0
    assert "image tag missing" in result.stderr


def test_extra_unrelated_image_rows_are_ignored(fake_tools):
    wrong_digest = "sha256:" + "b" * 64
    image_list = "\n".join(
        [
            "REF TYPE DIGEST SIZE PLATFORMS LABELS",
            f"docker.io/unrelated/first:tag application/vnd.oci.image.manifest.v1+json {wrong_digest} 1B linux/amd64 -",
            f"docker.io/karyaquest/llm-gateway:dev-123 application/vnd.oci.image.manifest.v1+json {DIGEST} 1B linux/amd64 -",
            f"docker.io/unrelated/last:tag application/vnd.oci.image.manifest.v1+json {wrong_digest} 1B linux/amd64 -",
        ]
    )
    result = run(fake_tools, *standard_args(), FAKE_IMAGE_LIST=image_list)
    assert result.returncode == 0


def test_alias_created_on_server_and_agent_nodes(fake_tools):
    nodes = "k3d-dev-server-0 server dev running\nk3d-dev-agent-0 agent dev running\nk3d-dev-serverlb loadbalancer dev running"
    result = run(fake_tools, *standard_args(), FAKE_NODES=nodes)
    assert result.returncode == 0
    assert "2 nodes verified" in result.stdout
    tag_calls = [call for call in commands(fake_tools) if "tag" in call]
    assert {call[2] for call in tag_calls} == {"k3d-dev-server-0", "k3d-dev-agent-0"}
    assert all(call[-2:] == ["docker.io/karyaquest/llm-gateway:dev-123", f"docker.io/karyaquest/llm-gateway@{DIGEST}"] for call in tag_calls)


@pytest.mark.parametrize(
    "failure",
    [
        "k3d cluster list",
        "docker image inspect",
        "k3d image import",
        "k3d node list",
        "docker exec k3d-dev-server-0 ctr --namespace k8s.io images list",
        "docker exec k3d-dev-server-0 ctr --namespace k8s.io images tag",
    ],
)
def test_command_failure_propagates(fake_tools, failure):
    result = run(fake_tools, *standard_args(), FAKE_FAIL=failure)
    assert result.returncode != 0


def test_repeated_execution_is_idempotent(fake_tools):
    first = run(fake_tools, *standard_args())
    second = run(fake_tools, *standard_args())
    assert first.returncode == second.returncode == 0
    tag_calls = [call for call in commands(fake_tools) if "tag" in call]
    assert len(tag_calls) == 2
    assert all("--force" in call for call in tag_calls)


def test_docker_and_k3d_are_only_invoked_through_sudo(fake_tools):
    result = run(fake_tools, *standard_args())
    assert result.returncode == 0
    assert commands(fake_tools)
    assert all(call[0] in {"docker", "k3d"} for call in commands(fake_tools))


@pytest.mark.parametrize(
    "image",
    ["UPPER/repo:tag", "repo:tag", "host.example/Repo:tag", "host.example/team/:tag", "host.example/team/repo@sha256:bad"],
)
def test_malformed_image_reference_rejected(fake_tools, image):
    assert run(fake_tools, *standard_args(image)).returncode != 0
