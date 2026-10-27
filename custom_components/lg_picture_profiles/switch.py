"""One owner for day/night policy and temporary adjustments."""

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.entity import EntityCategory

from .entity import ProfileEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([ManagementSwitch(entry)])


class ManagementSwitch(ProfileEntity, SwitchEntity):
    _attr_name = "Manage picture profiles"
    _attr_icon = "mdi:television-guide"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry):
        super().__init__(entry, "management")

    @property
    def is_on(self):
        return self.manager.data["enabled"]

    async def async_turn_on(self, **kwargs):
        await self.manager.async_enable(True)

    async def async_turn_off(self, **kwargs):
        await self.manager.async_enable(False)
