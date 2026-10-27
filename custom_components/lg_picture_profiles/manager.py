"""Profile ownership and durable temporary adjustments. No polling or automatic learning."""

from __future__ import annotations

import asyncio
import logging
from copy import deepcopy
from datetime import UTC, datetime

from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store

from .const import (
    CONF_BRIDGE_TOPIC,
    CONF_BRIGHT_HELPER,
    CONF_DARK_HELPER,
    CONF_GAME_HELPER,
    CONF_SUN_ENTITY,
    CONF_TV_ENTITY,
    DOMAIN,
    STORAGE_VERSION,
)
from .model import (
    apply_standard_value,
    desired,
    environment_keys,
    equal,
    find_bank,
    is_active,
    validate,
)
from .transport import BridgeTransport

_LOGGER = logging.getLogger(__name__)


class ProfileManager:
    def __init__(self, hass: HomeAssistant, entry, *, transport=None, store=None) -> None:
        self.hass = hass
        self.entry = entry
        self.config = {**entry.data, **entry.options}
        self.store = store or Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}", atomic_writes=True
        )
        self.data = {
            "document": None,
            "overrides": {},
            "enabled": False,
            "pending_restore": False,
            "last_power": None,
            "seen_requests": [],
            "tracked_since": None,
            "environment": None,
        }
        self.context: dict = {}
        self.last_error: str | None = None
        self.last_changed_count = 0
        self.applying = False
        self._listeners = set()
        self._lock = asyncio.Lock()
        self._unsub = None
        self._sync_task = None
        self._sync_again = False
        self._last_transport_available = False
        self._override_versions: dict[tuple[str, str], str] = {}
        self._jobs: set[asyncio.Task] = set()
        self._stopping = False
        self._loaded = False
        self.transport = transport or BridgeTransport(
            hass, self.config[CONF_BRIDGE_TOPIC], self._bridge_changed, self._settings_status
        )

    @property
    def document(self) -> dict | None:
        return self.data["document"]

    @property
    def override_count(self) -> int:
        return sum(len(values) for values in self.data["overrides"].values())

    @property
    def room(self) -> str | None:
        state = self.hass.states.get(self.config.get(CONF_SUN_ENTITY, "sun.sun"))
        return {"above_horizon": "bright", "below_horizon": "dark"}.get(
            state.state if state else None
        )

    @property
    def tv_on(self) -> bool:
        state = self.hass.states.get(self.config[CONF_TV_ENTITY])
        return bool(state and state.state == "on")

    @property
    def available(self) -> bool:
        return self.tv_on and self.transport.available

    @property
    def state(self) -> str:
        if not self.document:
            return "unconfigured"
        if not self.data["enabled"]:
            return "disabled"
        if self.last_error:
            return "error"
        if self.data["pending_restore"]:
            return "pending_restore"
        if not self.available:
            return "offline"
        return "applying" if self.applying else "ready"

    @property
    def active_names(self) -> list[str]:
        if not self.document:
            return []
        return list(
            dict.fromkeys(
                self.document["devices"][d]
                for b in self.document["banks"]
                if is_active(b, self.context)
                for d in b.get("devices", [])
            )
        )

    @callback
    def async_add_listener(self, listener):
        self._listeners.add(listener)
        return lambda: self._listeners.discard(listener)

    @callback
    def notify(self) -> None:
        for listener in tuple(self._listeners):
            listener()

    def lights(self) -> dict:
        result = {}
        for role, key in [
            ("movie_sdr", CONF_BRIGHT_HELPER if self.room == "bright" else CONF_DARK_HELPER),
            ("game_sdr", CONF_GAME_HELPER),
        ]:
            entity = self.config.get(key)
            if not entity:
                continue
            state = self.hass.states.get(entity)
            try:
                value = float(state.state) if state else -1
            except ValueError:
                value = -1
            if not 0 <= value <= 100:
                raise HomeAssistantError(
                    f"Brightness helper {entity} is unavailable or outside 0–100"
                )
            result[role] = int(value) if value.is_integer() else value
        return result

    async def persist(self) -> None:
        await self.store.async_save(deepcopy(self.data))
        self.notify()

    async def async_start(self) -> None:
        saved = await self.store.async_load()
        if saved:
            if saved.get("document"):
                saved["document"] = validate(saved["document"])
            self.data.update(saved)
        self._loaded = True
        entity_ids = [self.config[CONF_TV_ENTITY], self.config.get(CONF_SUN_ENTITY, "sun.sun")]
        entity_ids.extend(
            self.config[k]
            for k in (CONF_BRIGHT_HELPER, CONF_DARK_HELPER, CONF_GAME_HELPER)
            if self.config.get(k)
        )
        self._unsub = async_track_state_change_event(self.hass, entity_ids, self._state_changed)
        await self.transport.async_start()
        current = self.hass.states.get(self.config[CONF_TV_ENTITY])
        if current and current.state == "off" and self.override_count:
            self.data["pending_restore"] = True
            await self.persist()
        self._schedule_sync()

    @callback
    def _spawn(self, coro) -> None:
        if self._stopping:
            coro.close()
            return
        task = self.hass.async_create_task(coro)
        self._jobs.add(task)
        task.add_done_callback(self._jobs.discard)

    @callback
    def _state_changed(self, event) -> None:
        self._spawn(self._handle_state(event))

    async def _handle_state(self, event) -> None:
        state = event.data.get("new_state")
        if (
            state
            and state.entity_id == self.config[CONF_TV_ENTITY]
            and state.state in ("on", "off")
        ):
            async with self._lock:
                if state.state == "off" and self.override_count:
                    self.data["pending_restore"] = True
                self.data["last_power"] = state.state
                await self.persist()
        self._schedule_sync()

    @callback
    def _bridge_changed(self) -> None:
        self.notify()
        available = self.transport.available
        if available and not self._last_transport_available:
            self._schedule_sync()
        self._last_transport_available = available

    @callback
    def _schedule_sync(self) -> None:
        if self._stopping:
            return
        if self._sync_task and not self._sync_task.done():
            self._sync_again = True
            return
        self._sync_task = self.hass.async_create_task(self._background_sync())

    async def _background_sync(self) -> None:
        while True:
            self._sync_again = False
            await asyncio.sleep(0.3)
            try:
                await self.async_reconcile()
            except HomeAssistantError as error:
                self.last_error = str(error)
                self.notify()
                _LOGGER.warning("Picture environment remains pending: %s", error)
            if not self._sync_again:
                break

    @callback
    def _settings_status(self, status) -> None:
        context = status.get("context")
        if isinstance(context, dict):
            if context.get("input") == self.context.get("input") and "gameGenre" in self.context:
                context = {"gameGenre": self.context["gameGenre"], **context}
            self.context = context
        self._spawn(self.async_user_results(status.get("results") or {}))
        self.notify()

    async def async_user_results(self, results: dict) -> None:
        """Only confirmed user commands create temporary overrides; telemetry never learns standards."""
        # Process in-memory changes before awaiting persistence. Holding the
        # operation lock here could let a restore overwrite a just-acknowledged
        # user command while its tracking event waited for that same lock.
        if not self.document or not self.data["enabled"] or not self.room:
            return
        changed = False
        since = self.data.get("tracked_since") or "9999"
        for rid, result in sorted(
            results.items(), key=lambda item: item[1].get("completed_at", "")
        ):
            if rid in self.data["seen_requests"] or result.get("completed_at", "") < since:
                continue
            self.data["seen_requests"].append(rid)
            self.data["seen_requests"] = self.data["seen_requests"][-64:]
            changed = True
            applied = result.get("applied") or {}
            if not result.get("ok") or applied.get("kind") != "user_setting":
                continue
            bank = find_bank(self.document, applied.get("target", {}), applied.get("key", ""))
            if not bank:
                continue
            key, value = applied["key"], applied["value"]
            self._override_versions[(bank["id"], key)] = rid
            baseline = desired(bank, self.room, self.lights())[key]
            overrides = self.data["overrides"].setdefault(bank["id"], {})
            if equal(value, baseline):
                overrides.pop(key, None)
            else:
                overrides[key] = value
            if not overrides:
                self.data["overrides"].pop(bank["id"], None)
            if bank["target"]["category"] == "other" and key == "gameGenre":
                self.context["gameGenre"] = value
        if changed:
            if not self.tv_on and self.override_count:
                self.data["pending_restore"] = True
            await self.persist()

    def _clear_unchanged_overrides(self, selections, versions) -> None:
        for bank, keys in selections:
            current = self.data["overrides"].get(bank["id"], {})
            for key in keys:
                identity = (bank["id"], key)
                if self._override_versions.get(identity) == versions.get(identity):
                    current.pop(key, None)
            if not current:
                self.data["overrides"].pop(bank["id"], None)

    async def async_import(self, document: dict) -> dict:
        document = validate(document)
        async with self._lock:
            if self.override_count:
                raise HomeAssistantError(
                    "Restore or save temporary adjustments before replacing standards"
                )
            self.data["document"] = document
            self._loaded = True
            self.data["environment"] = None
            self.data["tracked_since"] = (
                datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
            )
            self.last_error = None
            await self.persist()
        self._schedule_sync()
        return {"banks": len(document["banks"]), "devices": len(document["devices"])}

    async def async_enable(self, enabled: bool) -> None:
        async with self._lock:
            if enabled and not self.document:
                raise HomeAssistantError(
                    "Import your verified standards before enabling management"
                )
            if enabled and (not self.data["enabled"] or not self.data["tracked_since"]):
                self.data["tracked_since"] = (
                    datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
                )
            self.data["enabled"] = enabled
            await self.persist()
        self._schedule_sync()

    async def read_banks(self, selections: list[tuple[dict, set[str]]]) -> dict:
        snapshots = {}
        for start in range(0, len(selections), 4):
            group = selections[start : start + 4]
            request = [
                {"id": b["id"], "target": b["target"], "keys": sorted(keys)} for b, keys in group
            ]
            reply = await self.transport.async_command("read", request)
            actual = {row["id"]: row for row in reply.get("banks", [])}
            for bank, keys in group:
                row = actual.get(bank["id"])
                if (
                    not row
                    or row.get("target") != bank["target"]
                    or not keys <= row.get("settings", {}).keys()
                ):
                    raise HomeAssistantError(
                        "Bridge returned an incomplete or differently scoped snapshot"
                    )
                snapshots[bank["id"]] = row["settings"]
        return snapshots

    async def _apply(self, selections: list[tuple[dict, set[str]]], *, keep_overrides: bool) -> int:
        if not self.available or not self.room:
            raise HomeAssistantError("TV and sun state must be available")
        selections = [(b, keys) for b, keys in selections if keys]
        # Stored presets before mappings, so switching Dolby Vision room mode sees a ready preset.
        selections.sort(key=lambda item: "pictureMode" in item[1])
        if not selections:
            return 0
        self.applying = True
        self.notify()
        try:
            snapshots = await self.read_banks(selections)
            operations = []
            for bank, keys in selections:
                expected = snapshots[bank["id"]]
                values = desired(bank, self.room, self.lights())
                if keep_overrides:
                    keys = keys - self.data["overrides"].get(bank["id"], {}).keys()
                delta = {k: values[k] for k in keys if not equal(values[k], expected[k])}
                if delta:
                    operations.append(
                        {
                            "id": bank["id"],
                            "target": bank["target"],
                            "settings": delta,
                            "expected": {k: expected[k] for k in delta},
                        }
                    )
            changed = 0
            for start in range(0, len(operations), 4):
                group = operations[start : start + 4]
                reply = await self.transport.async_command("apply", group)
                result = {b["id"]: b for b in reply.get("banks", [])}
                for operation in group:
                    actual = result.get(operation["id"])
                    if (
                        not actual
                        or actual.get("target") != operation["target"]
                        or any(
                            not equal(actual.get("settings", {}).get(k), v)
                            for k, v in operation["settings"].items()
                        )
                    ):
                        raise HomeAssistantError(
                            "Bridge did not confirm the requested saved settings"
                        )
                    changed += len(actual.get("changed", []))
            self.last_changed_count = changed
            self.last_error = None
            return changed
        finally:
            self.applying = False
            self.notify()

    async def async_reconcile(self) -> dict:
        async with self._lock:
            if not self.document or not self.data["enabled"] or not self.available or not self.room:
                return {"deferred": True}
            changed = 0
            if self.data["pending_restore"]:
                selected = [
                    (b, set(self.data["overrides"].get(b["id"], {})))
                    for b in self.document["banks"]
                ]
                versions = self._override_versions.copy()
                changed += await self._apply(selected, keep_overrides=False)
                self._clear_unchanged_overrides(selected, versions)
                self.data["pending_restore"] = False
                await self.persist()
            environment = {"room": self.room, "lights": self.lights()}
            if self.data["environment"] != environment:
                selected = [(b, environment_keys(b)) for b in self.document["banks"]]
                changed += await self._apply(selected, keep_overrides=True)
                self.data["environment"] = environment
                await self.persist()
            return {"changed_settings": changed}

    async def async_restore(self, scope: str = "all") -> dict:
        async with self._lock:
            if not self.document:
                raise HomeAssistantError("No standard profiles have been imported")
            selected = [
                (b, set(b["settings"]))
                for b in self.document["banks"]
                if scope == "all" or is_active(b, self.context)
            ]
            if scope == "active" and (not self.available or not self.context.get("ready")):
                raise HomeAssistantError("An active context is required")
            if not self.available:
                # Persist an explicit full restore request across restarts.
                for bank, keys in selected:
                    self.data["overrides"].setdefault(bank["id"], {}).update(
                        {k: None for k in keys}
                    )
                self.data["pending_restore"] = True
                await self.persist()
                return {"deferred": True}
            versions = self._override_versions.copy()
            changed = await self._apply(selected, keep_overrides=False)
            self._clear_unchanged_overrides(selected, versions)
            self.data["pending_restore"] = bool(
                self.data["overrides"] and self.data["pending_restore"]
            )
            await self.persist()
            return {"changed_settings": changed}

    async def async_save_standard(self, scope: str = "active") -> dict:
        async with self._lock:
            if (
                not self.document
                or not self.available
                or not self.room
                or not self.context.get("ready")
            ):
                raise HomeAssistantError(
                    "TV must be available with a known active picture and room"
                )
            selected = [
                (b, set(self.data["overrides"].get(b["id"], {})))
                for b in self.document["banks"]
                if scope == "all" or is_active(b, self.context)
            ]
            selected = [(b, keys) for b, keys in selected if keys]
            versions = self._override_versions.copy()
            snapshots = await self.read_banks(selected)
            updated = deepcopy(self.document)
            updated_banks = {b["id"]: b for b in updated["banks"]}
            helper_updates = {}
            for bank, keys in selected:
                for key in keys:
                    value = snapshots[bank["id"]][key]
                    apply_standard_value(updated_banks[bank["id"]], self.room, key, value)
                    if key == "backlight" and bank.get("brightness_role"):
                        helper_key = (
                            CONF_GAME_HELPER
                            if bank["brightness_role"] == "game_sdr"
                            else CONF_BRIGHT_HELPER
                            if self.room == "bright"
                            else CONF_DARK_HELPER
                        )
                        if entity := self.config.get(helper_key):
                            if entity in helper_updates and not equal(
                                helper_updates[entity], value
                            ):
                                raise HomeAssistantError(
                                    "Selected brightness overrides disagree for a shared helper; save one context at a time"
                                )
                            helper_updates[entity] = value
            validate(updated)
            for entity, value in helper_updates.items():
                await self.hass.services.async_call(
                    "input_number",
                    "set_value",
                    {"entity_id": entity, "value": float(value)},
                    blocking=True,
                )
            self.data["document"] = updated
            self._clear_unchanged_overrides(selected, versions)
            if not self.override_count:
                self.data["pending_restore"] = False
            await self.persist()
            return {"saved_settings": sum(len(keys) for _, keys in selected)}

    async def async_export(self) -> dict:
        if not self.document:
            raise HomeAssistantError("No standard profiles have been imported")
        return deepcopy(self.document)

    async def async_preview(self) -> dict:
        async with self._lock:
            if not self.document or not self.available or not self.room:
                raise HomeAssistantError("Standards, TV and sun state must be available")
            selected = [(b, set(b["settings"])) for b in self.document["banks"]]
            snapshots = await self.read_banks(selected)
            differences = []
            for bank, _ in selected:
                values = desired(bank, self.room, self.lights())
                changes = {
                    k: {
                        "actual": snapshots[bank["id"]][k],
                        "standard": v,
                        "temporary": k in self.data["overrides"].get(bank["id"], {}),
                    }
                    for k, v in values.items()
                    if not equal(snapshots[bank["id"]][k], v)
                }
                if changes:
                    differences.append(
                        {"bank": bank["id"], "name": bank["name"], "settings": changes}
                    )
            return {"room": self.room, "differences": differences}

    async def async_stop(self) -> None:
        self._stopping = True
        if self._unsub:
            self._unsub()
        if self._sync_task and not self._sync_task.done():
            self._sync_task.cancel()
            await asyncio.gather(self._sync_task, return_exceptions=True)
        for task in self._jobs:
            task.cancel()
        await asyncio.gather(*self._jobs, return_exceptions=True)
        await self.transport.async_stop()
        if self._loaded:
            await self.persist()
