"""CLI coverage for ARC's provider-native login surface."""

from __future__ import annotations

from typer.testing import CliRunner

import cli.entry as entry
from application.auth import ProviderAuthStatus

runner = CliRunner()


def _status(provider: str, *, authenticated: bool, installed: bool = True) -> ProviderAuthStatus:
    names = {"codex": "OpenAI Codex", "claude": "Claude Code", "antigravity": "Antigravity"}
    return ProviderAuthStatus(
        provider=provider,
        display_name=names[provider],
        installed=installed,
        authenticated=authenticated,
        state="AUTHENTICATED" if authenticated else "SIGNED_OUT" if installed else "MISSING",
        detail="Logged in" if authenticated else "Not logged in",
        executable=f"/usr/bin/{'agy' if provider == 'antigravity' else provider}" if installed else None,
        auth_method="OAuth",
    )


def test_login_and_auth_help_are_product_commands() -> None:
    login_help = runner.invoke(entry.app, ["login", "--help"])
    assert login_help.exit_code == 0
    assert "provider" in login_help.output.lower()

    auth_help = runner.invoke(entry.app, ["auth", "--help"])
    assert auth_help.exit_code == 0
    assert "status" in auth_help.output.lower()


def test_login_delegates_to_provider_native_flow(monkeypatch, tmp_path) -> None:
    statuses = iter([_status("codex", authenticated=False), _status("codex", authenticated=True)])
    monkeypatch.setattr(entry, "auth_status", lambda _provider: next(statuses))
    called = []
    monkeypatch.setattr(entry, "login_provider", lambda provider, cwd=".": called.append((provider, str(cwd))) or 0)

    result = runner.invoke(entry.app, ["login", "codex", "--repo", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert called and called[0][0] == "codex"
    assert "Signed in" in result.output


def test_auth_status_does_not_require_project(monkeypatch) -> None:
    monkeypatch.setattr(entry, "auth_status", lambda provider: _status(provider, authenticated=True))
    result = runner.invoke(entry.app, ["auth", "status"])
    assert result.exit_code == 0, result.output
    assert "OpenAI Codex" in result.output
    assert "Claude Code" in result.output
    assert "Antigravity" in result.output
