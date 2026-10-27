from copy import deepcopy
from types import SimpleNamespace

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.lg_picture_profiles.manager import ProfileManager

from .conftest import MemoryStore, adjust


async def test_context_switch_restores_original_hdr_bank(manager):
    await adjust(manager, "game_hdr", "gameSharpness", 10)
    assert manager.override_count == 1
    manager.context = {
        "input": "hdmi3",
        "mode": "dolbyHdrCinema",
        "range": "dolbyHdr",
        "ready": True,
    }
    result = await manager.async_restore()
    assert result["changed_settings"] == 1
    assert manager.transport.values["game_hdr"]["gameSharpness"] == 0
    assert not manager.override_count
    writes = [b for action, banks in manager.transport.calls if action == "apply" for b in banks]
    assert len(writes) == 1
    assert writes[0]["target"]["dimension"]["dynamicRange"] == "hdrALLM"


async def test_override_survives_day_change_then_restores_current_standard(manager):
    await manager.async_reconcile()
    await adjust(manager, "movie_sdr", "backlight", 25)
    manager.hass.states.async_set("sun.sun", "above_horizon")
    await manager.async_reconcile()
    assert manager.transport.values["movie_sdr"]["backlight"] == 25
    assert manager.transport.values["movie_sdr"]["peakBrightness"] == "high"
    assert manager.transport.values["dv_mapping"]["pictureMode"] == "dolbyHdrCinemaBright"
    await manager.async_restore()
    assert manager.transport.values["movie_sdr"]["backlight"] == 100


async def test_duplicate_results_do_not_change_storage_or_baseline(manager):
    baseline = deepcopy(manager.document)
    await adjust(manager, "game_hdr", "gameColorDepth", 55)
    count = manager.store.saves
    await adjust(manager, "game_hdr", "gameColorDepth", 55)
    assert manager.store.saves == count
    assert manager.document == baseline


async def test_no_redundant_wake_or_reconnect_reads_and_writes(manager):
    await manager.async_reconcile()
    manager.transport.calls.clear()
    for _ in range(3):
        assert await manager.async_reconcile() == {"changed_settings": 0}
    assert manager.transport.calls == []


async def test_restart_preserves_adjustment_until_a_confirmed_off(manager):
    await manager.async_reconcile()
    await adjust(manager, "game_hdr", "gameColorDepth", 60)
    restored = ProfileManager(
        manager.hass, manager.entry, transport=manager.transport, store=MemoryStore(manager.data)
    )
    restored._schedule_sync = lambda: None
    await restored.async_start()
    assert restored.override_count == 1
    assert not restored.data["pending_restore"]
    await restored.async_reconcile()
    assert restored.transport.values["game_hdr"]["gameColorDepth"] == 60
    manager.hass.states.async_set("media_player.tv", "off")
    await restored._handle_state(
        SimpleNamespace(data={"new_state": manager.hass.states.get("media_player.tv")})
    )
    assert restored.data["pending_restore"]
    manager.hass.states.async_set("media_player.tv", "on")
    restored.context = {
        "input": "hdmi3",
        "mode": "dolbyHdrCinema",
        "range": "dolbyHdr",
        "ready": True,
    }
    await restored.async_reconcile()
    assert restored.transport.values["game_hdr"]["gameColorDepth"] == 50
    assert not restored.override_count
    await restored.async_stop()


async def test_failure_keeps_pending_restore_for_retry(manager):
    await adjust(manager, "game_hdr", "gameSharpness", 15)
    manager.data["pending_restore"] = True
    manager.transport.fail_apply = True
    with pytest.raises(HomeAssistantError):
        await manager.async_reconcile()
    assert manager.override_count == 1 and manager.data["pending_restore"]
    manager.transport.fail_apply = False
    await manager.async_reconcile()
    assert not manager.override_count and not manager.data["pending_restore"]


async def test_save_is_explicit_and_context_scoped(manager):
    await adjust(manager, "game_hdr", "gameSharpness", 4)
    await adjust(manager, "movie_sdr", "color", 55, "user-2")
    result = await manager.async_save_standard()
    assert result == {"saved_settings": 1}
    assert manager.document["banks"][1]["settings"]["gameSharpness"] == 4
    assert manager.document["banks"][0]["settings"]["color"] == "50"
    assert manager.override_count == 1


async def test_new_user_adjustment_during_snapshot_wins_over_environment(manager):
    manager.hass.states.async_set("sun.sun", "above_horizon")

    async def during_read():
        await adjust(manager, "movie_sdr", "backlight", 35, "concurrent")

    manager.transport.on_read = during_read
    await manager.async_reconcile()
    assert manager.transport.values["movie_sdr"]["backlight"] == 35
    assert manager.data["overrides"]["movie_sdr"]["backlight"] == 35


async def test_new_user_adjustment_during_restore_is_not_forgotten(manager):
    await adjust(manager, "game_hdr", "gameSharpness", 10)
    manager.data["pending_restore"] = True

    async def after_write():
        await adjust(manager, "game_hdr", "gameSharpness", 10, "new-same-value")

    manager.transport.on_apply = after_write
    await manager.async_reconcile()
    assert manager.override_count == 1
    assert manager.transport.values["game_hdr"]["gameSharpness"] == 10
    assert not manager.data["pending_restore"]


async def test_offline_restore_persists_then_restores_all_managed_banks(manager):
    manager.hass.states.async_set("media_player.tv", "off")
    assert await manager.async_restore() == {"deferred": True}
    assert manager.store.saved["pending_restore"]
    manager.transport.values["game_hdr"]["gameSharpness"] = 17
    manager.hass.states.async_set("media_player.tv", "on")
    await manager.async_reconcile()
    assert manager.transport.values["game_hdr"]["gameSharpness"] == 0


async def test_preview_does_not_write(manager):
    await adjust(manager, "game_hdr", "gameSharpness", 5)
    manager.transport.calls.clear()
    result = await manager.async_preview()
    assert result["differences"][0]["settings"]["gameSharpness"]["temporary"] is True
    assert all(action == "read" for action, _ in manager.transport.calls)


async def test_unknown_availability_does_not_end_session(manager):
    await adjust(manager, "game_hdr", "gameColorDepth", 53)
    manager.hass.states.async_set("media_player.tv", "unavailable")
    await manager._handle_state(
        SimpleNamespace(data={"new_state": manager.hass.states.get("media_player.tv")})
    )
    assert not manager.data["pending_restore"]
