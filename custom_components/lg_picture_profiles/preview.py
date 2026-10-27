"""Readable preview of tracked changes, without the native-bank or backup payload."""

from .model import desired, equal


def summarize(snapshot: dict, *, available: bool, backup_saved: bool, error=None) -> dict:
    state = snapshot.get("state") or {}
    status = snapshot.get("status") or {}
    document = state.get("document") or {}
    banks = document.get("banks", [])
    devices = document.get("devices", {})
    room = state.get("room")
    preferences = state.get("preferences", {})
    lights = {
        "movie_sdr": preferences.get("movie_" + room) if room in ("bright", "dark") else None,
        "game_sdr": preferences.get("game_sdr"),
    }
    lights = {role: value for role, value in lights.items() if value is not None}
    adjustments = []
    for bank in banks:
        standard = desired(bank, room, lights)
        changes = {
            key: {"standard": standard[key], "temporary": value}
            for key, value in state.get("overrides", {}).get(bank["id"], {}).items()
            if key in standard and not equal(value, standard[key])
        }
        if changes:
            adjustments.append(
                {
                    "profile": bank["name"],
                    "devices": [devices.get(device, device) for device in bank.get("devices", [])],
                    "changes": changes,
                }
            )
    context = status.get("context", state.get("context", {}))
    power = status.get("power") if available else None
    active = None
    if available and power == "on" and context.get("ready"):
        active = {
            "input": context.get("input"),
            "signal": context.get("range"),
            "picture_mode": context.get("mode"),
            "devices": status.get("active_devices", []),
        }
    recovery = state.get("recovery", {})
    pending = recovery.get("restore", {})
    sequence = status.get("backup_sequence")
    confirmed = available and sequence is not None and sequence == status.get("backup_acknowledged")
    return {
        "source": "bridge_snapshot"
        if available
        else "saved_backup"
        if backup_saved
        else "saved_configuration",
        "snapshot_at": state.get("created_at"),
        "collection": document.get("name"),
        "revision": state.get("revision"),
        "management_enabled": bool(state.get("enabled")),
        "tv_power": power or "unknown",
        "room": room,
        "sdr_brightness": preferences,
        "active_picture": active,
        "temporary_adjustments": adjustments,
        "pending_restore": {
            "banks": len(pending),
            "settings": sum(len(keys) for keys in pending.values()),
        },
        "reconstructing_adjustments": bool(recovery.get("reconstructing")),
        "applying": bool(status.get("applying")) if available else False,
        "backup": "confirmed"
        if confirmed
        else "pending"
        if available
        else "saved"
        if backup_saved
        else "none",
        "error": error or status.get("error"),
    }
