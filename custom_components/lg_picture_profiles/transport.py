"""Use Home Assistant's existing MQTT connection and the bridge's correlated replies."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from uuid import uuid4

from homeassistant.components import mqtt
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError


class BridgeTransport:
    def __init__(
        self,
        hass: HomeAssistant,
        base: str,
        changed: Callable,
        settings: Callable,
        observations: Callable | None = None,
        backup: Callable | None = None,
    ) -> None:
        self.hass = hass
        self.base = base
        self.changed = changed
        self.settings = settings
        self.observations = observations
        self.backup = backup
        self.manager_status: dict = {}
        self.api_version = 1
        self.session: str | None = None
        self.online = False
        self.ready = False
        self._pending: dict[str, asyncio.Future] = {}
        self._unsub: list[Callable] = []

    async def async_start(self) -> None:
        for suffix, handler in [
            ("/profiles/status", self._status),
            ("/availability", self._availability),
            ("/settings/status", self._settings),
            ("/settings/observations", self._observations),
            ("/profiles/backup", self._backup),
        ]:
            self._unsub.append(
                await mqtt.async_subscribe(self.hass, self.base + suffix, handler, qos=0)
            )

    @callback
    def _fail_pending(self, reason: str) -> None:
        for future in self._pending.values():
            if not future.done():
                future.set_exception(HomeAssistantError(reason))

    @callback
    def _availability(self, message) -> None:
        online = message.payload == "online"
        if not online:
            self.ready = False
            self.session = None
            self._fail_pending("TV bridge went offline")
        self.online = online
        self.changed()

    @callback
    def _status(self, message) -> None:
        if message.retain:
            return
        try:
            status = json.loads(message.payload)
        except ValueError, TypeError:
            return
        if not isinstance(status, dict) or status.get("protocol") != 1:
            return
        session = status.get("session_id")
        if not isinstance(session, str) or not session:
            return
        if self.session and session != self.session:
            self._fail_pending("TV bridge reconnected; command outcome requires a fresh read")
        self.session = session
        self.api_version = status.get("api_version", self.api_version)
        if isinstance(status.get("manager"), dict):
            self.manager_status = status["manager"]
        self.ready = status.get("ready") is True
        for rid, result in (status.get("results") or {}).items():
            future = self._pending.get(rid)
            if future and not future.done():
                if result.get("ok") is True:
                    future.set_result(result.get("applied", {}))
                else:
                    future.set_exception(
                        HomeAssistantError(
                            f"{result.get('error', 'command_failed')}: {result.get('message', 'TV rejected command')}"
                        )
                    )
        self.changed()

    @callback
    def _settings(self, message) -> None:
        if message.retain:
            return
        try:
            status = json.loads(message.payload)
        except ValueError, TypeError:
            return
        if isinstance(status, dict):
            self.settings(status)

    @property
    def available(self) -> bool:
        return self.online and self.ready and self.session is not None

    @callback
    def _observations(self, message) -> None:
        if message.retain or not self.observations or len(message.payload) > 200000:
            return
        try:
            payload = json.loads(message.payload)
        except ValueError, TypeError:
            return
        if (
            isinstance(payload, dict)
            and payload.get("protocol") == 1
            and isinstance(payload.get("observations"), list)
            and len(payload["observations"]) <= 128
        ):
            self.observations(payload["observations"])

    @callback
    def _backup(self, message) -> None:
        if not self.backup or len(message.payload) > 1000000:
            return
        try:
            envelope = json.loads(message.payload)
        except ValueError, TypeError:
            return
        self.backup(envelope)

    async def async_publish_context(self, room: str) -> None:
        await mqtt.async_publish(
            self.hass,
            self.base + "/profiles/environment",
            json.dumps({"protocol": 1, "room": room}),
            qos=1,
            retain=True,
        )

    async def async_ack_backup(self, state: dict, checksum: str) -> None:
        await mqtt.async_publish(
            self.hass,
            self.base + "/profiles/backup/ack",
            json.dumps(
                {k: state[k] for k in ("owner_id", "instance_id", "sequence")}
                | {"sha256": checksum}
            ),
            qos=1,
            retain=False,
        )

    async def async_command(self, action: str, banks: list[dict] | None = None, **fields) -> dict:
        if not self.available:
            raise HomeAssistantError(
                "TV bridge unavailable; turn on the TV and check the bridge connection"
            )
        rid = "ha-profile-" + uuid4().hex
        session = self.session
        envelope = json.dumps(
            {
                "protocol": 1,
                "request_id": rid,
                "session_id": session,
                "expires_at": time.time() + 45,
                "policy": {
                    "action": action,
                    **({"banks": banks} if banks is not None else {}),
                    **fields,
                },
            },
            allow_nan=False,
        )
        future = self.hass.loop.create_future()
        self._pending[rid] = future
        try:
            for _ in range(3):
                if not self.available or self.session != session:
                    raise HomeAssistantError("TV bridge connection changed")
                # Identical retries are deduplicated by the bridge. Never retain commands.
                await mqtt.async_publish(
                    self.hass, self.base + "/profiles/command", envelope, qos=0, retain=False
                )
                try:
                    return await asyncio.wait_for(asyncio.shield(future), timeout=10)
                except TimeoutError:
                    continue
            raise HomeAssistantError("TV command timed out; pending restores are retained")
        finally:
            self._pending.pop(rid, None)
            if not future.done():
                future.cancel()

    async def async_stop(self) -> None:
        for unsub in self._unsub:
            unsub()
        self._unsub.clear()
        self._fail_pending("Picture profile integration unloaded")
