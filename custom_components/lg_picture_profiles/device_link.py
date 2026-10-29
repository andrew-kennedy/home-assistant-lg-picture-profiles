"""Link companion entities to the existing MQTT bridge device, without owning it."""

from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.helper_integration import async_remove_helper_devices

from .const import CONF_BRIDGE_TOPIC


class BridgeDeviceLink:
    """One registry listener per entry; no discovery subscription or polling."""

    def __init__(self, hass, entry):
        self.hass, self.entry = hass, entry
        config = entry.options or entry.data
        # The bridge's final topic segment is also its MQTT discovery device ID.
        self.identifier = ("mqtt", config[CONF_BRIDGE_TOPIC].rsplit("/", 1)[-1])
        self.device = None
        self._unsub = None

    @callback
    def async_start(self):
        self._unsub = self.hass.bus.async_listen(
            dr.EVENT_DEVICE_REGISTRY_UPDATED, self._registry_changed
        )
        self.async_sync()

    @callback
    def _registry_changed(self, event):
        device = dr.async_get(self.hass).async_get(event.data["device_id"])
        if (
            event.data["action"] == "remove"
            or "identifiers" in event.data.get("changes", {})
            or (self.device and event.data["device_id"] == self.device.id)
            or (device and self.identifier in device.identifiers)
        ):
            self.async_sync()

    @callback
    def async_sync(self):
        devices = dr.async_get(self.hass)
        matches = [
            device
            for device in devices.async_get_devices(identifiers={self.identifier})
            if (owner := self.hass.config_entries.async_get_entry(device.config_entry_id))
            and owner.domain == "mqtt"
        ]
        # Never choose arbitrarily if two MQTT config entries claim this bridge.
        previous = self.device
        self.device = matches[0] if len(matches) == 1 else None
        entities = er.async_get(self.hass)
        if self.device:
            # Core relinks registered entities (including disabled entities) and
            # removes only devices owned by this companion entry. It leaves the
            # MQTT device, entity identities and user customizations intact.
            async_remove_helper_devices(
                self.hass,
                helper_config_entry_id=self.entry.entry_id,
                source_device_id=self.device.id,
                remove_all_devices=True,
            )
        elif previous:
            for entity in er.async_entries_for_config_entry(entities, self.entry.entry_id):
                if entity.device_id == previous.id:
                    entities.async_update_entity(entity.entity_id, device_id=None)

    @callback
    def async_stop(self):
        if self._unsub:
            self._unsub()
            self._unsub = None
