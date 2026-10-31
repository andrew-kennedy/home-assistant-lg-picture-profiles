"""TV-owned named profiles discovered from complete backups; no polling."""

from homeassistant.components.select import SelectEntity
from homeassistant.exceptions import HomeAssistantError

from .entity import ProfileEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([ProfileSelection(entry)])


class ProfileSelection(ProfileEntity, SelectEntity):
    _attr_name = "Picture profile"
    _attr_icon = "mdi:television-shimmer"

    def __init__(self, entry):
        super().__init__(entry, "picture_profile")

    @property
    def choices(self):
        document = self.manager.snapshot.get("document") or {}
        return {
            "automatic": "Automatic",
            "standard": "Base standard",
            **{p["id"]: p["name"] for p in document.get("profiles", [])},
        }

    @property
    def available(self):
        return (
            self.manager.available
            and (self.manager.snapshot.get("document") or {}).get("schema") == 2
            and self.manager.transport.manager_status.get("editor_api", 0) >= 6
        )

    @property
    def options(self):
        return list(self.choices.values())

    @property
    def current_option(self):
        status = self.manager.transport.manager_status
        selected = status.get("selection", self.manager.snapshot.get("selection", "automatic"))
        return self.choices.get(selected)

    @property
    def extra_state_attributes(self):
        status = self.manager.transport.manager_status
        return {
            key: status.get(key, self.manager.snapshot.get(key))
            for key in ("selection", "active_profile")
        }

    async def async_select_option(self, option):
        profile_id = next((pid for pid, name in self.choices.items() if name == option), None)
        if profile_id is None:
            raise HomeAssistantError("Profile changed; refresh the available profiles")
        await self.manager.async_apply_profile(profile_id)
