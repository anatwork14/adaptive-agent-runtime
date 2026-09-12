"""Security regression coverage for ARC's unauthenticated browser control planes."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from application.app import ArcApplication
from application.session_app import SessionArcApplication
from webui.local_security import is_loopback_host, is_loopback_origin
from webui.server import create_web_app, run_web
from webui.workspace_server import create_workspace_app, run_workspace


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "arc@example.test"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "ARC Test"], check=True)
    (repo / "README.md").write_text("# secure local control plane\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "initial"], check=True)
    subprocess.run(["git", "-C", str(repo), "branch", "-M", "main"], check=True)
    return repo


def test_loopback_policy_handles_ipv4_ipv6_and_browser_origins() -> None:
    assert is_loopback_host("127.0.0.1")
    assert is_loopback_host("::1")
    assert is_loopback_host("[::1]")
    assert is_loopback_host("localhost")
    assert not is_loopback_host("0.0.0.0")
    assert not is_loopback_host("::")
    # DNS aliases are deliberately not trusted even if they might resolve to
    # loopback at some point in time. This keeps the Origin policy fail-closed.
    assert not is_loopback_host("loopback.example")

    assert is_loopback_origin(None)
    assert is_loopback_origin("http://127.0.0.1:8788")
    assert is_loopback_origin("http://localhost:8788")
    assert is_loopback_origin("http://[::1]:8788")
    assert not is_loopback_origin("https://evil.example")
    assert not is_loopback_origin("http://loopback.example:8788")
    assert not is_loopback_origin("null")


def test_browser_http_origin_guard_blocks_cross_site_control(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    with SessionArcApplication(repo, "workspace-security") as arc:
        arc.initialize()
    with ArcApplication(repo, "mission-security") as arc:
        arc.initialize()

    workspace = TestClient(create_workspace_app(repo=repo, project_id="workspace-security"))
    mission = TestClient(create_web_app(repo=repo, project_id="mission-security"))

    hostile = {"Origin": "https://evil.example"}
    assert workspace.get("/api/health", headers=hostile).status_code == 403
    assert mission.get("/api/health", headers=hostile).status_code == 403

    local = {"Origin": "http://127.0.0.1:8788"}
    assert workspace.get("/api/health", headers=local).status_code == 200
    assert mission.get("/api/health", headers=local).status_code == 200

    # Non-browser clients are still supported because they normally omit Origin.
    assert workspace.get("/api/health").status_code == 200
    assert mission.get("/api/health").status_code == 200


def test_workspace_websocket_rejects_cross_site_origin(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    with SessionArcApplication(repo, "workspace-ws-security") as arc:
        arc.initialize()

    client = TestClient(create_workspace_app(repo=repo, project_id="workspace-ws-security"))
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(
            "/ws/events?after=0",
            headers={"Origin": "https://evil.example"},
        ):
            pass
    assert exc.value.code == 1008


def test_mission_websocket_rejects_cross_site_origin(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    with ArcApplication(repo, "mission-ws-security") as arc:
        arc.initialize()

    client = TestClient(create_web_app(repo=repo, project_id="mission-ws-security"))
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(
            "/ws/events?after=0",
            headers={"Origin": "https://evil.example"},
        ):
            pass
    assert exc.value.code == 1008


def test_legacy_remote_opt_in_no_longer_bypasses_local_boundary(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    expected = "only bind to loopback"

    with pytest.raises(ValueError, match=expected):
        run_workspace(repo=repo, host="0.0.0.0", port=8788, allow_remote=True)
    with pytest.raises(ValueError, match=expected):
        run_web(repo=repo, host="0.0.0.0", port=8787, allow_remote=True)


def test_browser_app_versions_match_security_patch(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    with SessionArcApplication(repo, "workspace-version") as arc:
        arc.initialize()
    with ArcApplication(repo, "mission-version") as arc:
        arc.initialize()

    assert create_workspace_app(repo=repo, project_id="workspace-version").version == "0.9.1"
    assert create_web_app(repo=repo, project_id="mission-version").version == "0.9.1"
