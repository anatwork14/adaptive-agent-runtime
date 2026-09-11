"""Compact Codex/Claude/Antigravity-style provider picker for `arc login`."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.containers import Container
from textual.widgets import Footer, Label, ListItem, ListView, Static

from application.auth import auth_status, supported_auth_providers


class ProviderLoginPicker(App[str | None]):
    """Arrow-key login-method chooser that exits before vendor OAuth starts."""

    TITLE = "ARC Login"
    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("q", "cancel", "Cancel"),
    ]

    CSS = """
    Screen {
        background: #090d14;
        color: #e9eef7;
        align: center middle;
    }
    #frame {
        width: 72;
        height: auto;
        border: solid #28334a;
        background: #0f1420;
        padding: 1 2;
    }
    #brand {
        color: #22d3ee;
        text-style: bold;
        margin-bottom: 1;
    }
    #intro, #hint {
        color: #9cacc5;
        margin-bottom: 1;
    }
    ListView {
        height: auto;
        max-height: 12;
        border: none;
        background: #0f1420;
    }
    ListItem {
        padding: 1 2;
        color: #e9eef7;
    }
    ListItem.--highlight {
        background: #1a3140;
        color: #67e8f9;
        text-style: bold;
    }
    #hint {
        margin-top: 1;
        text-align: center;
    }
    Footer {
        background: #141b29;
        color: #9cacc5;
    }
    """

    def compose(self) -> ComposeResult:
        specs = supported_auth_providers()
        items: list[ListItem] = []
        for spec in specs:
            status = auth_status(spec.provider)
            marker = "● signed in" if status.authenticated else "○ sign in" if status.installed else "× not installed"
            items.append(
                ListItem(
                    Label(f"{spec.display_name}   ·   {spec.auth_method}   ·   {marker}"),
                    id=spec.provider,
                )
            )
        with Container(id="frame"):
            yield Static("ARC  ·  CONNECT PROVIDER", id="brand")
            yield Static("Select login method", id="intro")
            yield ListView(*items, initial_index=0)
            yield Static("↑/↓ Navigate   Enter Confirm   Esc Cancel", id="hint")
        yield Footer()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        self.exit(event.item.id)

    def action_cancel(self) -> None:
        self.exit(None)


def choose_login_provider() -> str | None:
    """Run the picker and return the provider identifier."""
    return ProviderLoginPicker().run()
