"""Pure profile model. The TV's saved bank is the identity, not the active entity ID."""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from typing import Any

from .const import MAX_BANKS, ROOMS

PRESETS = {
    "filmMaker",
    "hdrFilmMaker",
    "game",
    "hdrGame",
    "dolbyHdrGame",
    "dolbyHdrCinema",
    "dolbyHdrCinemaBright",
}
RANGES = {"sdr", "sdrALLM", "hdr", "hdrALLM", "dolbyHdr", "dolbyHdrALLM"}
PICTURE_KEYS = set(
    (
        "backlight contrast brightness color tint sharpness colorTemperature colorGamut gamma gammaLevel "
        "peakBrightness hdrDynamicToneMapping expressionEnhancer dynamicContrast dynamicColor superResolution "
        "noiseReduction mpegNoiseReduction smoothGradation realCinema truMotionJudder truMotionBlur motionEyeCare motionProOLED "
        "aiHdrRemastering ambientLightCompensation filmmakerAmbientLight dolbyPrecisionDetail nearBlackDetail blackLevel"
    ).split()
)
GAME_KEYS = {
    "gameAdjustContrast",
    "gameBlackLevel",
    "gameColorDepth",
    "gameSharpness",
    "blackStabilizer",
    "whiteStabilizer",
    "lowLevelAdjustment",
}
PORT_KEYS = {
    "gameGenre",
    "inputOptimization",
    "gameOptimization",
    "enableALLM",
    "enableQFT",
    "enable144HzBooster",
    "uhdDeepColor",
    "freesync",
}


class ProfileError(ValueError):
    """The profile document or its target is invalid."""


def equal(left: Any, right: Any) -> bool:
    """LG returns some numbers as strings; preserve types but compare their meaning."""
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(equal(left[k], right[k]) for k in left)
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    return left is not None and right is not None and str(left) == str(right)


def target_key(target: dict) -> str:
    """Canonical scope, including app ownership for motion controls."""
    return json.dumps(target, sort_keys=True, separators=(",", ":"))


def bank_id(target: dict) -> str:
    return "bank_" + hashlib.sha256(target_key(target).encode()).hexdigest()[:16]


def allowed_keys(target: dict) -> set[str]:
    if not isinstance(target, dict) or set(target) - {"category", "dimension", "app_id"}:
        raise ProfileError("Invalid target fields")
    d = target.get("dimension")
    if not isinstance(d, dict) or not all(isinstance(v, str) for v in d.values()):
        raise ProfileError("Explicit string dimensions are required")
    if target.get("category") == "picture" and re.fullmatch(
        r"hdmi[1-4](?:_pc)?", d.get("input", "")
    ):
        if set(d) == {"input", "pictureMode"} and d["pictureMode"] in PRESETS:
            if "app_id" in target:
                if target["app_id"] != "com.webos.app." + d["input"].removesuffix("_pc"):
                    raise ProfileError("Wrong HDMI app binding")
                return {"truMotionMode"}
            return PICTURE_KEYS
        if (
            set(d) == {"input", "dynamicRange"}
            and d["dynamicRange"] in RANGES
            and "app_id" not in target
        ):
            return {"pictureMode"}
    if (
        target.get("category") == "other"
        and re.fullmatch(r"hdmi[1-4]", d.get("gameInput", ""))
        and "app_id" not in target
    ):
        if set(d) == {"gameInput"}:
            return PORT_KEYS
        if (
            set(d) == {"gameInput", "dynamicRange", "gameGenre"}
            and d["dynamicRange"] in RANGES
            and d["gameGenre"] in {"Standard", "FPS", "RPG", "RTS", "Sports", "USER"}
        ):
            return GAME_KEYS
    raise ProfileError("Unsupported saved-bank target")


