from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.lg_picture_profiles.manager import ProfileManager
from custom_components.lg_picture_profiles.model import ProfileError, validate

from .conftest import MemoryStore, adjust, document


async def test_failed_load_does_not_replace_existing_store(manager):
    manager.store.saved = {"document": {"schema": 99}, "enabled": True}
    original = deepcopy(manager.store.saved)
    manager._loaded = False
    with pytest.raises(ProfileError):
        await manager.async_start()
    await manager.async_stop()
    assert manager.store.saved == original


async def test_reenable_does_not_replay_commands_from_disabled_period(manager):
    await manager.async_enable(False)
    timestamp = datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    manager.data["tracked_since"] = "2020-01-01T00:00:00.000Z"
    await manager.async_enable(True)
    assert manager.data["tracked_since"] >= timestamp
    await manager.async_user_results(
        {
            "old": {
                "ok": True,
                "completed_at": "2020-02-01T00:00:00.000Z",
                "applied": {
                    "kind": "user_setting",
                    "target": manager.document["banks"][0]["target"],
                    "key": "color",
                    "value": 70,
                },
            }
        }
    )
    assert manager.override_count == 0


async def test_incompatible_mode_cannot_be_saved_as_standard(manager):
    await adjust(manager, "dv_mapping", "pictureMode", "vivid")
    original = deepcopy(manager.document)
    with pytest.raises(ProfileError, match="signal range"):
        await manager.async_save_standard("all")
    assert manager.document == original
    assert manager.override_count == 1
    await manager.async_restore()
    assert manager.override_count == 0


def test_import_rejects_wrong_signal_family():
    doc = document()
    doc["banks"][2]["settings"]["pictureMode"] = "hdrGame"
    with pytest.raises(ProfileError, match="signal range"):
        validate(doc)


async def test_active_devices_exclude_port_controls_and_missing_signal(manager):
    manager.document["banks"].append(
        {
            "id": "hdmi3_port",
            "name": "HDMI 3 controls",
            "devices": ["switch"],
            "target": {"category": "other", "dimension": {"gameInput": "hdmi3"}},
            "settings": {"enableALLM": "on"},
        }
    )
    manager.context = {"input": "hdmi3", "range": "sdr", "mode": "filmMaker", "ready": True}
    assert manager.active_names == ["Apple TV", "Shield"]
    manager.context["ready"] = False
    assert manager.active_names == []


async def test_interrupted_full_restore_is_journaled_without_a_temporary_edit(manager):
    manager.transport.values["movie_sdr"]["color"] = 70  # An LG remote edit, not an MQTT edit.
    manager.transport.fail_apply = True
    with pytest.raises(HomeAssistantError):
        await manager.async_restore()
    assert manager.override_count == 0
    assert manager.store.saved["restore_requests"]
    restored = ProfileManager(
        manager.hass, manager.entry, transport=manager.transport, store=MemoryStore(manager.data)
    )
    restored._schedule_sync = lambda: None
    await restored.async_start()
    manager.transport.fail_apply = False
    await restored.async_reconcile()
    assert restored.transport.values["movie_sdr"]["color"] == "50"
    assert not restored.data["restore_requests"]
    assert not restored.data["pending_restore"]
    await restored.async_stop()


async def test_new_edit_during_explicit_restore_remains_temporary(manager):
    await adjust(manager, "game_hdr", "gameSharpness", 10)

    async def after_write():
        await adjust(manager, "game_hdr", "gameSharpness", 9, "newer-edit")

    manager.transport.on_apply = after_write
    await manager.async_restore()
    assert manager.data["overrides"]["game_hdr"]["gameSharpness"] == 9
    assert not manager.data["pending_restore"]
    await manager.async_reconcile()
    assert manager.transport.values["game_hdr"]["gameSharpness"] == 9


async def test_tv_metadata_and_sun_attributes_do_not_write_or_schedule_work(manager):
    scheduled = []
    manager._schedule_sync = lambda: scheduled.append(True)
    saves = manager.store.saves
    for entity in ("media_player.tv", "sun.sun"):
        state = manager.hass.states.get(entity)
        for _ in range(10):
            await manager._handle_state(
                SimpleNamespace(
                    data={
                        "old_state": state,
                        "new_state": state,
                    }
                )
            )
    assert manager.store.saves == saves
    assert not scheduled
    old = manager.hass.states.get("media_player.tv")
    manager.hass.states.async_set("media_player.tv", "off")
    await manager._handle_state(
        SimpleNamespace(
            data={
                "old_state": old,
                "new_state": manager.hass.states.get("media_player.tv"),
            }
        )
    )
    assert manager.store.saves == saves + 1
    assert len(scheduled) == 1
