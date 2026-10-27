"""Shared SDR standards stored on the TV, with no polling."""

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.helpers.entity import EntityCategory

from .entity import ProfileEntity

NAMES = {
    "movie_bright": "Movie SDR brightness bright room",
    "movie_dark": "Movie SDR brightness dark room",
    "game_sdr": "Game SDR brightness",
}


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(ProfileBrightness(entry, key) for key in NAMES)


class ProfileBrightness(ProfileEntity, NumberEntity):
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:brightness-6"

    def __init__(self, entry, key):
        super().__init__(entry, key)
        self.key = key
        self._attr_name = NAMES[key]

    @property
    def available(self):
        return self.manager.available and bool(self.manager.snapshot)

    @property
    def native_value(self):
        return self.manager.snapshot.get("preferences", {}).get(self.key)

    async def async_set_native_value(self, value):
        await self.manager.async_set_brightness(self.key, value)
