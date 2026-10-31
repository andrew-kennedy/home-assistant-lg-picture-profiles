"""Complete TV-owned snapshots; no profile data is placed in Recorder attributes."""

import hashlib
import json
from datetime import datetime

from .model import ProfileError, validate


def decode(envelope: dict) -> dict:
    if (
        not isinstance(envelope, dict)
        or envelope.get("protocol") != 1
        or envelope.get("format") != "lg-picture-bridge-backup"
        or not isinstance(envelope.get("state_json"), str)
        or len(envelope["state_json"].encode()) > 750000
        or hashlib.sha256(envelope["state_json"].encode()).hexdigest() != envelope.get("sha256")
    ):
        raise ProfileError("Invalid backup format or checksum")
    state = json.loads(envelope["state_json"])
    if (
        not isinstance(state, dict)
        or state.get("schema") != 1
        or any(
            not isinstance(state.get(k), str) or not 1 <= len(state[k]) <= 128
            for k in ("owner_id", "instance_id")
        )
        or any(type(state.get(k)) is not int or state[k] < 1 for k in ("sequence", "revision"))
        or type(state.get("enabled")) is not bool
        or state.get("room") not in ("bright", "dark")
    ):
        raise ProfileError("Invalid backup identity")
    validate(state.get("document"))
    native = state.get("native_snapshot")
    if native is not None:
        if not isinstance(native, dict) or set(native) != {"captured_at", "updated_at", "document"}:
            raise ProfileError("Invalid native snapshot")
        try:
            for key in ("captured_at", "updated_at"):
                datetime.fromisoformat(native[key])
        except (ValueError, TypeError) as error:
            raise ProfileError("Invalid native snapshot timestamp") from error
        validate(native["document"])
        if native["document"]["schema"] != 1 or any(
            "variants" in bank or "brightness_role" in bank
            for bank in native["document"]["banks"]
        ):
            raise ProfileError("Native snapshots contain values, not profile policy")
    if state["document"]["schema"] == 2:
        ids = {p["id"] for p in state["document"]["profiles"]} | {"standard"}
        if (
            state.get("selection") not in ids | {"automatic"}
            or state.get("active_profile") not in ids
        ):
            raise ProfileError("Invalid selected profile")
    prefs = state.get("preferences")
    if (
        not isinstance(prefs, dict)
        or set(prefs) != {"movie_bright", "movie_dark", "game_sdr"}
        or any(type(v) is not int or not 0 <= v <= 100 for v in prefs.values())
    ):
        raise ProfileError("Invalid backup brightness preferences")
    banks = {b["id"]: b for b in state["document"]["banks"]}
    overrides = state.get("overrides")
    if not isinstance(overrides, dict):
        raise ProfileError("Invalid backup adjustments")
    for bid, values in overrides.items():
        if (
            bid not in banks
            or not isinstance(values, dict)
            or set(values) - banks[bid]["settings"].keys()
        ):
            raise ProfileError("Invalid backup adjustment scope")
    recovery = state.get("recovery")
    if not isinstance(recovery, dict):
        raise ProfileError("Invalid recovery journal")
    for key in ("dirty", "restore"):
        scopes = recovery.get(key)
        if not isinstance(scopes, dict):
            raise ProfileError("Invalid recovery scopes")
        for bid, keys in scopes.items():
            if (
                bid not in banks
                or not isinstance(keys, list)
                or any(k not in banks[bid]["settings"] for k in keys)
            ):
                raise ProfileError("Invalid recovery bank")
    return state
