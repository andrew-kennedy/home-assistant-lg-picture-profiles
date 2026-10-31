"""A controller and durable backup receiver. The TV is the only policy writer."""

from __future__ import annotations

import asyncio
from copy import deepcopy

from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store

from .backup import decode
from .const import (
    BRIGHTNESS_ROLES,
    CONF_BRIDGE_TOPIC,
    CONF_SUN_ENTITY,
    CONF_TV_ENTITY,
    DOMAIN,
    STORAGE_VERSION,
)
from .model import validate
from .transport import BridgeTransport


class ProfileManager:
    def __init__(self, hass, entry, *, transport=None, store=None):
        self.hass, self.entry = hass, entry
        self.config = dict(entry.options or entry.data)
        self.store = store or Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}", atomic_writes=True
        )
        self.saved = {
            "format": 2,
            "backup": None,
            "previous": [],
            "migration_complete": False,
        }
        self.snapshot: dict = {}
        self.last_error = None
        self._listeners = set()
        self._jobs = set()
        self._unsub = None
        self._stopping = False
        self._loaded = False
        self._lock = asyncio.Lock()
        self._control_lock = asyncio.Lock()
        self._candidate = None
        self._connection = None
        self._sync_task = None
        self._sync_again = False
        self.devices = None
        self.transport = transport or BridgeTransport(
            hass,
            self.config[CONF_BRIDGE_TOPIC],
            self._bridge_changed,
            backup=self._receive_backup,
        )

    @property
    def document(self):
        return self.snapshot.get("document") or (self.saved.get("legacy") or {}).get("document")

    @property
    def data(self):
        status = self.transport.manager_status
        return {
            "document": self.document,
            "enabled": status.get("enabled", self.snapshot.get("enabled", False)),
            "pending_restore": status.get(
                "pending_restore", bool(self.snapshot.get("recovery", {}).get("restore"))
            ),
            "overrides": self.snapshot.get("overrides", {}),
        }

    @property
    def context(self):
        return self.transport.manager_status.get("context", {}) if self.available else {}

    @property
    def override_count(self):
        return self.transport.manager_status.get(
            "temporary_count", sum(len(v) for v in self.snapshot.get("overrides", {}).values())
        )

    @property
    def room(self):
        state = self.hass.states.get(self.config.get(CONF_SUN_ENTITY, "sun.sun"))
        return {"above_horizon": "bright", "below_horizon": "dark"}.get(
            state.state if state else None
        )

    @property
    def available(self):
        return self.transport.available and self.transport.api_version >= 2

    @property
    def state(self):
        if self.last_error or self.transport.manager_status.get("error"):
            return "error"
        if self.saved.get("legacy") and not self.saved["migration_complete"]:
            return "awaiting_tv_migration"
        if not self.document:
            return "unconfigured"
        if not self.available:
            return "offline"
        if not self.data["enabled"]:
            return "disabled"
        if self.data["pending_restore"]:
            return "pending_restore"
        return "applying" if self.transport.manager_status.get("applying") else "ready"

    @property
    def active_names(self):
        return self.transport.manager_status.get("active_devices", []) if self.available else []

    @property
    def last_changed_count(self):
        return self.transport.manager_status.get("changed_count", 0)

    @property
    def revision(self):
        return self.transport.manager_status.get("revision", self.snapshot.get("revision", 0))

    @callback
    def async_add_listener(self, listener):
        self._listeners.add(listener)
        return lambda: self._listeners.discard(listener)

    @callback
    def notify(self):
        for listener in tuple(self._listeners):
            listener()

    def _spawn(self, coro):
        if self._stopping:
            coro.close()
            return

        async def run():
            try:
                await coro
            except (HomeAssistantError, ValueError, OSError) as error:
                self.last_error = str(error)
                self.notify()

        task = self.hass.async_create_task(run())
        self._jobs.add(task)
        task.add_done_callback(self._jobs.discard)

    async def async_start(self):
        value = await self.store.async_load()
        if value:
            if value.get("format") == 2:
                self.saved.update(value)
                if self.saved["backup"]:
                    self.snapshot = decode(self.saved["backup"])
                    if self.saved["migration_complete"] and "legacy" in self.saved:
                        saved = deepcopy(self.saved)
                        saved.pop("legacy")
                        await self.store.async_save(saved)
                        self.saved = saved
            else:
                if value.get("document"):
                    validate(value["document"])
                # Keep the former HA document/journal until a complete migrated
                # TV backup has been validated and durably saved.
                # The retired HA policy writer never runs during migration.
                self.saved["legacy"] = value
                await self.store.async_save(deepcopy(self.saved))
        self._loaded = True
        ids = [self.config.get(CONF_SUN_ENTITY, "sun.sun"), self.config[CONF_TV_ENTITY]]
        self._unsub = async_track_state_change_event(self.hass, ids, self._state_changed)
        await self.transport.async_start()
        self._schedule_sync()

    @callback
    def _bridge_changed(self):
        manager = self.transport.manager_status
        connection = (
            self.available,
            self.transport.session,
            manager.get("instance_id"),
            manager.get("configured"),
        )
        if connection != self._connection:
            self._connection = connection
            self._schedule_sync()
        self.notify()

    def _schedule_sync(self):
        if self._stopping:
            return
        if self._sync_task and not self._sync_task.done():
            self._sync_again = True
            return
        self._sync_task = self.hass.async_create_task(self._sync())

    async def _sync(self):
        while True:
            self._sync_again = False
            await self._sync_once()
            if not self._sync_again:
                return

    async def _sync_once(self):
        try:
            if self._candidate:
                await self._accept_backup(self._candidate)
            if not self.available:
                return
            if self.room:
                await self.transport.async_publish_context(self.room)
            legacy = self.saved.get("legacy")
            status = self.transport.manager_status
            if legacy and legacy.get("document") and not self.saved["migration_complete"]:
                if status.get("configured"):
                    async with self._lock:
                        if self.snapshot.get("migration_id") == self.entry.entry_id:
                            saved = deepcopy(self.saved)
                            saved["migration_complete"] = True
                            saved.pop("legacy", None)
                            await self.store.async_save(saved)
                            self.saved = saved
                        elif self.snapshot:
                            raise HomeAssistantError(
                                "TV already has a profile collection; download the saved HA standards before choosing which collection to keep"
                            )
                else:
                    prefs = {"movie_bright": 100, "movie_dark": 3, "game_sdr": 80}
                    await self.transport.async_command(
                        "initialize",
                        document=legacy["document"],
                        enabled=bool(legacy.get("enabled")),
                        preferences=prefs,
                        overrides=legacy.get("overrides", {}),
                        restore=legacy.get("restore_requests", {}),
                        pending_restore=legacy.get("pending_restore", False),
                        room=self.room or "dark",
                        migration_id=self.entry.entry_id,
                    )
            self.last_error = None
        except (HomeAssistantError, ValueError) as error:
            self.last_error = str(error)
        finally:
            self.notify()

    @callback
    def _state_changed(self, event):
        old, new = event.data.get("old_state"), event.data.get("new_state")
        if not new or old and old.state == new.state:
            return
        if new.entity_id == self.config.get(CONF_SUN_ENTITY, "sun.sun"):
            self._schedule_sync()
        # TV power never runs HA-side picture writes. The TV owns restoration.

    @callback
    def _receive_backup(self, envelope):
        try:
            decode(envelope)
        except ValueError, TypeError, KeyError:
            return
        self._candidate = envelope
        self._spawn(self._accept_backup(envelope))

    async def _accept_backup(self, envelope):
        async with self._lock:
            state = decode(envelope)
            current = self.snapshot
            status = self.transport.manager_status
            if current:
                same_instance = (
                    state["instance_id"] == current["instance_id"]
                    and state["owner_id"] == current["owner_id"]
                )
                if same_instance and state["sequence"] < current["sequence"]:
                    return
                if not same_instance and (
                    not self.available
                    or state["instance_id"] != status.get("instance_id")
                    or state["owner_id"] != status.get("owner_id")
                ):
                    return
                if same_instance and state["sequence"] == current["sequence"]:
                    if envelope["sha256"] == self.saved["backup"]["sha256"]:
                        await self.transport.async_ack_backup(state, envelope["sha256"])
                    if self._candidate is envelope:
                        self._candidate = None
                    return
            saved = deepcopy(self.saved)
            if saved["backup"] and (
                state["revision"] != current.get("revision")
                or state["owner_id"] != current.get("owner_id")
            ):
                saved["previous"] = (saved["previous"] + [saved["backup"]])[-5:]
            saved["backup"] = deepcopy(envelope)
            if state.get("migration_id") == self.entry.entry_id or not saved.get("legacy"):
                saved["migration_complete"] = True
            if saved["migration_complete"]:
                saved.pop("legacy", None)
            # The ack means HA committed the whole snapshot, not merely received it.
            await self.store.async_save(saved)
            self.saved = saved
            self.snapshot = state
            await self.transport.async_ack_backup(state, envelope["sha256"])
            if self._candidate is envelope:
                self._candidate = None
            self.notify()

    async def async_rpc(self, action, **fields):
        if not self.available:
            raise HomeAssistantError(
                "Turn on the TV with LG Picture Bridge 0.13.2 or newer to change its profiles"
            )
        async with self._control_lock:
            return await self.transport.async_command(action, **fields)

    async def async_import(self, document):
        document = validate(document)
        if not self.transport.manager_status.get("configured"):
            return await self.async_rpc(
                "initialize", document=document, enabled=True, room=self.room or "dark"
            )
        return await self.async_rpc("import", document=document, revision=self.revision)

    async def async_export(self):
        if not self.document:
            raise HomeAssistantError("No saved profile collection")
        return deepcopy(self.document)

    async def async_export_backup(self, previous=0):
        if not self.saved["backup"]:
            raise HomeAssistantError("No complete TV backup has been received yet")
        if previous:
            if not 1 <= previous <= len(self.saved["previous"]):
                raise HomeAssistantError("That previous standard revision is not available")
            return deepcopy(self.saved["previous"][-previous])
        return deepcopy(self.saved["backup"])

    async def async_restore_backup(self, envelope):
        decode(envelope)
        return await self.async_rpc("restore_backup", backup=envelope, revision=self.revision)

    async def async_restore(self, scope="all", filters=None, categories=None):
        if filters is not None or categories is not None:
            if self.transport.manager_status.get("editor_api", 0) < 5:
                raise HomeAssistantError("Update LG Picture Bridge to use grouped restoration")
            fields = {"scope": scope, "revision": self.revision}
            if filters is not None:
                fields["filters"] = filters
            if categories is not None:
                fields["categories"] = categories
            return await self.async_rpc("restore_scope", **fields)
        return await self.async_rpc("restore", scope=scope)

    async def async_save_standard(self, scope="active"):
        return await self.async_rpc("save", scope=scope, revision=self.revision)

    async def async_enable(self, enabled):
        return await self.async_rpc("set_enabled", enabled=enabled)

    async def async_set_brightness(self, role, value):
        if role not in BRIGHTNESS_ROLES or not float(value).is_integer() or not 0 <= value <= 100:
            raise HomeAssistantError("SDR brightness must be an integer from 0 to 100")
        return await self.async_rpc(
            "set_brightness", values={role: int(value)}, revision=self.revision
        )

    async def async_reconcile(self):
        return await self.async_rpc("reconcile")

    async def async_preview(self):
        """Full cached profile state for both the preview action and editor."""
        if self.available:
            return await self.async_rpc("get")
        state = deepcopy(self.snapshot)
        if not state and self.document:
            state = {
                "document": deepcopy(self.document),
                "revision": 0,
                "enabled": False,
                "room": self.room or "dark",
                "preferences": {"movie_bright": 100, "movie_dark": 3, "game_sdr": 80},
                "overrides": deepcopy((self.saved.get("legacy") or {}).get("overrides", {})),
            }
        return {"state": state, "status": {"offline": True, "error": self.last_error}}

    async def async_stop(self):
        self._stopping = True
        if self.devices:
            self.devices.async_stop()
        if self._unsub:
            self._unsub()
        if self._sync_task:
            self._sync_task.cancel()
            await asyncio.gather(self._sync_task, return_exceptions=True)
        await asyncio.gather(*self._jobs, return_exceptions=True)
        await self.transport.async_stop()
