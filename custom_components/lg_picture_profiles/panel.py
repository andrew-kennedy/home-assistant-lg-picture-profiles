"""Authenticated UI for the TV-owned editor; no new TV HTTP port or credentials."""

from pathlib import Path

import voluptuous as vol
from homeassistant.components import frontend, panel_custom, websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.exceptions import HomeAssistantError

from .backup import decode
from .const import DOMAIN

ASSET_ROOT = "/lg-picture-profiles-assets"
REGISTERED = DOMAIN + "_panel_registered"


async def async_register(hass, entry):
    if not hass.data.get(REGISTERED):
        await hass.http.async_register_static_paths(
            [StaticPathConfig(ASSET_ROOT, str(Path(__file__).parent / "frontend"), False)]
        )
        websocket_api.async_register_command(hass, editor_command)
        hass.data[REGISTERED] = True
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path="lg-picture-profiles-" + entry.entry_id.lower(),
        webcomponent_name="lg-picture-profiles-panel",
        sidebar_title=entry.title,
        sidebar_icon="mdi:television-shimmer",
        module_url=ASSET_ROOT + "/panel.js?v=0.4.8",
        embed_iframe=False,
        require_admin=True,
        config={"entry_id": entry.entry_id, "title": entry.title},
    )


def async_remove(hass, entry):
    frontend.async_remove_panel(hass, "lg-picture-profiles-" + entry.entry_id.lower())


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "lg_picture_profiles/editor",
        vol.Required("entry_id"): str,
        vol.Required("command"): dict,
    }
)
@websocket_api.async_response
async def editor_command(hass, connection, message):
    manager = hass.data.get(DOMAIN, {}).get(message["entry_id"])
    if manager is None:
        connection.send_error(
            message["id"], "not_found", "The picture profile integration is not loaded"
        )
        return
    command = dict(message["command"])
    action = command.pop("action", None)
    try:
        if action == "get":
            result = await manager.async_preview()
        elif action == "backup":
            result = await manager.async_export_backup()
        elif action == "restore_backup":
            decode(command.get("backup"))
            result = await manager.async_rpc(
                "restore_backup", backup=command["backup"], revision=command.get("revision")
            )
        elif action in (
            "inspect",
            "edit",
            "import",
            "initialize",
            "save",
            "restore",
            "set_enabled",
            "set_brightness",
        ):
            result = await manager.async_rpc(action, **command)
        else:
            raise HomeAssistantError("Unsupported editor action")
        connection.send_result(message["id"], result)
    except (HomeAssistantError, ValueError, TypeError) as error:
        connection.send_error(message["id"], "profile_error", str(error))
