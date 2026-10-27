"""Home Assistant companion for LG Picture Bridge."""

from __future__ import annotations

import logging

import voluptuous as vol
import yaml
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.storage import Store

from . import panel
from .backup import decode
from .const import DOMAIN, PLATFORMS, STORAGE_VERSION
from .manager import ProfileManager
from .model import ProfileError

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
type LGProfilesEntry = ConfigEntry[ProfileManager]
_LOGGER = logging.getLogger(__name__)


async def async_migrate_entry(hass: HomeAssistant, entry: LGProfilesEntry) -> bool:
    """Retire helper bindings after their values have reached TV-owned storage."""
    if entry.version > 2:
        return False
    if entry.version == 1:
        retired = {"bright_helper", "dark_helper", "game_helper"}
        current = entry.options or entry.data
        if any(current.get(key) for key in retired):
            stored = await Store(
                hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}", atomic_writes=True
            ).async_load()
            try:
                if not stored or not stored.get("migration_complete"):
                    raise ValueError("TV ownership migration is incomplete")
                decode(stored.get("backup"))
            except ValueError, TypeError, KeyError:
                _LOGGER.error(
                    "Complete TV profile migration using LG Picture Profiles 0.3.2 "
                    "before upgrading; existing helper values have not been backed up"
                )
                return False
        hass.config_entries.async_update_entry(
            entry,
            data={k: v for k, v in entry.data.items() if k not in retired},
            options={k: v for k, v in entry.options.items() if k not in retired},
            version=2,
            minor_version=1,
        )
    return True


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
        await panel.async_register(hass, entry)
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
    panel.async_remove(hass, entry)
    hass.data[DOMAIN].pop(entry.entry_id, None)
    if not hass.data[DOMAIN]:
        for name in (
            "import_profiles",
            "export_profiles",
            "restore_standard",
            "save_standard",
            "reconcile",
            "preview",
            "export_backup",
            "restore_backup",
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
            if call.service == "export_backup":
                return await manager.async_export_backup(call.data.get("previous", 0))
            if call.service == "restore_backup":
                return await manager.async_restore_backup(call.data["backup"])
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
        "export_backup",
        "restore_backup",
    ):
        fields = dict(base)
        if name == "import_profiles":
            fields.update({vol.Optional("document"): dict, vol.Optional("yaml"): str})
        if name == "restore_backup":
            fields[vol.Required("backup")] = dict
        if name == "export_backup":
            fields[vol.Optional("previous", default=0)] = vol.All(
                vol.Coerce(int), vol.Range(min=0, max=5)
            )
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
            if name in ("export_profiles", "preview", "export_backup")
            else SupportsResponse.OPTIONAL,
        )
