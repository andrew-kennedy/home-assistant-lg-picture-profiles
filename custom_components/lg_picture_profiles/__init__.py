"""Home Assistant companion for LG Picture Bridge."""

from __future__ import annotations

import voluptuous as vol
import yaml
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN, PLATFORMS
from .manager import ProfileManager
from .model import ProfileError

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
type LGProfilesEntry = ConfigEntry[ProfileManager]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: LGProfilesEntry) -> bool:
    manager = ProfileManager(hass, entry)
    entry.runtime_data = manager
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = manager
    try:
        await manager.async_start()
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        await manager.async_stop()
        hass.data[DOMAIN].pop(entry.entry_id, None)
        raise
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    _register_services(hass)
    return True


async def async_reload_entry(hass: HomeAssistant, entry: LGProfilesEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: LGProfilesEntry) -> bool:
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    await entry.runtime_data.async_stop()
    hass.data[DOMAIN].pop(entry.entry_id, None)
    if not hass.data[DOMAIN]:
        for name in (
            "import_profiles",
            "export_profiles",
            "restore_standard",
            "save_standard",
            "reconcile",
            "preview",
        ):
            hass.services.async_remove(DOMAIN, name)
    return True


def _register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, "import_profiles"):
        return
    base = {vol.Optional("entry_id"): str}

    async def handle(call: ServiceCall):
        managers = hass.data.get(DOMAIN, {})
        manager = (
            managers.get(call.data.get("entry_id"))
            if call.data.get("entry_id")
            else next(iter(managers.values()))
            if len(managers) == 1
            else None
        )
        if manager is None:
            raise HomeAssistantError("Select a loaded LG Picture Profiles entry")
        try:
            if call.service == "import_profiles":
                if ("document" in call.data) == ("yaml" in call.data):
                    raise HomeAssistantError("Supply either document or yaml")
                text = call.data.get("yaml", "")
                if len(text) > 200000:
                    raise HomeAssistantError("Profile document is too large")
                document = (
                    call.data.get("document") if "document" in call.data else yaml.safe_load(text)
                )
                return await manager.async_import(document)
            if call.service == "export_profiles":
                document = await manager.async_export()
                return {
                    "document": document,
                    "yaml": yaml.safe_dump(document, sort_keys=False, allow_unicode=True),
                }
            if call.service == "restore_standard":
                return await manager.async_restore(call.data.get("scope", "all"))
            if call.service == "save_standard":
                return await manager.async_save_standard(call.data.get("scope", "active"))
            if call.service == "preview":
                return await manager.async_preview()
            return await manager.async_reconcile()
        except (ProfileError, ValueError, yaml.YAMLError) as error:
            raise HomeAssistantError(str(error)) from error

    for name in (
        "import_profiles",
        "export_profiles",
        "restore_standard",
        "save_standard",
        "reconcile",
        "preview",
    ):
        fields = dict(base)
        if name == "import_profiles":
            fields.update({vol.Optional("document"): dict, vol.Optional("yaml"): str})
        if name in ("restore_standard", "save_standard"):
            fields[
                vol.Optional("scope", default="all" if name == "restore_standard" else "active")
            ] = vol.In(["active", "all"])
        hass.services.async_register(
            DOMAIN,
            name,
            handle,
            schema=vol.Schema(fields),
            supports_response=SupportsResponse.ONLY
            if name in ("export_profiles", "preview")
            else SupportsResponse.OPTIONAL,
        )
