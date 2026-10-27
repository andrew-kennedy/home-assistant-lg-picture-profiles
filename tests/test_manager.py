import hashlib
import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.lg_picture_profiles.backup import decode
from custom_components.lg_picture_profiles.manager import ProfileManager
from custom_components.lg_picture_profiles.model import ProfileError

from .conftest import FakeTransport, MemoryStore, document


def backup(sequence=1, revision=1, instance="tv-process", owner="tv-owner", **fields):
    state = {
        "schema": 1,
        "document": document(),
        "owner_id": owner,
        "instance_id": instance,
        "sequence": sequence,
        "revision": revision,
        "enabled": True,
        "room": "dark",
        "preferences": {"movie_bright": 100, "movie_dark": 3, "game_sdr": 80},
        "overrides": {},
        "recovery": {"dirty": {}, "restore": {}, "power": "on", "boot_id": "boot"},
        "migration_id": "test",
        **fields,
    }
    raw = json.dumps(state, separators=(",", ":"))
    return {
        "protocol": 1,
        "format": "lg-picture-bridge-backup",
        "state_json": raw,
        "sha256": hashlib.sha256(raw.encode()).hexdigest(),
    }


async def test_complete_backup_persisted_before_ack(manager):
    snapshot = backup(overrides={"game_hdr": {"gameSharpness": 7}})

    async def ack(state, checksum):
        assert manager.store.saved["backup"] == snapshot
        assert state["overrides"]["game_hdr"]["gameSharpness"] == 7

    manager.transport.async_ack_backup = AsyncMock(side_effect=ack)
    await manager._accept_backup(snapshot)
    assert manager.override_count == 1
    assert manager.document == document()
    assert manager.saved["migration_complete"]
    manager.transport.async_ack_backup.assert_awaited_once()
    assert not manager.transport.calls, "Receiving observations never drives HA settings writes"


async def test_duplicate_ack_has_no_storage_write(manager):
    snapshot = backup()
    await manager._accept_backup(snapshot)
    writes = manager.store.saves
    await manager._accept_backup(snapshot)
    assert manager.store.saves == writes
    assert len(manager.transport.acks) == 2


async def test_corrupt_or_out_of_order_backup_cannot_replace_good_copy(manager):
    valid = backup(sequence=4)
    await manager._accept_backup(valid)
    await manager._accept_backup(backup(sequence=3))
    assert manager.saved["backup"] == valid
    with pytest.raises(ProfileError, match="checksum"):
        await manager._accept_backup({**valid, "state_json": valid["state_json"] + " "})
    await manager._accept_backup(backup(sequence=99, instance="retired-process"))
    assert manager.saved["backup"] == valid
    manager.transport.manager_status["instance_id"] = "new-process"
    await manager._accept_backup(backup(instance="new-process"))
    assert manager.snapshot["instance_id"] == "new-process"


async def test_retained_backup_can_seed_new_ha_without_running_policy(manager):
    manager.transport.available = False
    await manager._accept_backup(backup())
    assert manager.document == document()
    assert manager.state == "offline"
    assert await manager.async_export_backup() == manager.saved["backup"]
    assert not manager.transport.calls
    with pytest.raises(HomeAssistantError, match="Turn on"):
        await manager.async_enable(True)


async def test_backup_history_only_tracks_standard_revisions_and_is_bounded(manager):
    await manager._accept_backup(backup())
    await manager._accept_backup(backup(sequence=2, overrides={"game_hdr": {"gameSharpness": 5}}))
    assert not manager.saved["previous"]
    for n in range(2, 10):
        await manager._accept_backup(backup(sequence=n + 1, revision=n))
    assert len(manager.saved["previous"]) == 5
    assert decode(manager.saved["previous"][-1])["revision"] == 8


async def test_failed_disk_write_is_not_acknowledged(manager):
    manager.store.async_save = AsyncMock(side_effect=OSError("disk unavailable"))
    with pytest.raises(OSError):
        await manager._accept_backup(backup())
    assert not manager.transport.acks
    assert not manager.snapshot


