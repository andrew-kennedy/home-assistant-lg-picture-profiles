"""Configure the existing MQTT bridge and optional brightness helpers."""

from __future__ import annotations

import re

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_BRIDGE_TOPIC,
    CONF_BRIGHT_HELPER,
    CONF_DARK_HELPER,
    CONF_GAME_HELPER,
    CONF_SUN_ENTITY,
    CONF_TV_ENTITY,
    DOMAIN,
)


def schema(defaults=None):
    values = defaults or {}
    fields = {
        vol.Required("name", default=values.get("name", "LG Picture Profiles")): str,
        vol.Required(CONF_BRIDGE_TOPIC, default=values.get(CONF_BRIDGE_TOPIC, "")): str,
        vol.Required(
            CONF_TV_ENTITY,
            **({"default": values[CONF_TV_ENTITY]} if values.get(CONF_TV_ENTITY) else {}),
        ): selector.EntitySelector(selector.EntitySelectorConfig(domain="media_player")),
        vol.Required(
            CONF_SUN_ENTITY, default=values.get(CONF_SUN_ENTITY, "sun.sun")
        ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sun")),
    }
    for key in (CONF_BRIGHT_HELPER, CONF_DARK_HELPER, CONF_GAME_HELPER):
        fields[vol.Optional(key, **({"default": values[key]} if values.get(key) else {}))] = (
            selector.EntitySelector(selector.EntitySelectorConfig(domain="input_number"))
        )
    return vol.Schema(fields)


def valid_topic(value):
    return (
        isinstance(value, str)
        and re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*", value)
        and len(value) <= 200
    )


class LGPictureProfilesConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            if not valid_topic(user_input.get(CONF_BRIDGE_TOPIC)):
                errors[CONF_BRIDGE_TOPIC] = "invalid_topic"
            else:
                await self.async_set_unique_id(user_input[CONF_BRIDGE_TOPIC])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=user_input["name"], data=user_input)
        return self.async_show_form(step_id="user", data_schema=schema(user_input), errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return LGPictureProfilesOptionsFlow()


class LGPictureProfilesOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        errors = {}
        if user_input is not None:
            if user_input.get(CONF_BRIDGE_TOPIC) != self.config_entry.data[CONF_BRIDGE_TOPIC]:
                errors[CONF_BRIDGE_TOPIC] = "bridge_change"
            else:
                return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=schema(
                user_input or {**self.config_entry.data, **self.config_entry.options}
            ),
            errors=errors,
        )
