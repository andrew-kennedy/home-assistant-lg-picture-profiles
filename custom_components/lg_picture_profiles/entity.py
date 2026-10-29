"""Common device and subscription lifecycle for companion entities."""

from homeassistant.core import callback
from homeassistant.helpers.entity import Entity


class ProfileEntity(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry, key: str) -> None:
        self.manager = entry.runtime_data
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        # A companion links to the bridge's device; it must not register a
        # second device or move the MQTT entities into this config entry.
        self.device_entry = self.manager.devices.device if self.manager.devices else None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.manager.async_add_listener(self._changed))

    @callback
    def _changed(self) -> None:
        self.async_write_ha_state()
