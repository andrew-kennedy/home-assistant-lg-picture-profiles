from copy import deepcopy
from types import SimpleNamespace

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.lg_picture_profiles.manager import ProfileManager
from custom_components.lg_picture_profiles.model import equal


def document():
    return {
        "schema": 1,
        "name": "Living room",
        "devices": {"switch": "Nintendo", "apple": "Apple TV", "shield": "Shield"},
        "banks": [
            {
                "id": "movie_sdr",
                "name": "Shared SDR movie",
                "devices": ["apple", "shield"],
                "target": {
                    "category": "picture",
                    "dimension": {"input": "hdmi3", "pictureMode": "filmMaker"},
                },
                "settings": {"backlight": "3", "peakBrightness": "off", "color": "50"},
                "variants": {
                    "bright": {"backlight": 100, "peakBrightness": "high"},
                    "dark": {"backlight": 3, "peakBrightness": "off"},
                },
                "brightness_role": "movie_sdr",
            },
            {
                "id": "game_hdr",
                "name": "Nintendo HDR Game controls",
                "devices": ["switch"],
                "target": {
                    "category": "other",
                    "dimension": {
                        "gameInput": "hdmi3",
                        "dynamicRange": "hdrALLM",
                        "gameGenre": "Standard",
                    },
                },
                "settings": {"gameColorDepth": 50, "gameSharpness": 0, "gameAdjustContrast": 100},
            },
            {
                "id": "dv_mapping",
                "name": "Shared Dolby Vision selection",
                "devices": ["apple", "shield"],
                "target": {
                    "category": "picture",
                    "dimension": {"input": "hdmi3", "dynamicRange": "dolbyHdr"},
                },
                "settings": {"pictureMode": "dolbyHdrCinema"},
                "variants": {
                    "bright": {"pictureMode": "dolbyHdrCinemaBright"},
                    "dark": {"pictureMode": "dolbyHdrCinema"},
                },
            },
        ],
    }


class MemoryStore:
    def __init__(self, saved=None):
        self.saved = deepcopy(saved)
        self.saves = 0

    async def async_load(self):
        return deepcopy(self.saved)

    async def async_save(self, value):
        self.saved = deepcopy(value)
        self.saves += 1


class FakeTransport:
    available = True

    def __init__(self, doc):
        self.values = {b["id"]: deepcopy(b["settings"]) for b in doc["banks"]}
        self.calls = []
        self.fail_apply = False
        self.on_read = None
        self.on_apply = None

    async def async_start(self):
        pass

    async def async_stop(self):
        pass

    async def async_command(self, action, banks):
        self.calls.append((action, deepcopy(banks)))
        if action == "read" and self.on_read:
            hook, self.on_read = self.on_read, None
            await hook()
        if action == "apply" and self.fail_apply:
            raise HomeAssistantError("injected failure")
        results = []
        for bank in banks:
            current = self.values[bank["id"]]
            changed = []
            if action == "apply":
                for key, value in bank["settings"].items():
                    if equal(current[key], value):
                        continue
                    if not equal(current[key], bank["expected"][key]):
                        raise HomeAssistantError("profile_conflict")
                    current[key] = value
                    changed.append(key)
            keys = bank.get("keys", bank.get("settings", {}))
            results.append(
                {
                    "id": bank["id"],
                    "target": bank["target"],
                    "settings": {k: current[k] for k in keys},
                    "changed": changed,
                }
            )
        if action == "apply" and self.on_apply:
            hook, self.on_apply = self.on_apply, None
            await hook()
        return {"action": action, "banks": results}


@pytest.fixture
async def manager(tmp_path):
    hass = HomeAssistant(str(tmp_path))
    hass.states.async_set("media_player.tv", "on")
    hass.states.async_set("sun.sun", "below_horizon")
    doc = document()
    transport, store = FakeTransport(doc), MemoryStore()
    entry = SimpleNamespace(
        entry_id="test",
        data={"bridge_topic": "lg/test", "tv_entity": "media_player.tv", "sun_entity": "sun.sun"},
        options={},
    )
    manager = ProfileManager(hass, entry, transport=transport, store=store)
    manager._schedule_sync = lambda: None
    await manager.async_import(doc)
    await manager.async_enable(True)
    manager.data["tracked_since"] = "2020-01-01T00:00:00.000Z"
    manager.context = {"input": "hdmi3", "mode": "hdrGame", "range": "hdrALLM", "ready": True}
    yield manager
    await manager.async_stop()
    await hass.async_stop()


async def adjust(manager, bank_id, key, value, rid="user-1"):
    bank = next(b for b in manager.document["banks"] if b["id"] == bank_id)
    manager.transport.values[bank_id][key] = value
    await manager.async_user_results(
        {
            rid: {
                "ok": True,
                "completed_at": "2026-10-27T12:00:00.000Z",
                "applied": {
                    "kind": "user_setting",
                    "target": bank["target"],
                    "key": key,
                    "value": value,
                },
            }
        }
    )
