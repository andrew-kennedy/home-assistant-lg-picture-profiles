"""TV-owned named profiles discovered from complete backups; no polling."""

from homeassistant.components.select import SelectEntity
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import slugify

from .entity import ProfileEntity
from .model import addon_groups

ADDON_OFF = "Off (no add-on)"


async def async_setup_entry(hass, entry, async_add_entities):
    manager = entry.runtime_data
    known: set[str] = set()

    @callback
    def add_groups():
        # One select per add-on group, added when the TV's backup first lists it.
        groups = [g for g in addon_groups(manager.snapshot.get("document")) if g not in known]
        if groups:
            known.update(groups)
            async_add_entities([AddonSelection(entry, group) for group in groups])

    async_add_entities([ProfileSelection(entry)])
    add_groups()
    entry.async_on_unload(manager.async_add_listener(add_groups))


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
            **{p["id"]: p["name"] for p in document.get("profiles", []) if not p.get("group")},
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


class AddonSelection(ProfileEntity, SelectEntity):
    """The add-on chosen for one group, layered over the main profile."""

    _attr_icon = "mdi:layers-plus"

    def __init__(self, entry, group):
        super().__init__(entry, "addon_" + slugify(group))
        self.group = group
        self._attr_name = f"{group} add-on"

    @property
    def choices(self):
        profiles = addon_groups(self.manager.snapshot.get("document")).get(self.group, [])
        return {"none": ADDON_OFF, **{p["id"]: p["name"] for p in profiles}}

    @property
    def available(self):
        return (
            self.manager.available
            and self.group in addon_groups(self.manager.snapshot.get("document"))
            and self.manager.transport.manager_status.get("editor_api", 0) >= 10
        )

    @property
    def options(self):
        return list(self.choices.values())

    @property
    def current_option(self):
        status = self.manager.transport.manager_status
        selected = (status.get("addons", self.manager.snapshot.get("addons")) or {}).get(self.group)
        return self.choices.get(selected or "none", ADDON_OFF)

    @property
    def extra_state_attributes(self):
        status = self.manager.transport.manager_status
        selected = (status.get("addons", self.manager.snapshot.get("addons")) or {}).get(self.group)
        return {"group": self.group, "profile_id": selected}

    async def async_select_option(self, option):
        profile_id = next((pid for pid, name in self.choices.items() if name == option), None)
        if profile_id is None:
            raise HomeAssistantError("Add-ons changed; refresh the available choices")
        await self.manager.async_apply_addon(self.group, profile_id)
