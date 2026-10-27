"""Remote edits, native preset loads, and automatic-write echoes on pushed telemetry."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from custom_components.lg_picture_profiles.manager import ProfileManager

from .conftest import MemoryStore


def observe(manager, bank_id, key, value, *, age=0, update_tv=True):
    bank = next(b for b in manager.document["banks"] if b["id"] == bank_id)
    if update_tv:
        manager.transport.values[bank_id][key] = deepcopy(value)
    item = {
        "target": deepcopy(bank["target"]),
        "key": key,
        "value": value,
        "observed_at": (datetime.now(UTC) + timedelta(seconds=age)).isoformat(),
    }
    manager._settings_observed([item])
    return item


async def test_remote_edits_restore_original_bank_after_confirmed_power_cycle(manager):
    original = deepcopy(manager.document)
    observe(manager, "game_hdr", "gameColorDepth", 60)
    observe(manager, "game_hdr", "gameSharpness", 4)
    assert manager.override_count == 2
    assert manager.document == original
    assert not manager.transport.calls, "Tracking uses pushed values, no TV reads or writes"
    manager.hass.states.async_set("media_player.tv", "off")
    await manager._handle_state(
        SimpleNamespace(data={"new_state": manager.hass.states.get("media_player.tv")})
    )
    assert manager.store.saved["pending_restore"]
    manager.hass.states.async_set("media_player.tv", "on")
    manager.context = {
        "input": "hdmi3",
        "mode": "dolbyHdrCinema",
        "range": "dolbyHdr",
        "ready": True,
    }
    await manager.async_reconcile()
    assert not manager.override_count
    assert manager.transport.values["game_hdr"]["gameColorDepth"] == 50
    assert manager.transport.values["game_hdr"]["gameSharpness"] == 0
    assert manager.document == original


async def test_save_promotes_remote_edits_without_promoting_other_contexts(manager):
    observe(manager, "game_hdr", "gameSharpness", 3)
    observe(manager, "movie_sdr", "color", 55)
    assert await manager.async_save_standard() == {"saved_settings": 1}
    assert manager.document["banks"][1]["settings"]["gameSharpness"] == 3
    assert manager.document["banks"][0]["settings"]["color"] == "50"
    assert manager.data["overrides"] == {"movie_sdr": {"color": 55}}


async def test_normal_preset_loads_duplicates_and_old_messages_do_not_persist(manager):
    count = manager.store.saves
    for bank in manager.document["banks"]:
        for key, value in bank["settings"].items():
            observe(manager, bank["id"], key, value)
    assert not manager.override_count and not manager._observation_save
    assert manager.store.saves == count and not manager.transport.calls
    packet = observe(manager, "game_hdr", "gameSharpness", 5)
    timer = manager._observation_save
    for _ in range(20):
        manager._settings_observed([packet])
    assert manager._observation_save is timer and manager.store.saves == count
    observe(manager, "game_hdr", "gameSharpness", 8, age=-30, update_tv=False)
    assert manager.data["overrides"]["game_hdr"]["gameSharpness"] == 5
    observe(manager, "game_hdr", "gameSharpness", 0)
    assert not manager.override_count


async def test_day_change_and_our_write_echoes_are_not_overrides(manager):
    await manager.async_reconcile()
    observe(manager, "movie_sdr", "backlight", 3)
    manager.hass.states.async_set("sun.sun", "above_horizon")
    # Replayed observations before the new environment has finished applying.
    observe(manager, "movie_sdr", "backlight", 3)
    observe(manager, "movie_sdr", "peakBrightness", "off")
    assert not manager.override_count

    async def own_echo():
        observe(manager, "movie_sdr", "backlight", 100)
        observe(manager, "movie_sdr", "peakBrightness", "high")
        observe(manager, "dv_mapping", "pictureMode", "dolbyHdrCinemaBright")
        assert not manager.override_count

    manager.transport.on_apply = own_echo
    await manager.async_reconcile()
    assert not manager.override_count
    assert manager.data["environment"]["room"] == "bright"
    assert manager.transport.values["movie_sdr"]["backlight"] == 100


async def test_remote_brightness_wins_during_environment_read(manager):
    await manager.async_reconcile()
    manager.hass.states.async_set("sun.sun", "above_horizon")

    async def edit():
        observe(manager, "movie_sdr", "backlight", 35)

    manager.transport.on_read = edit
    await manager.async_reconcile()
    assert manager.transport.values["movie_sdr"]["backlight"] == 35
    assert manager.data["overrides"]["movie_sdr"]["backlight"] == 35


async def test_new_remote_edit_during_restore_is_kept(manager):
    observe(manager, "game_hdr", "gameSharpness", 5)

    async def edit():
        observe(manager, "game_hdr", "gameSharpness", 0)  # Our write's echo.
        observe(manager, "game_hdr", "gameSharpness", 5)  # A fresh external edit.

    manager.transport.on_apply = edit
    await manager.async_restore()
    assert manager.data["overrides"]["game_hdr"]["gameSharpness"] == 5
    assert not manager.data["pending_restore"]


async def test_lost_write_echo_does_not_hide_a_repeat_remote_value(manager):
    observe(manager, "game_hdr", "gameSharpness", 5)
    await manager.async_restore()  # No echo in FakeTransport.
    assert not manager.override_count
    observe(manager, "game_hdr", "gameSharpness", 5)
    assert manager.data["overrides"]["game_hdr"]["gameSharpness"] == 5


async def test_wrong_app_unmanaged_bank_invalid_and_disabled_observations_are_ignored(manager):
    packet = observe(manager, "game_hdr", "gameSharpness", 0)
    for bad in [
        None,
        {},
        {**packet, "value": float("nan")},
        {**packet, "observed_at": "bad"},
        {**packet, "target": {**packet["target"], "app_id": "com.webos.app.hdmi1"}},
        {**packet, "key": "factoryReset"},
    ]:
        manager._settings_observed([bad])
    assert not manager.override_count
    await manager.async_enable(False)
    observe(manager, "game_hdr", "gameSharpness", 10)
    assert not manager.override_count


async def test_restart_and_unknown_power_preserve_remote_adjustment(manager):
    observe(manager, "game_hdr", "gameSharpness", 7)
    await manager.persist()
    restored = ProfileManager(
        manager.hass, manager.entry, transport=manager.transport, store=MemoryStore(manager.data)
    )
    restored._schedule_sync = lambda: None
    await restored.async_start()
    manager.hass.states.async_set("media_player.tv", "unavailable")
    await restored._handle_state(
        SimpleNamespace(data={"new_state": manager.hass.states.get("media_player.tv")})
    )
    assert restored.override_count == 1 and not restored.data["pending_restore"]
    await restored.async_stop()


async def test_newer_duplicate_advances_watermark_before_an_old_different_value(manager):
    observe(manager, "game_hdr", "gameSharpness", 0)
    observe(manager, "game_hdr", "gameSharpness", 0, age=10)
    observe(manager, "game_hdr", "gameSharpness", 9, age=5, update_tv=False)
    assert not manager.override_count


async def test_remote_button_burst_coalesces_durable_saves(manager):
    import asyncio

    saves = manager.store.saves
    for value in range(1, 31):
        observe(manager, "game_hdr", "gameSharpness", value)
    assert manager.store.saves == saves
    assert not manager.transport.calls
    await asyncio.sleep(0.55)
    assert manager.store.saves == saves + 1
    assert manager.store.saved["overrides"]["game_hdr"]["gameSharpness"] == 30


async def test_observation_during_connection_loss_does_not_end_session(manager):
    manager.data["last_power"] = "on"
    manager.hass.states.async_set("media_player.tv", "unavailable")
    observe(manager, "game_hdr", "gameSharpness", 6)
    assert manager.override_count == 1
    assert not manager.data["pending_restore"]
    # A late observation after a confirmed off must still queue restoration.
    manager.data["last_power"] = "off"
    observe(manager, "game_hdr", "gameSharpness", 7)
    assert manager.data["pending_restore"]


async def test_mqtt_result_during_connection_loss_does_not_end_session(manager):
    from .conftest import adjust

    manager.data["last_power"] = "on"
    manager.hass.states.async_set("media_player.tv", "unknown")
    await adjust(manager, "game_hdr", "gameSharpness", 8)
    assert not manager.data["pending_restore"]


async def test_first_replayed_snapshot_cannot_resurrect_an_override_during_wake_restore(manager):
    observe(manager, "game_hdr", "gameSharpness", 8)
    manager.data["pending_restore"] = True
    restored = ProfileManager(
        manager.hass, manager.entry, transport=manager.transport, store=MemoryStore(manager.data)
    )
    restored._schedule_sync = lambda: None
    await restored.async_start()

    async def first_snapshot():
        observe(restored, "game_hdr", "gameSharpness", 8)

    restored.transport.on_read = first_snapshot
    await restored.async_reconcile()
    assert restored.transport.values["game_hdr"]["gameSharpness"] == 0
    assert restored.override_count == 0
    assert not restored.data["pending_restore"]
    await restored.async_stop()
