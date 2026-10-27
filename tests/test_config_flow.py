from types import MappingProxyType
from unittest.mock import AsyncMock

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.lg_picture_profiles.config_flow import LGPictureProfilesConfigFlow
from custom_components.lg_picture_profiles.manager import ProfileManager

from .conftest import FakeTransport, MemoryStore, document

HELPERS = ("bright_helper", "dark_helper", "game_helper")
SETUP = {
    "name": "LG Picture Profiles",
    "bridge_topic": "lg/test",
    "tv_entity": "media_player.tv",
    "sun_entity": "sun.sun",
    "bright_helper": "input_number.day",
    "dark_helper": "input_number.night",
    "game_helper": "input_number.game",
}


@pytest.fixture
async def configured(tmp_path, monkeypatch):
    hass = HomeAssistant(str(tmp_path))
    hass.config_entries = config_entries.ConfigEntries(hass, {})
    await hass.config_entries.async_initialize()
    entry = config_entries.ConfigEntry(
        domain="lg_picture_profiles",
        title=SETUP["name"],
        data=dict(SETUP),
        options={},
        unique_id=SETUP["bridge_topic"],
        version=1,
        minor_version=1,
        source="user",
        discovery_keys=MappingProxyType({}),
        subentries_data=None,
    )
    # Use HA's actual flow validation/persistence; substitute only integration discovery.
    hass.config_entries._entries[entry.entry_id] = entry
    monkeypatch.setattr(
        config_entries,
        "_async_get_flow_handler",
        AsyncMock(return_value=LGPictureProfilesConfigFlow),
    )
    hass.states.async_set("media_player.tv", "on")
    hass.states.async_set("sun.sun", "below_horizon")
    for entity in ("input_number.day", "input_number.night", "input_number.game"):
        hass.states.async_set(entity, "25")
    yield hass, entry
    await hass.async_stop()


def field(form, name):
    return next(k for k in form["data_schema"].schema if k.schema == name)


@pytest.mark.parametrize("helper", HELPERS)
async def test_clear_helper_through_real_options_flow(configured, helper):
    hass, entry = configured
    form = await hass.config_entries.options.async_init(entry.entry_id)
    assert field(form, helper).description["suggested_value"] == SETUP[helper]
    edited = {k: v for k, v in SETUP.items() if k != helper}
    result = await hass.config_entries.options.async_configure(form["flow_id"], edited)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert dict(entry.options) == edited
    assert entry.data[helper] == SETUP[helper]  # Original setup data must not resurrect it.
    reopened = await hass.config_entries.options.async_init(entry.entry_id)
    assert not (field(reopened, helper).description or {}).get("suggested_value")
    for remaining in set(HELPERS) - {helper}:
        assert field(reopened, remaining).description["suggested_value"] == SETUP[remaining]
    runtime = ProfileManager(hass, entry, transport=FakeTransport(document()), store=MemoryStore())
    assert runtime.config == edited


async def test_saved_options_remain_authoritative_after_runtime_reload(configured):
    hass, entry = configured
    edited = {k: v for k, v in SETUP.items() if k not in HELPERS}
    hass.config_entries.async_update_entry(entry, options=edited)
    baseline = document()
    saved = {"document": baseline, "enabled": True, "overrides": {"game_hdr": {"gameSharpness": 7}}}
    store = MemoryStore(saved)
    for _ in range(2):
        runtime = ProfileManager(hass, entry, transport=FakeTransport(baseline), store=store)
        runtime._schedule_sync = lambda: None
        await runtime.async_start()
        assert runtime.config == edited
        assert all(key not in runtime.config for key in HELPERS)
        assert runtime.document == baseline
        assert runtime.saved["legacy"]["overrides"] == saved["overrides"]
        await runtime.async_stop()


async def test_initial_entries_without_options_keep_their_configured_helpers(configured):
    hass, entry = configured
    runtime = ProfileManager(hass, entry, transport=FakeTransport(document()), store=MemoryStore())
    assert runtime.config == SETUP
    assert all(runtime.config[key] == SETUP[key] for key in HELPERS)


async def test_changed_bridge_rejected_without_restoring_cleared_helpers(configured):
    hass, entry = configured
    form = await hass.config_entries.options.async_init(entry.entry_id)
    edited = {k: v for k, v in SETUP.items() if k != "dark_helper"}
    edited["bridge_topic"] = "another/bridge"
    error = await hass.config_entries.options.async_configure(form["flow_id"], edited)
    assert error["errors"] == {"bridge_topic": "bridge_change"}
    assert not entry.options
    assert not (field(error, "dark_helper").description or {}).get("suggested_value")
    edited["bridge_topic"] = SETUP["bridge_topic"]
    await hass.config_entries.options.async_configure(form["flow_id"], edited)
    assert dict(entry.options) == edited


async def test_name_and_helper_change_are_saved_together(configured):
    hass, entry = configured
    changes = []

    async def updated(hass, entry):
        changes.append((entry.title, dict(entry.options)))

    entry.add_update_listener(updated)
    form = await hass.config_entries.options.async_init(entry.entry_id)
    edited = {**SETUP, "name": "Living room profiles", "dark_helper": "input_number.new_night"}
    await hass.config_entries.options.async_configure(form["flow_id"], edited)
    await hass.async_block_till_done()
    assert entry.title == edited["name"]
    assert changes == [(edited["name"], edited)]
    hass.config_entries.async_update_entry(entry, title="Renamed in Home Assistant")
    reopened = await hass.config_entries.options.async_init(entry.entry_id)
    assert field(reopened, "name").default() == "Renamed in Home Assistant"
