from copy import deepcopy
from types import MappingProxyType
from unittest.mock import AsyncMock

import pytest
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.lg_picture_profiles import async_migrate_entry
from custom_components.lg_picture_profiles.config_flow import LGPictureProfilesConfigFlow, schema
from custom_components.lg_picture_profiles.manager import ProfileManager

from .conftest import FakeTransport, MemoryStore, document
from .test_manager import backup

HELPERS = {
    "bright_helper": "input_number.day",
    "dark_helper": "input_number.night",
    "game_helper": "input_number.game",
}
SETUP = {
    "name": "LG Picture Profiles",
    "bridge_topic": "lg/test",
    "tv_entity": "media_player.tv",
    "sun_entity": "sun.sun",
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
    hass.config_entries._entries[entry.entry_id] = entry
    monkeypatch.setattr(
        config_entries,
        "_async_get_flow_handler",
        AsyncMock(return_value=LGPictureProfilesConfigFlow),
    )
    monkeypatch.setattr(
        config_entries, "_support_single_config_entry_only", AsyncMock(return_value=False)
    )
    hass.states.async_set("media_player.tv", "on")
    hass.states.async_set("sun.sun", "below_horizon")
    yield hass, entry
    await hass.async_stop()


def field(form, name):
    return next(k for k in form["data_schema"].schema if k.schema == name)


async def test_setup_and_options_only_offer_connection_fields(configured, monkeypatch):
    hass, entry = configured
    form = await hass.config_entries.flow.async_init(
        "lg_picture_profiles", context={"source": "user"}
    )
    assert {k.schema for k in form["data_schema"].schema} == set(SETUP)
    monkeypatch.setattr(hass.config_entries, "async_setup", AsyncMock(return_value=True))
    edited = {**SETUP, "bridge_topic": "lg/another"}
    result = await hass.config_entries.flow.async_configure(form["flow_id"], edited)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].version == 2
    assert dict(result["result"].data) == edited
    form = await hass.config_entries.options.async_init(entry.entry_id)
    assert {k.schema for k in form["data_schema"].schema} == set(SETUP)
    with pytest.raises(vol.Invalid):
        schema()({**SETUP, **HELPERS})


@pytest.mark.parametrize("with_options", [False, True])
async def test_migration_removes_bindings_without_changing_tv_backup(
    configured, monkeypatch, with_options
):
    hass, entry = configured
    options = {**SETUP, **HELPERS, "sun_entity": "sun.alternate"} if with_options else {}
    hass.config_entries.async_update_entry(entry, data={**SETUP, **HELPERS}, options=options)
    stored = {
        "format": 2,
        "migration_complete": True,
        "backup": backup(preferences={"movie_bright": 73, "movie_dark": 7, "game_sdr": 62}),
        "previous": [],
        "legacy": {"document": document()},
    }
    original = deepcopy(stored)
    store = MemoryStore(stored)
    monkeypatch.setattr("custom_components.lg_picture_profiles.Store", lambda *a, **kw: store)
    assert await async_migrate_entry(hass, entry)
    assert entry.version == 2
    assert dict(entry.data) == SETUP
    expected = {k: v for k, v in options.items() if k not in HELPERS}
    assert dict(entry.options) == expected
    assert store.saved == original
    assert store.saves == 0
    runtime = ProfileManager(hass, entry, transport=FakeTransport(), store=store)
    runtime._schedule_sync = lambda: None
    await runtime.async_start()
    assert runtime.config == (expected or SETUP)
    assert runtime.snapshot["preferences"] == {"movie_bright": 73, "movie_dark": 7, "game_sdr": 62}
    await runtime.async_stop()
    assert await async_migrate_entry(hass, entry), "Migration is idempotent"


@pytest.mark.parametrize(
    "stored",
    [
        None,
        {"document": document()},
        {"migration_complete": True, "backup": {"state_json": "corrupt"}},
    ],
)
async def test_unfinished_legacy_migration_keeps_helper_bindings(configured, monkeypatch, stored):
    hass, entry = configured
    original = {**SETUP, **HELPERS}
    hass.config_entries.async_update_entry(entry, data=original)
    store = MemoryStore(stored)
    monkeypatch.setattr("custom_components.lg_picture_profiles.Store", lambda *a, **kw: store)
    assert not await async_migrate_entry(hass, entry)
    assert entry.version == 1
    assert dict(entry.data) == original
    assert not store.saves


async def test_cleared_bindings_are_not_resurrected_from_original_setup(configured):
    hass, entry = configured
    hass.config_entries.async_update_entry(entry, data={**SETUP, **HELPERS}, options=SETUP)
    assert await async_migrate_entry(hass, entry)
    assert dict(entry.data) == dict(entry.options) == SETUP


async def test_changed_bridge_rejected_without_saving(configured):
    hass, entry = configured
    form = await hass.config_entries.options.async_init(entry.entry_id)
    edited = {**SETUP, "bridge_topic": "another/bridge"}
    error = await hass.config_entries.options.async_configure(form["flow_id"], edited)
    assert error["errors"] == {"bridge_topic": "bridge_change"}
    assert not entry.options
    assert {k.schema for k in error["data_schema"].schema} == set(SETUP)


async def test_name_and_environment_change_are_saved_together(configured):
    hass, entry = configured
    changes = []

    async def updated(hass, entry):
        changes.append((entry.title, dict(entry.options)))

    entry.add_update_listener(updated)
    form = await hass.config_entries.options.async_init(entry.entry_id)
    edited = {**SETUP, "name": "Living room profiles", "sun_entity": "sun.alternate"}
    await hass.config_entries.options.async_configure(form["flow_id"], edited)
    await hass.async_block_till_done()
    assert entry.title == edited["name"]
    assert changes == [(edited["name"], edited)]
    hass.config_entries.async_update_entry(entry, title="Renamed in Home Assistant")
    reopened = await hass.config_entries.options.async_init(entry.entry_id)
    assert field(reopened, "name").default() == "Renamed in Home Assistant"
