import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from homeassistant.exceptions import Unauthorized

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
