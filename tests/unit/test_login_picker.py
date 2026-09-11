"""Headless coverage for the interactive ARC login method picker."""

from __future__ import annotations

import pytest

import tui.login as login_ui
from application.auth import ProviderAuthStatus
from tui.login import ProviderLoginPicker


@pytest.mark.asyncio
async def test_provider_picker_selects_highlighted_provider(monkeypatch) -> None:
    def fake_status(provider: str) -> ProviderAuthStatus:
        return ProviderAuthStatus(
            provider=provider,
            display_name=provider,
            installed=True,
            authenticated=False,
            state="SIGNED_OUT",
            detail="not signed in",
            executable=f"/usr/bin/{provider}",
            auth_method="OAuth",
        )

    monkeypatch.setattr(login_ui, "auth_status", fake_status)
    picker = ProviderLoginPicker()
    async with picker.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
    assert picker.return_value == "codex"