async def test_migration_keeps_legacy_until_complete_backup_is_saved(manager):
    legacy = {
        "document": document(),
        "enabled": True,
        "overrides": {"game_hdr": {"gameSharpness": 7}},
        "pending_restore": True,
        "restore_requests": {"game_hdr": ["gameSharpness"]},
    }
    old = ProfileManager(
        manager.hass, manager.entry, transport=FakeTransport(), store=MemoryStore(legacy)
    )
    old._schedule_sync = lambda: None
    await old.async_start()
    assert old.saved["legacy"] == legacy
    assert old.state == "awaiting_tv_migration"
    await old._sync()
    assert len(old.transport.calls) == 1
    action, fields = old.transport.calls[0]
    assert action == "initialize"
    assert fields["document"] == legacy["document"]
    assert fields["overrides"] == legacy["overrides"]
    assert fields["restore"] == legacy["restore_requests"]
    assert not old.saved["migration_complete"], "Command success is not a durable backup"
    await old._accept_backup(backup())
    assert old.saved["migration_complete"]
    old.transport.manager_status["configured"] = True
    await old._sync()
    assert len(old.transport.calls) == 1
    assert "legacy" not in old.saved
    assert "legacy" not in old.store.saved
    await old.async_stop()


async def test_completed_migration_cleanup_preserves_backup_and_history_offline(manager):
    original = {
        "format": 2,
        "backup": backup(sequence=3, revision=3),
        "previous": [backup(), backup(sequence=2, revision=2)],
        "legacy": {"document": document(), "enabled": True},
        "migration_complete": True,
    }
    store = MemoryStore(original)
    expected = {k: v for k, v in original.items() if k != "legacy"}
    for _ in range(2):
        transport = FakeTransport()
        transport.available = False
        runtime = ProfileManager(manager.hass, manager.entry, transport=transport, store=store)
        runtime._schedule_sync = lambda: None
        await runtime.async_start()
        assert runtime.saved == store.saved == expected
        assert runtime.document == document()
        assert store.saves == 1, "Cleanup writes once, not on every reload"
        assert not transport.calls
        assert not transport.acks
        await runtime.async_stop()


@pytest.mark.parametrize("complete", [False, True])
async def test_migration_copy_without_verified_backup_is_preserved(manager, complete):
    original = {
        "format": 2,
        "backup": None,
        "previous": [],
        "legacy": {"document": document(), "enabled": True},
        "migration_complete": complete,
    }
    store = MemoryStore(original)
    runtime = ProfileManager(manager.hass, manager.entry, transport=FakeTransport(), store=store)
    runtime._schedule_sync = lambda: None
    await runtime.async_start()
    assert runtime.saved == store.saved == original
    assert not store.saves
    await runtime.async_stop()


async def test_corrupt_backup_cannot_discard_migration_copy(manager):
    original = {
        "format": 2,
        "backup": {**backup(), "sha256": "invalid"},
        "previous": [],
        "legacy": {"document": document()},
        "migration_complete": True,
    }
    store = MemoryStore(original)
    runtime = ProfileManager(manager.hass, manager.entry, transport=FakeTransport(), store=store)
    with pytest.raises(ProfileError, match="checksum"):
        await runtime.async_start()
    assert store.saved == original
    assert not store.saves
    await runtime.async_stop()


async def test_failed_migration_commit_preserves_copy_and_retries_atomically(manager):
    legacy = {"document": document(), "enabled": True}
    manager.saved["legacy"] = legacy
    before = deepcopy(manager.saved)
    save = manager.store.async_save
    manager.store.async_save = AsyncMock(side_effect=OSError("disk unavailable"))
    with pytest.raises(OSError):
        await manager._accept_backup(backup())
    assert manager.saved == before
    assert not manager.transport.acks
    assert not manager.snapshot
    manager.store.async_save = save
    await manager._accept_backup(backup())
    assert manager.saved == manager.store.saved
    assert "legacy" not in manager.saved
    assert manager.saved["migration_complete"]
    assert len(manager.transport.acks) == 1


async def test_failed_backup_revision_commit_does_not_duplicate_history(manager):
    first = backup()
    await manager._accept_backup(first)
    before = deepcopy(manager.saved)
    save = manager.store.async_save
    manager.store.async_save = AsyncMock(side_effect=OSError("disk unavailable"))
    next_backup = backup(sequence=2, revision=2)
    with pytest.raises(OSError):
        await manager._accept_backup(next_backup)
    assert manager.saved == before
    manager.store.async_save = save
    await manager._accept_backup(next_backup)
    assert manager.saved["previous"] == [first]
    assert manager.saved["backup"] == next_backup


async def test_old_bridge_cannot_trigger_legacy_policy(manager):
    manager.saved["legacy"] = {"document": document(), "enabled": True}
    manager.transport.api_version = 1
    await manager._sync()
    assert manager.state == "awaiting_tv_migration"
    assert not manager.transport.calls
    with pytest.raises(HomeAssistantError, match=r"LG Picture Bridge 0\.13\.2"):
        await manager.async_restore()


