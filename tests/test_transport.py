import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.lg_picture_profiles import transport as module
from custom_components.lg_picture_profiles.transport import BridgeTransport


def message(value, retain=False):
    return SimpleNamespace(payload=json.dumps(value), retain=retain)


@pytest.fixture
async def transport():
    result = BridgeTransport(
        SimpleNamespace(loop=asyncio.get_running_loop()), "lg/test", lambda: None, lambda _: None
    )
    result._availability(SimpleNamespace(payload="online"))
    result._status(message({"protocol": 1, "session_id": "session-a", "ready": True}))
    return result


async def test_retained_status_cannot_enable_bridge_or_complete_command(transport, monkeypatch):
    publish = AsyncMock()
    monkeypatch.setattr(module.mqtt, "async_publish", publish)
    task = asyncio.create_task(transport.async_command("read", []))
    await asyncio.sleep(0)
    envelope = json.loads(publish.call_args.args[2])
    rid = envelope["request_id"]
    reply = {
        "protocol": 1,
        "session_id": "session-a",
        "ready": True,
        "results": {rid: {"ok": True, "applied": {"banks": []}}},
    }
    transport._status(message(reply, retain=True))
    assert not transport._pending[rid].done()
    transport._status(message(reply))
    assert await task == {"banks": []}
    assert not transport._pending
    assert publish.call_args.kwargs["retain"] is False


async def test_session_change_rejects_old_outcome(transport, monkeypatch):
    publish = AsyncMock()
    monkeypatch.setattr(module.mqtt, "async_publish", publish)
    task = asyncio.create_task(transport.async_command("apply", []))
    await asyncio.sleep(0)
    rid = json.loads(publish.call_args.args[2])["request_id"]
    transport._status(
        message(
            {
                "protocol": 1,
                "session_id": "session-b",
                "ready": True,
                "results": {rid: {"ok": True, "applied": {"banks": []}}},
            }
        )
    )
    with pytest.raises(HomeAssistantError, match="reconnected"):
        await task


async def test_offline_and_unload_release_pending_commands(transport, monkeypatch):
    monkeypatch.setattr(module.mqtt, "async_publish", AsyncMock())
    task = asyncio.create_task(transport.async_command("read", []))
    await asyncio.sleep(0)
    transport._availability(SimpleNamespace(payload="offline"))
    with pytest.raises(HomeAssistantError, match="offline"):
        await task
    assert not transport.available
    assert transport.session is None
    await transport.async_stop()


async def test_retries_are_identical_and_cannot_repeat_a_write(transport, monkeypatch):
    publish = AsyncMock()
    monkeypatch.setattr(module.mqtt, "async_publish", publish)
    real_wait = asyncio.wait_for
    attempts = 0

    async def wait(future, timeout):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            future.cancel()  # Only the shield is cancelled, not the command's future.
            raise TimeoutError
        rid = next(iter(transport._pending))
        transport._status(
            message(
                {
                    "protocol": 1,
                    "session_id": "session-a",
                    "ready": True,
                    "results": {rid: {"ok": True, "applied": {"changed": 1}}},
                }
            )
        )
        return await real_wait(future, timeout)

    monkeypatch.setattr(module.asyncio, "wait_for", wait)
    assert await transport.async_command("apply", []) == {"changed": 1}
    payloads = [call.args[2] for call in publish.call_args_list]
    assert len(payloads) == 3 and len(set(payloads)) == 1


async def test_exhausted_timeout_leaves_no_pending_future(transport, monkeypatch):
    monkeypatch.setattr(module.mqtt, "async_publish", AsyncMock())

    async def timeout(future, timeout):
        future.cancel()
        raise TimeoutError

    monkeypatch.setattr(module.asyncio, "wait_for", timeout)
    with pytest.raises(HomeAssistantError, match="timed out"):
        await transport.async_command("apply", [])
    assert not transport._pending


async def test_only_bounded_live_observations_are_delivered(transport):
    received = []
    transport.observations = received.append
    payload = {"protocol": 1, "observations": [{"key": "color", "value": 55}]}
    transport._observations(message(payload, retain=True))
    for invalid in [
        None,
        [],
        {},
        {**payload, "protocol": 2},
        {**payload, "observations": [{}] * 129},
    ]:
        transport._observations(message(invalid))
    transport._observations(SimpleNamespace(payload="bad json", retain=False))
    assert not received
    transport._observations(message(payload))
    assert received == [payload["observations"]]
