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
    "normal", "vivid", "cinema", "expert1", "expert2", "eco", "personalized", "sports", "photo",
    "hdrStandard", "hdrVivid", "hdrCinema", "hdrCinemaBright", "hdrEco", "hdrPersonalized",
    "dolbyHdrStandard", "dolbyHdrVivid", "dolbyHdrPersonalized",
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


def validate_catalog(document: dict) -> set[str]:
    """Validate named overlays while retaining the exact native bank identities."""
    roles = {"game_sdr", "movie_sdr"}

    def brightness(value, complete=False):
        if (
            not isinstance(value, dict)
            or set(value) - roles
            or complete
            and set(value) != roles
            or any(type(v) is not int or not 0 <= v <= 100 for v in value.values())
        ):
            raise ProfileError("Invalid shared profile brightness")

    brightness(document.get("brightness"), True)
    profiles = document.get("profiles")
    if not isinstance(profiles, list) or len(profiles) > 32:
        raise ProfileError("Expected up to 32 named profiles")
    ids, names = set(), {"automatic", "base standard"}
    for profile in profiles:
        if not isinstance(profile, dict) or set(profile) - {"id", "name", "brightness"}:
            raise ProfileError("Invalid named profile")
        pid, name = profile.get("id"), profile.get("name")
        if (
            not isinstance(pid, str)
            or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", pid)
            or pid in {"constructor", "prototype", "__proto__", "standard", "automatic"}
            or pid in ids
        ):
            raise ProfileError("Profile IDs must be unique")
        if (
            not isinstance(name, str)
            or not 1 <= len(name) <= 64
            or name != name.strip()
            or re.search(r"[\x00-\x1f\x7f]", name)
            or name.lower() in names
        ):
            raise ProfileError("Choose a unique profile name")
        brightness(profile.get("brightness", {}))
        ids.add(pid)
        names.add(name.lower())
    automatic = document.get("automatic")
    if (
        not isinstance(automatic, dict)
        or set(automatic) != {"bright", "dark"}
        or any(not isinstance(v, str) or v not in ids | {"standard"} for v in automatic.values())
    ):
        raise ProfileError("Invalid automatic profile bindings")
    return ids


def validate(document: dict) -> dict:
    """Validate imported state before replacing the active standard."""
    if (
        not isinstance(document, dict)
        or set(document)
        - {
            "schema",
            "name",
            "devices",
            "banks",
            *({"profiles", "brightness", "automatic"} if document.get("schema") == 2 else set()),
        }
        or document.get("schema") not in (1, 2)
    ):
        raise ProfileError("Expected a schema 1 or 2 profile document")
    if not isinstance(document.get("name"), str) or not 1 <= len(document["name"]) <= 100:
        raise ProfileError("A profile collection name is required")
    profile_ids = validate_catalog(document) if document["schema"] == 2 else set(ROOMS)
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
    if not isinstance(banks, list) or not (0 if document["schema"] == 2 else 1) <= len(banks) <= MAX_BANKS:
        raise ProfileError("Expected up to 768 saved banks")
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
            or set(variants) - profile_ids
            or any(not isinstance(v, dict) or set(v) - settings.keys() for v in variants.values())
        ):
            raise ProfileError("Room variants may only override existing bank settings")
        for values in [settings, *variants.values()]:
            for key, value in values.items():
                if key == "pictureMode":
                    signal = bank["target"]["dimension"]["dynamicRange"].removesuffix("ALLM")
                    mode_format = (
                        "dolbyHdr" if isinstance(value, str) and value.startswith("dolbyHdr")
                        else "hdr" if isinstance(value, str) and value.startswith("hdr")
                        else "sdr"
                    )
                    if not isinstance(value, str) or value not in PRESETS or mode_format != signal:
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
    if len(json.dumps(document, allow_nan=False)) > 500000:
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
    if "gameGenre" in d and not str(context.get("mode", "")).lower().endswith("game"):
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
