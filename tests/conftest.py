from copy import deepcopy
from types import SimpleNamespace

import pytest
from homeassistant.core import HomeAssistant

from custom_components.lg_picture_profiles.manager import ProfileManager


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
    api_version = 2
    session = "session"

    def __init__(self, doc=None):
        self.manager_status = {
            "configured": False,
            "instance_id": "tv-process",
            "owner_id": "tv-owner",
            "revision": 1,
        }
        self.calls = []
        self.acks = []
        self.contexts = []

    async def async_start(self):
        pass

    async def async_stop(self):
        pass

    async def async_command(self, action, banks=None, **fields):
        self.calls.append((action, deepcopy(fields)))
        return {"ok": True}

    async def async_publish_context(self, room):
        self.contexts.append(room)

    async def async_ack_backup(self, state, checksum):
        self.acks.append((deepcopy(state), checksum))


@pytest.fixture
async def manager(tmp_path):
    hass = HomeAssistant(str(tmp_path))
    hass.states.async_set("media_player.tv", "on")
    hass.states.async_set("sun.sun", "below_horizon")
    entry = SimpleNamespace(
        entry_id="test",
        data={"bridge_topic": "lg/test", "tv_entity": "media_player.tv", "sun_entity": "sun.sun"},
        options={},
    )
    result = ProfileManager(hass, entry, transport=FakeTransport(), store=MemoryStore())
    result._schedule_sync = lambda: None
    await result.async_start()
    yield result
    await result.async_stop()
    await hass.async_stop()
