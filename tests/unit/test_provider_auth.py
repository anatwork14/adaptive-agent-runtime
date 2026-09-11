"""Tests for vendor-native ARC authentication orchestration."""

from __future__ import annotations

from types import SimpleNamespace

from adapters.antigravity import AntigravityAgentAdapter
from application import auth
from application.agents import build_agent
from application.config import AgentProfile


def test_provider_aliases_and_commands() -> None:
    assert auth.get_auth_spec("openai").provider == "codex"
    assert auth.get_auth_spec("anthropic").provider == "claude"
    assert auth.get_auth_spec("agy").provider == "antigravity"
    assert auth.get_auth_spec("codex").status_command == ("codex", "login", "status")
    assert auth.get_auth_spec("claude").login_command == ("claude", "auth", "login")
    assert auth.get_auth_spec("antigravity").login_command == ("agy",)


def test_auth_status_missing_executable(monkeypatch) -> None:
    monkeypatch.setattr(auth.shutil, "which", lambda _name: None)
    result = auth.auth_status("codex")
    assert result.state == "MISSING"
    assert result.installed is False
    assert result.authenticated is False


def test_auth_status_success_and_redaction(monkeypatch) -> None:
    monkeypatch.setattr(auth.shutil, "which", lambda name: f"/usr/bin/{name}")

    def fake_run(*_args, **_kwargs):
        return SimpleNamespace(returncode=0, stdout="Logged in using ChatGPT sk-secret-value", stderr="")

    monkeypatch.setattr(auth.subprocess, "run", fake_run)
    result = auth.auth_status("codex")
    assert result.state == "AUTHENTICATED"
    assert result.installed is True
    assert result.authenticated is True
    assert "sk-secret-value" not in result.detail
    assert "[redacted]" in result.detail


def test_auth_status_signed_out(monkeypatch) -> None:
    monkeypatch.setattr(auth.shutil, "which", lambda name: f"/usr/bin/{name}")

    def fake_run(*_args, **_kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr="Not logged in")

    monkeypatch.setattr(auth.subprocess, "run", fake_run)
    result = auth.auth_status("claude")
    assert result.state == "SIGNED_OUT"
    assert result.installed is True
    assert result.authenticated is False


def test_antigravity_profile_builds_real_adapter() -> None:
    profile = AgentProfile(name="researcher", provider="antigravity", role="research")
    adapter = build_agent(profile)
    assert isinstance(adapter, AntigravityAgentAdapter)
