import json
from copy import deepcopy
from unittest.mock import AsyncMock

from custom_components.lg_picture_profiles.preview import summarize

from .test_manager import backup


def snapshot(**changes):
    return {
        "state": json.loads(backup(**changes)["state_json"]),
        "status": {
            "power": "on",
            "context": {"input": "hdmi3", "range": "sdr", "mode": "filmMaker", "ready": True},
            "active_devices": ["Apple TV", "Shield"],
            "backup_sequence": 1,
            "backup_acknowledged": 1,
        },
    }


def test_summary_omits_document_and_recovery_internals_without_mutating_them():
    raw = snapshot()
    original = deepcopy(raw)
    result = summarize(raw, available=True, backup_saved=True)
    assert result["temporary_adjustments"] == []
    assert result["sdr_brightness"] == {"movie_bright": 100, "movie_dark": 3, "game_sdr": 80}
    assert result["active_picture"]["picture_mode"] == "filmMaker"
    assert result["backup"] == "confirmed"
    assert result["source"] == "bridge_snapshot"
    assert (
        not {"document", "state", "status", "owner_id", "instance_id", "recovery"} & result.keys()
    )
    assert "game_hdr" not in json.dumps(result)
    assert raw == original


def test_differences_use_room_variant_and_shared_brightness_preference():
    raw = snapshot(
        room="bright",
        preferences={"movie_bright": 77, "movie_dark": 7, "game_sdr": 62},
        overrides={"movie_sdr": {"backlight": "50", "peakBrightness": "off", "color": 50}},
    )
    result = summarize(raw, available=True, backup_saved=True)
    assert result["temporary_adjustments"] == [
        {
            "profile": "Shared SDR movie",
            "devices": ["Apple TV", "Shield"],
            "changes": {
                "backlight": {"standard": 77, "temporary": "50"},
                "peakBrightness": {"standard": "high", "temporary": "off"},
            },
        }
    ]


def test_inactive_adjustments_and_pending_restores_remain_visible():
    raw = snapshot(
        overrides={"game_hdr": {"gameSharpness": 7}},
        recovery={
            "dirty": {"game_hdr": ["gameSharpness"]},
            "restore": {"game_hdr": ["gameSharpness", "gameColorDepth"]},
            "reconstructing": True,
        },
    )
    result = summarize(raw, available=True, backup_saved=True)
    assert result["temporary_adjustments"][0]["changes"] == {
        "gameSharpness": {"standard": 0, "temporary": 7}
    }
    assert result["pending_restore"] == {"banks": 1, "settings": 2}
    assert result["reconstructing_adjustments"] is True


def test_offline_preview_labels_saved_snapshot_without_asserting_current_power():
    raw = snapshot(created_at="2026-10-27T16:00:00Z")
    result = summarize(raw, available=False, backup_saved=True)
    assert result["source"] == "saved_backup"
    assert result["snapshot_at"] == "2026-10-27T16:00:00Z"
    assert result["active_picture"] is None
    assert result["tv_power"] == "unknown"
    assert result["backup"] == "saved"


def test_live_standby_has_no_active_picture_and_keeps_errors():
    raw = snapshot()
    raw["status"].update(power="off", error="Native restore failed", backup_acknowledged=None)
    result = summarize(raw, available=True, backup_saved=True)
    assert result["tv_power"] == "off"
    assert result["active_picture"] is None
    assert result["error"] == "Native restore failed"
    assert result["backup"] == "pending"


async def test_preview_and_editor_use_different_views_of_the_same_snapshot(manager):
    await manager._accept_backup(backup(overrides={"game_hdr": {"gameSharpness": 7}}))
    manager.transport.available = False
    preview = await manager.async_preview()
    editor = await manager.async_snapshot()
    assert preview["temporary_adjustments"][0]["changes"]["gameSharpness"]["temporary"] == 7
    assert editor["state"]["document"] == manager.document
    assert editor["state"]["overrides"] == {"game_hdr": {"gameSharpness": 7}}
    assert editor["status"]["offline"] is True
    assert not manager.transport.calls


async def test_live_preview_only_reads_one_cached_bridge_snapshot(manager):
    manager.transport.async_command = AsyncMock(return_value=snapshot())
    result = await manager.async_preview()
    manager.transport.async_command.assert_awaited_once_with("get")
    assert result["temporary_adjustments"] == []
