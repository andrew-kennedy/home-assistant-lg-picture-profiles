"""Explicit restore and promote actions."""

from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.entity import EntityCategory

from .entity import ProfileEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        [ProfileButton(entry, "restore_standard"), ProfileButton(entry, "save_standard")]
    )


class ProfileButton(ProfileEntity, ButtonEntity):
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry, action):
        super().__init__(entry, action)
        self.action = action
        self._attr_name = (
            "Restore standard"
            if action == "restore_standard"
            else "Save current adjustments as standard"
        )
        self._attr_icon = (
            "mdi:restore" if action == "restore_standard" else "mdi:content-save-check"
        )

    @property
    def available(self):
        return (
            bool(self.manager.document)
            and self.manager.available
            and (self.action == "restore_standard" or self.manager.context.get("ready"))
        )

    async def async_press(self):
        if self.action == "restore_standard":
            await self.manager.async_restore()
        else:
            await self.manager.async_save_standard()
