from __future__ import annotations

import subprocess

import pytest

from isolation import container
from isolation.container import SandboxRunner, SandboxUnavailable

IMAGE_DIGEST = "sha256:" + "a" * 64


def _fake_docker(monkeypatch, *, image_id: str | None = IMAGE_DIGEST, image_rc: int = 0):
    calls: list[list[str]] = []

    monkeypatch.setattr(container.shutil, "which", lambda name: "/fake/docker")

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[1:3] == ["info", "--format"]:
            return subprocess.CompletedProcess(command, 0, stdout="27.0\n", stderr="")
        if command[1:3] == ["image", "inspect"]:
            return subprocess.CompletedProcess(
                command,
                image_rc,
                stdout=(f"{image_id}\n" if image_id else ""),
                stderr="missing image\n" if image_rc else "",
            )
        raise AssertionError(command)

    monkeypatch.setattr(container.subprocess, "run", fake_run)
    return calls


def test_verify_available_accepts_correct_docker_identity(monkeypatch, tmp_path):
    calls = _fake_docker(monkeypatch)
    runner = SandboxRunner(tmp_path, image="arc-qualified:test", image_digest=IMAGE_DIGEST)

    report = runner.verify_available()

    assert report["backend"] == "docker"
    assert report["actual_image_digest"] == IMAGE_DIGEST
    assert report["ready"] is True
    assert [call[1] for call in calls] == ["info", "image"]


def test_verify_available_blocks_wrong_digest(monkeypatch, tmp_path):
    _fake_docker(monkeypatch, image_id="sha256:" + "b" * 64)
    runner = SandboxRunner(tmp_path, image="arc-qualified:test", image_digest=IMAGE_DIGEST)

    with pytest.raises(SandboxUnavailable, match="identity mismatch"):
        runner.verify_available()


def test_verify_available_blocks_missing_image(monkeypatch, tmp_path):
    _fake_docker(monkeypatch, image_id=None, image_rc=1)
    runner = SandboxRunner(tmp_path, image="arc-qualified:test", image_digest=IMAGE_DIGEST)

    with pytest.raises(SandboxUnavailable, match="cannot be inspected"):
        runner.verify_available()


def test_verify_available_blocks_unusable_docker(monkeypatch, tmp_path):
    monkeypatch.setattr(container.shutil, "which", lambda name: "/fake/docker")

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="daemon unavailable")

    monkeypatch.setattr(container.subprocess, "run", fake_run)
    runner = SandboxRunner(tmp_path, image="arc-qualified:test", image_digest=IMAGE_DIGEST)

    with pytest.raises(SandboxUnavailable, match="daemon is unavailable"):
        runner.verify_available()
