from unittest.mock import AsyncMock

from custom_components.lg_picture_profiles.backup import decode

from .test_manager import backup


async def test_offline_preview_preserves_full_saved_state_without_writes(manager):
    envelope = backup(
        overrides={"game_hdr": {"gameSharpness": 7}},
        recovery={
            "dirty": {"game_hdr": ["gameSharpness"]},
            "restore": {"game_hdr": ["gameSharpness"]},
            "power": "off",
            "boot_id": "boot",
        },
    )
    await manager._accept_backup(envelope)
    manager.transport.available = False
    writes = manager.store.saves
    preview = await manager.async_preview()
    assert preview == {
        "state": decode(envelope),
        "status": {"offline": True, "error": None},
    }
    assert manager.store.saves == writes
    assert not manager.transport.calls
    preview["state"]["document"]["name"] = "Changed response"
    assert manager.document["name"] == "Living room"


async def test_live_preview_reads_one_cached_bridge_snapshot_without_writes(manager):
    snapshot = {"state": decode(backup()), "status": {"power": "on", "applying": False}}
    manager.transport.async_command = AsyncMock(return_value=snapshot)
    writes = manager.store.saves
    result = await manager.async_preview()
    manager.transport.async_command.assert_awaited_once_with("get")
    assert result == snapshot
    assert manager.store.saves == writes
