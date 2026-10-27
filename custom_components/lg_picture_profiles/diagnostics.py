"""Troubleshoot without disclosing broker credentials or personal profiles."""


async def async_get_config_entry_diagnostics(hass, entry):
    manager = entry.runtime_data
    return {
        "state": manager.state,
        "bridge_available": manager.transport.available,
        "room": manager.room,
        "bank_count": len(manager.document["banks"]) if manager.document else 0,
        "override_count": manager.override_count,
        "pending_restore": manager.data["pending_restore"],
        "last_error": manager.last_error,
    }
