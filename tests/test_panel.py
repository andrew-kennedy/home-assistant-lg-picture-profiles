import asyncio
import hashlib
import inspect
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.exceptions import Unauthorized

from custom_components.lg_picture_profiles import panel as panel_module
from custom_components.lg_picture_profiles.panel import editor_command

from .test_manager import backup


async def test_panel_requires_admin_before_command(manager):
    connection = SimpleNamespace(user=SimpleNamespace(is_admin=False))
    with pytest.raises(Unauthorized):
        editor_command(
            manager.hass, connection, {"id": 1, "entry_id": "test", "command": {"action": "get"}}
        )
    assert not manager.transport.calls


async def test_editor_export_offline_and_explicit_revision(manager):
    manager.hass.data["lg_picture_profiles"] = {"test": manager}
    await manager._accept_backup(backup())
    connection = SimpleNamespace(
        user=SimpleNamespace(is_admin=True), send_result=Mock(), send_error=Mock()
    )
    manager.transport.available = False
    editor_command(
        manager.hass, connection, {"id": 1, "entry_id": "test", "command": {"action": "backup"}}
    )
    await asyncio.sleep(0)
    assert connection.send_result.call_args.args[1] == manager.saved["backup"]
    manager.transport.available = True
    editor_command(
        manager.hass,
        connection,
        {
            "id": 2,
            "entry_id": "test",
            "command": {"action": "restore_backup", "backup": backup(), "revision": 15},
        },
    )
    await asyncio.sleep(0)
    assert manager.transport.calls[-1][1]["revision"] == 15
    editor_command(
        manager.hass, connection, {"id": 3, "entry_id": "test", "command": {"action": "raw_luna"}}
    )
    await asyncio.sleep(0)
    assert connection.send_error.call_args.args[1] == "profile_error"


def test_vendored_editor_has_recorded_digest():
    root = Path(__file__).parents[1] / "custom_components/lg_picture_profiles/frontend"
    metadata = json.loads((root / "editor-source.json").read_text())
    assert set(metadata["files"]) == {"profile-view.js", "profile-editor.js"}
    for name, source in metadata["files"].items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == source["sha256"]
    panel = (root / "panel.js").read_text()
    assert panel.index("import './profile-view.js") < panel.index("import './profile-editor.js")


async def test_panel_handles_safe_area_itself(monkeypatch):
    # Home Assistant would otherwise pad the panel by the device safe areas around a
    # panel that is already one screen tall, so the app page scrolls (pull to refresh)
    # and the review row falls below the screen.
    real = panel_module.panel_custom.async_register_panel
    assert "handle_safe_area" in inspect.signature(real).parameters
    register = AsyncMock()
    monkeypatch.setattr(panel_module.panel_custom, "async_register_panel", register)
    hass = SimpleNamespace(data={panel_module.REGISTERED: True})
    entry = SimpleNamespace(entry_id="ABC", title="LG Picture Profiles")
    await panel_module.async_register(hass, entry)
    options = register.call_args.kwargs
    assert options["handle_safe_area"] is True
    assert options["embed_iframe"] is False
    root = Path(__file__).parents[1] / "custom_components/lg_picture_profiles/frontend"
    style = (root / "panel.js").read_text()
    assert "box-sizing:border-box;height:100vh;height:100dvh;" in style
    for inset in ("--safe-area-inset-top", "--safe-area-inset-bottom", "--safe-area-inset-left", "--safe-area-inset-right"):
        assert "var(" + inset + ",0px)" in style


async def test_editor_forwards_atomic_batch_and_exact_selection(manager):
    manager.hass.data["lg_picture_profiles"] = {"test": manager}
    await manager._accept_backup(backup())
    manager.transport.available = True
    connection = SimpleNamespace(
        user=SimpleNamespace(is_admin=True), send_result=Mock(), send_error=Mock()
    )
    for command in [
        {
            "action": "edit_many",
            "revision": 7,
            "edits": [
                {
                    "bank_id": "movie",
                    "variant": "dark",
                    "settings": {"color": 50},
                    "inherit": ["backlight"],
                }
            ],
        },
        {
            "action": "edit_many",
            "revision": 4,
            "edits": [{"bank_id": "movie", "variant": "dark", "settings": {"realCinema": "on"}}],
            "preferences": {"movie_dark": 3},
        },
        {
            "action": "save",
            "revision": 5,
            "room": "dark",
            "selection": {"movie": ["realCinema"]},
            "expected": {"movie": {"realCinema": "on"}},
        },
    ]:
        editor_command(manager.hass, connection, {"id": 4, "entry_id": "test", "command": command})
        await asyncio.sleep(0)
        assert manager.transport.calls[-1] == (
            command["action"],
            {k: v for k, v in command.items() if k != "action"},
        )
    connection.send_error.assert_not_called()


async def test_editor_forwards_named_catalog_commands(manager):
    manager.hass.data["lg_picture_profiles"] = {"test": manager}
    connection = SimpleNamespace(
        user=SimpleNamespace(is_admin=True), send_result=Mock(), send_error=Mock()
    )
    for action in (
        "upgrade_profiles",
        "create_profile",
        "rename_profile",
        "delete_profile",
        "reset_profile",
        "set_automatic",
        "apply_profile",
    ):
        command = {"action": action, "revision": 7, "profile_id": "p_evening"}
        editor_command(manager.hass, connection, {"id": 7, "entry_id": "test", "command": command})
        await asyncio.sleep(0)
        assert manager.transport.calls[-1] == (action, {"revision": 7, "profile_id": "p_evening"})
    connection.send_error.assert_not_called()
