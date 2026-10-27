"""Compact status; full profile documents never enter the recorder."""

from homeassistant.components.sensor import SensorEntity

from .entity import ProfileEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        [ProfileSensor(entry, "status"), ProfileSensor(entry, "temporary_adjustments")]
    )


class ProfileSensor(ProfileEntity, SensorEntity):
    def __init__(self, entry, key):
        super().__init__(entry, key)
        self.key = key
        self._attr_name = "Profile status" if key == "status" else "Temporary adjustments"
        self._attr_icon = "mdi:television-shimmer" if key == "status" else "mdi:tune-variant"

    @property
    def native_value(self):
        return self.manager.state if self.key == "status" else self.manager.override_count

    @property
    def extra_state_attributes(self):
        if self.key != "status":
            return None
        return {
            "room": self.manager.room,
            "active_devices": self.manager.active_names,
            "pending_restore": self.manager.data["pending_restore"],
            "last_changed_settings": self.manager.last_changed_count,
            "last_error": self.manager.last_error
            or self.manager.transport.manager_status.get("error"),
        }