async def test_preexisting_tv_is_not_overwritten_by_legacy_ha(manager):
    legacy = {"document": document(), "enabled": True}
    manager.saved["legacy"] = legacy
    manager.transport.manager_status["configured"] = True
    await manager._accept_backup(backup(migration_id="different-entry"))
    await manager._sync()
    assert "already has" in manager.last_error
    assert manager.saved["legacy"] == manager.store.saved["legacy"] == legacy
    assert not manager.saved["migration_complete"]
    assert not manager.transport.calls


async def test_controls_forward_to_tv_with_revision(manager):
    await manager._accept_backup(backup())
    manager.transport.manager_status["configured"] = True
    await manager.async_enable(True)
    await manager.async_set_brightness("movie_dark", 5)
    await manager.async_restore("active")
    await manager.async_save_standard("all")
    assert manager.transport.calls == [
        ("set_enabled", {"enabled": True}),
        ("set_brightness", {"values": {"movie_dark": 5}, "revision": 1}),
        ("restore", {"scope": "active"}),
        ("save", {"scope": "all", "revision": 1}),
    ]
    assert manager.snapshot["preferences"]["movie_dark"] == 3, (
        "HA must await the TV's confirmed backup"
    )


async def test_power_and_metadata_do_not_write_profiles_or_store(manager):
    manager.transport.calls.clear()
    saves = manager.store.saves
    for old, new in [("on", "off"), ("off", "unavailable"), ("unavailable", "on"), ("on", "on")]:
        manager._state_changed(
            SimpleNamespace(
                data={
                    "old_state": SimpleNamespace(state=old),
                    "new_state": SimpleNamespace(state=new, entity_id="media_player.tv"),
                }
            )
        )
    await manager.hass.async_block_till_done()
    assert not manager.transport.calls
    assert manager.store.saves == saves


async def test_invalid_old_store_not_replaced(manager):
    original = {"document": {"schema": 99}, "enabled": True}
    store = MemoryStore(original)
    runtime = ProfileManager(manager.hass, manager.entry, transport=FakeTransport(), store=store)
    with pytest.raises(ProfileError):
        await runtime.async_start()
    await runtime.async_stop()
    assert store.saved == original


async def test_status_sensor_explains_native_tv_error(manager):
    from custom_components.lg_picture_profiles.sensor import ProfileSensor

    manager.transport.manager_status["error"] = "Inactive preset rejected"
    entry = SimpleNamespace(entry_id="test", title="Profiles", runtime_data=manager)
    sensor = ProfileSensor(entry, "status")
    assert sensor.native_value == "error"
    assert sensor.extra_state_attributes["last_error"] == "Inactive preset rejected"


@pytest.mark.parametrize("role", ["movie_bright", "movie_dark", "game_sdr"])
async def test_brightness_slider_reads_confirmed_tv_value_and_never_mirrors_helpers(manager, role):
    from custom_components.lg_picture_profiles.number import ProfileBrightness

    helper_call = AsyncMock()
    manager.hass.services.async_register("input_number", "set_value", helper_call)
    manager.config.update(
        bright_helper="input_number.day",
        dark_helper="input_number.night",
        game_helper="input_number.game",
    )
    for helper in ("day", "night", "game"):
        manager.hass.states.async_set("input_number." + helper, "0")
    await manager._accept_backup(backup())
    entry = SimpleNamespace(entry_id="test", title="Profiles", runtime_data=manager)
    slider = ProfileBrightness(entry, role)
    before = manager.snapshot["preferences"][role]
    assert slider.native_value == before
    await slider.async_set_native_value(42)
    assert manager.transport.calls == [("set_brightness", {"values": {role: 42}, "revision": 1})]
    assert slider.native_value == before, "Display only the TV-confirmed value"
    await manager._accept_backup(
        backup(sequence=2, revision=2, preferences={**manager.snapshot["preferences"], role: 42})
    )
    assert slider.native_value == 42
    await manager.hass.async_block_till_done()
    helper_call.assert_not_called()


async def test_retired_helper_changes_do_not_send_tv_commands(manager):
    await manager._accept_backup(backup())
    manager.config["dark_helper"] = "input_number.lg_movie_dark_sdr_oled_light"
    for value in (4, 5):
        manager._state_changed(
            SimpleNamespace(
                data={
                    "old_state": SimpleNamespace(state=str(value - 1)),
                    "new_state": SimpleNamespace(
                        state=str(value), entity_id="input_number.lg_movie_dark_sdr_oled_light"
                    ),
                }
            )
        )
    await manager.hass.async_block_till_done()
    assert not manager.transport.calls
