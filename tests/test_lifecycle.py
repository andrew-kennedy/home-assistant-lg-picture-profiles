from copy import deepcopy
from datetime import UTC, datetime

import pytest

from custom_components.lg_picture_profiles.model import ProfileError, validate

from .conftest import adjust, document


async def test_failed_load_does_not_replace_existing_store(manager):
    manager.store.saved = {"document": {"schema": 99}, "enabled": True}
    original = deepcopy(manager.store.saved)
    manager._loaded = False
    with pytest.raises(ProfileError):
        await manager.async_start()
    await manager.async_stop()
    assert manager.store.saved == original


async def test_reenable_does_not_replay_commands_from_disabled_period(manager):
    await manager.async_enable(False)
    timestamp = datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    manager.data["tracked_since"] = "2020-01-01T00:00:00.000Z"
    await manager.async_enable(True)
    assert manager.data["tracked_since"] >= timestamp
    await manager.async_user_results(
        {
            "old": {
                "ok": True,
                "completed_at": "2020-02-01T00:00:00.000Z",
                "applied": {
                    "kind": "user_setting",
                    "target": manager.document["banks"][0]["target"],
                    "key": "color",
                    "value": 70,
                },
            }
        }
    )
    assert manager.override_count == 0


async def test_incompatible_mode_cannot_be_saved_as_standard(manager):
    await adjust(manager, "dv_mapping", "pictureMode", "vivid")
    original = deepcopy(manager.document)
    with pytest.raises(ProfileError, match="signal range"):
        await manager.async_save_standard("all")
    assert manager.document == original
    assert manager.override_count == 1
    await manager.async_restore()
    assert manager.override_count == 0


def test_import_rejects_wrong_signal_family():
    doc = document()
    doc["banks"][2]["settings"]["pictureMode"] = "hdrGame"
    with pytest.raises(ProfileError, match="signal range"):
        validate(doc)