def validate(document: dict) -> dict:
    """Validate imported state before replacing the active standard."""
    if (
        not isinstance(document, dict)
        or set(document) - {"schema", "name", "devices", "banks"}
        or document.get("schema") != 1
    ):
        raise ProfileError("Expected a schema 1 profile document")
    if not isinstance(document.get("name"), str) or not 1 <= len(document["name"]) <= 100:
        raise ProfileError("A profile collection name is required")
    devices = document.get("devices", {})
    if (
        not isinstance(devices, dict)
        or len(devices) > 20
        or any(
            not re.fullmatch(r"[a-z][a-z0-9_]{0,39}", k) or not isinstance(v, str) or len(v) > 80
            for k, v in devices.items()
        )
    ):
        raise ProfileError("Devices must map stable IDs to display names")
    banks = document.get("banks")
    if not isinstance(banks, list) or not 1 <= len(banks) <= MAX_BANKS:
        raise ProfileError("Expected 1–100 saved banks")
    seen_ids, seen_targets = set(), set()
    for bank in banks:
        if not isinstance(bank, dict) or set(bank) - {
            "id",
            "name",
            "devices",
            "target",
            "settings",
            "variants",
            "brightness_role",
        }:
            raise ProfileError("Invalid bank fields")
        bid = bank.get("id", "")
        if (
            not isinstance(bid, str)
            or not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", bid)
            or bid in {"__proto__", "constructor", "prototype"}
            or bid in seen_ids
        ):
            raise ProfileError("Bank IDs must be unique")
        if not isinstance(bank.get("name"), str) or not 1 <= len(bank["name"]) <= 120:
            raise ProfileError("Each bank needs a readable name")
        if not isinstance(bank.get("devices", []), list) or any(
            v not in devices for v in bank.get("devices", [])
        ):
            raise ProfileError("Unknown device binding")
        allowed = allowed_keys(bank.get("target"))
        tk = target_key(bank["target"])
        if tk in seen_targets:
            raise ProfileError("Devices sharing a TV bank must share one standard")
        seen_ids.add(bid)
        seen_targets.add(tk)
        settings = bank.get("settings")
        if (
            not isinstance(settings, dict)
            or not settings
            or len(settings) > 40
            or set(settings) - allowed
        ):
            raise ProfileError("Unreviewed or missing bank settings")
        variants = bank.get("variants", {})
        if (
            not isinstance(variants, dict)
            or set(variants) - set(ROOMS)
            or any(not isinstance(v, dict) or set(v) - settings.keys() for v in variants.values())
        ):
            raise ProfileError("Room variants may only override existing bank settings")
        for values in [settings, *variants.values()]:
            for key, value in values.items():
                if key == "pictureMode":
                    signal = bank["target"]["dimension"]["dynamicRange"].removesuffix("ALLM")
                    modes = {
                        "sdr": {"filmMaker", "game"},
                        "hdr": {"hdrFilmMaker", "hdrGame"},
                        "dolbyHdr": {"dolbyHdrCinema", "dolbyHdrCinemaBright", "dolbyHdrGame"},
                    }
                    if not isinstance(value, str) or value not in modes[signal]:
                        raise ProfileError(
                            "Picture mode must be a supported preset for its signal range"
                        )
                elif key == "blackLevel":
                    if (
                        not isinstance(value, dict)
                        or set(value)
                        != {"secam", "ntsc", "pal60", "ntsc443", "pal", "unknown", "paln", "palm"}
                        or any(v not in {"auto", "high", "low"} for v in value.values())
                    ):
                        raise ProfileError("Invalid HDMI black-level structure")
                elif not isinstance(value, (str, int, float, bool)) or len(str(value)) > 100:
                    raise ProfileError("Settings must be bounded scalar values")
        role = bank.get("brightness_role")
        if role not in (None, "movie_sdr", "game_sdr") or (role and "backlight" not in settings):
            raise ProfileError("Brightness roles require an OLED brightness setting")
    # Reject NaN/Infinity as well as oversized documents.
    if len(json.dumps(document, allow_nan=False)) > 200000:
        raise ProfileError("Profile document is too large")
    return deepcopy(document)


def desired(
    bank: dict, room: str, lights: dict | None = None, overrides: dict | None = None
) -> dict:
    values = deepcopy(bank["settings"])
    values.update(bank.get("variants", {}).get(room, {}))
    role = bank.get("brightness_role")
    if role and lights and role in lights:
        values["backlight"] = lights[role]
    values.update(overrides or {})
    return values


def environment_keys(bank: dict) -> set[str]:
    keys = {k for variant in bank.get("variants", {}).values() for k in variant}
    if bank.get("brightness_role"):
        keys.add("backlight")
    return keys


def is_active(bank: dict, context: dict) -> bool:
    d = bank["target"]["dimension"]
    if "input" in d and d["input"] != context.get("input"):
        return False
    if "gameInput" in d and d["gameInput"] != str(context.get("input", "")).removesuffix("_pc"):
        return False
    if "pictureMode" in d and d["pictureMode"] != context.get("mode"):
        return False
    if "dynamicRange" in d and d["dynamicRange"] != context.get("range"):
        return False
    # Only one Game Optimizer genre is active. Obtain it from the scoped change,
    # rather than assuming all genre banks belong to the current view.
    if "gameGenre" in d and d["gameGenre"] != context.get("gameGenre", "Standard"):
        return False
    return True


def find_bank(document: dict, target: dict, key: str) -> dict | None:
    tk = target_key(target)
    return next(
        (b for b in document["banks"] if target_key(b["target"]) == tk and key in b["settings"]),
        None,
    )


def apply_standard_value(bank: dict, room: str, key: str, value: Any) -> None:
    """An explicit save changes the current room variant when one exists."""
    if key in environment_keys(bank) and bank.get("variants"):
        bank.setdefault("variants", {}).setdefault(room, {})[key] = value
    else:
        bank["settings"][key] = value
