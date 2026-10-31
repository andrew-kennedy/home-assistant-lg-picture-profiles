from copy import deepcopy
from types import SimpleNamespace

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.lg_picture_profiles import _register_services
from custom_components.lg_picture_profiles.backup import decode
from custom_components.lg_picture_profiles.model import ProfileError, validate
from custom_components.lg_picture_profiles.select import ProfileSelection

from .conftest import document
from .test_manager import backup


def named_document():
    doc = document()
    doc.update(
        schema=2,
        brightness={"movie_sdr": 3, "game_sdr": 80},
        profiles=[
            {"id": "bright", "name": "Bright room", "brightness": {"movie_sdr": 100}},
            {"id": "dark", "name": "Dark room", "brightness": {"movie_sdr": 3}},
            {"id": "p_evening", "name": "Evening", "brightness": {"movie_sdr": 17}},
        ],
        automatic={"bright": "bright", "dark": "dark"},
    )
    return doc


def test_named_backup_contains_complete_catalog_and_selection():
    doc = named_document()
    state = decode(backup(document=doc, selection="p_evening", active_profile="p_evening"))
    assert state["document"] == doc
    assert state["selection"] == "p_evening"
    for patch in (
        {"automatic": {"bright": "absent", "dark": "dark"}},
        {"profiles": [{"id": "standard", "name": "Reserved"}]},
        {"profiles": [{"id": "p_a", "name": "Automatic"}]},
        {"brightness": {"movie_sdr": 101, "game_sdr": 80}},
    ):
        with pytest.raises(ProfileError):
            validate({**doc, **patch})
    with pytest.raises(ProfileError, match="selected"):
        decode(backup(document=doc, selection="absent", active_profile="dark"))


async def test_selector_discovers_renames_and_selects_by_stable_id(manager):
    manager.transport.manager_status.update(editor_api=6, profile_schema=2)
    await manager._accept_backup(
        backup(document=named_document(), selection="automatic", active_profile="dark")
    )
    entity = ProfileSelection(SimpleNamespace(entry_id="test", runtime_data=manager))
    assert entity.available
    assert entity.current_option == "Automatic"
    assert entity.options == ["Automatic", "Base standard", "Bright room", "Dark room", "Evening"]
    await entity.async_select_option("Evening")
    assert manager.transport.calls == [
        ("apply_profile", {"profile_id": "p_evening", "clear_adjustments": True})
    ]
    doc = named_document()
    doc["profiles"][-1]["name"] = "Late evening"
    await manager._accept_backup(
        backup(
            sequence=2, revision=2, document=doc, selection="p_evening", active_profile="p_evening"
        )
    )
    assert entity.current_option == "Late evening"
    assert "Evening" not in entity.options
    with pytest.raises(HomeAssistantError, match="refresh"):
        await entity.async_select_option("Evening")
    await entity.async_select_option("Late evening")
    assert manager.transport.calls[-1][1]["profile_id"] == "p_evening"
    assert not entity.should_poll
    manager.transport.available = False
    assert not entity.available
    assert "Late evening" in entity.options, "Catalog remains visible from the complete backup"


async def test_activation_backups_do_not_consume_standard_history(manager):
    doc = named_document()
    await manager._accept_backup(backup(document=doc, selection="automatic", active_profile="dark"))
    await manager._accept_backup(
        backup(sequence=2, document=doc, selection="p_evening", active_profile="p_evening")
    )
    assert manager.saved["previous"] == []
    assert decode(manager.saved["backup"])["selection"] == "p_evening"
    renamed = deepcopy(doc)
    renamed["profiles"][-1]["name"] = "Evening cinema"
    await manager._accept_backup(
        backup(
            sequence=3,
            revision=2,
            document=renamed,
            selection="p_evening",
            active_profile="p_evening",
        )
    )
    assert len(manager.saved["previous"]) == 1


async def test_schema_upgrade_only_requested_for_capable_legacy_collection(manager):
    await manager._accept_backup(backup())
    manager.transport.manager_status.update(configured=True, profile_schema=1, editor_api=5)
    await manager._sync_once()
    assert not manager.transport.calls
    manager.transport.manager_status["editor_api"] = 6
    await manager._sync_once()
    assert manager.transport.calls == [("upgrade_profiles", {"revision": 1})]
    manager.transport.manager_status["profile_schema"] = 2
    await manager._sync_once()
    assert len(manager.transport.calls) == 1


async def test_apply_profile_action_supports_stable_ids_and_preserving_adjustments(manager):
    manager.hass.data["lg_picture_profiles"] = {"test": manager}
    manager.transport.manager_status["editor_api"] = 6
    _register_services(manager.hass)
    await manager.hass.services.async_call(
        "lg_picture_profiles", "apply_profile", {"profile_id": "p_evening"}, blocking=True
    )
    await manager.hass.services.async_call(
        "lg_picture_profiles",
        "apply_profile",
        {"profile_id": "automatic", "clear_adjustments": False},
        blocking=True,
    )
    assert manager.transport.calls == [
        ("apply_profile", {"profile_id": "p_evening", "clear_adjustments": True}),
        ("apply_profile", {"profile_id": "automatic", "clear_adjustments": False}),
    ]
