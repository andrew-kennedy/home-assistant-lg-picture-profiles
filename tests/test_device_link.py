from types import MappingProxyType, SimpleNamespace

import pytest
from homeassistant import config_entries
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.lg_picture_profiles.const import DOMAIN
from custom_components.lg_picture_profiles.device_link import BridgeDeviceLink
from custom_components.lg_picture_profiles.entity import ProfileEntity

from .test_config_flow import configured as configured


@pytest.fixture
async def registries(configured):
    hass, entry = configured
    dr.async_setup(hass)
    await dr.async_load(hass)
    await er.async_load(hass)
    mqtt = config_entries.ConfigEntry(
        domain="mqtt",
        title="Broker",
        data={},
        options={},
        unique_id="broker",
        version=1,
        minor_version=1,
        source="user",
        discovery_keys=MappingProxyType({}),
        subentries_data=None,
    )
    hass.config_entries._entries[mqtt.entry_id] = mqtt
    link = BridgeDeviceLink(hass, entry)
    entry.runtime_data = SimpleNamespace(devices=link)
    yield hass, entry, mqtt, dr.async_get(hass), er.async_get(hass), link
    link.async_stop()


async def test_existing_entities_link_without_changing_identity_or_mqtt_owner(registries):
    hass, entry, mqtt, devices, entities, link = registries
    bridge = devices.async_get_or_create(
        config_entry_id=mqtt.entry_id,
        identifiers={("mqtt", "test")},
        name="Living room TV",
        model="LG Picture Bridge",
        sw_version="0.13.6",
    )
    old = devices.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, entry.entry_id)}, name="Profiles"
    )
    existing = []
    for key in ["status", "management", "movie_dark"]:
        e = entities.async_get_or_create(
            "sensor", DOMAIN, entry.entry_id + "_" + key, config_entry=entry, device_id=old.id
        )
        existing.append(
            entities.async_update_entity(
                e.entity_id,
                name="My " + key,
                icon="mdi:television",
                disabled_by=er.RegistryEntryDisabler.USER if key == "status" else None,
            )
        )
    native = entities.async_get_or_create(
        "number", "mqtt", "setting_backlight", config_entry=mqtt, device_id=bridge.id
    )
    link.async_start()
    await hass.async_block_till_done()
    assert link.device.id == bridge.id
    assert devices.async_get(bridge.id) == bridge, "Companion must not change MQTT device metadata"
    assert devices.async_get(old.id) is None, "Retire only the obsolete companion device"
    assert entities.async_get(native.entity_id) == native
    for before in existing:
        after = entities.async_get(before.entity_id)
        assert after.device_id == bridge.id
        for field in [
            "id",
            "entity_id",
            "unique_id",
            "config_entry_id",
            "name",
            "icon",
            "disabled_by",
        ]:
            assert getattr(after, field) == getattr(before, field)
    entity = ProfileEntity(entry, "status")
    assert entity.device_entry.id == bridge.id
    assert entity.device_info is None, "Link the entity; do not register a duplicate device"
    # A reload is idempotent and does not add another MQTT device or entity.
    link.async_sync()
    assert len(list(devices.devices)) == 1
    assert len(entities.entities) == 4


async def test_late_discovery_and_removed_device_relink_without_polling(registries):
    hass, entry, mqtt, devices, entities, link = registries
    entity = entities.async_get_or_create("sensor", DOMAIN, "late", config_entry=entry)
    link.async_start()
    assert ProfileEntity(entry, "status").device_info is None
    assert link.device is None
    bridge = devices.async_get_or_create(
        config_entry_id=mqtt.entry_id, identifiers={("mqtt", "test")}, name="TV"
    )
    await hass.async_block_till_done()
    assert entities.async_get(entity.entity_id).device_id == bridge.id
    devices.async_remove_device(bridge.id)
    await hass.async_block_till_done()
    assert link.device is None
    assert entities.async_get(entity.entity_id).device_id is None
    replacement = devices.async_get_or_create(
        config_entry_id=mqtt.entry_id, identifiers={("mqtt", "test")}, name="TV"
    )
    await hass.async_block_till_done()
    assert entities.async_get(entity.entity_id).device_id == replacement.id
    link.async_stop()
    devices.async_update_device(replacement.id, new_identifiers={("mqtt", "different")})
    await hass.async_block_till_done()
    assert link.device.id == replacement.id, "Unloading removes the registry listener"


async def test_do_not_link_wrong_bridge_or_identity_from_another_integration(registries):
    hass, entry, mqtt, devices, entities, link = registries
    wrong = devices.async_get_or_create(
        config_entry_id=mqtt.entry_id, identifiers={("mqtt", "other")}, name="Other TV"
    )
    impostor = devices.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={("mqtt", "test")}, name="Old duplicate"
    )
    entity = entities.async_get_or_create(
        "sensor", DOMAIN, "profile", config_entry=entry, device_id=impostor.id
    )
    link.async_start()
    assert link.device is None
    assert entities.async_get(entity.entity_id).device_id == impostor.id
    assert devices.async_get(wrong.id) is not None


async def test_two_mqtt_owners_are_ambiguous(registries):
    hass, entry, mqtt, devices, entities, link = registries
    other = config_entries.ConfigEntry(
        domain="mqtt",
        title="Other broker",
        data={},
        options={},
        unique_id="other",
        version=1,
        minor_version=1,
        source="user",
        discovery_keys=MappingProxyType({}),
        subentries_data=None,
    )
    hass.config_entries._entries[other.entry_id] = other
    matches = [
        devices.async_get_or_create(
            config_entry_id=owner.entry_id, identifiers={("mqtt", "test")}, name="TV"
        )
        for owner in [mqtt, other]
    ]
    link.async_start()
    assert link.device is None
    devices.async_update_device(matches[1].id, new_identifiers={("mqtt", "other")})
    await hass.async_block_till_done()
    assert link.device.id == matches[0].id, "Resolve ambiguity when the other identity changes"
