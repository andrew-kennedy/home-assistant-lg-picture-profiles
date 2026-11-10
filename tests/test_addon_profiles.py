from types import SimpleNamespace

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.lg_picture_profiles import _register_services
from custom_components.lg_picture_profiles.backup import decode
from custom_components.lg_picture_profiles.model import ProfileError, addon_groups, validate
from custom_components.lg_picture_profiles.select import ADDON_OFF, AddonSelection, ProfileSelection

from .test_manager import backup
from .test_named_profiles import named_document


def addon_document():
    doc = named_document()
    doc["profiles"] += [
        {"id": "p_dtm", "name": "DTM fix", "brightness": {}, "group": "Switch 2 HDR"},
        {"id": "p_dark", "name": "Dark fix", "group": "Switch 2 HDR"},
    ]
    return doc


def test_addon_profiles_validate_and_group():
    doc = addon_document()
    assert validate(doc) == doc
    assert [p["id"] for p in addon_groups(doc)["Switch 2 HDR"]] == ["p_dtm", "p_dark"]
    state = decode(backup(document=doc, selection="automatic", active_profile="dark", addons={"Switch 2 HDR": "p_dtm"}))
    assert state["addons"] == {"Switch 2 HDR": "p_dtm"}
    for profile in (
        {"id": "p_x", "name": "X", "group": " padded "},
        {"id": "p_x", "name": "X", "group": ""},
        {"id": "p_x", "name": "X", "group": "G", "brightness": {"movie_sdr": 5}},
    ):
        with pytest.raises(ProfileError):
            validate({**doc, "profiles": doc["profiles"] + [profile]})
    with pytest.raises(ProfileError, match="automatic"):
        validate({**doc, "automatic": {"bright": "p_dtm", "dark": "dark"}})
    with pytest.raises(ProfileError, match="add-on"):
        decode(backup(document=doc, selection="automatic", active_profile="dark", addons=[]))


async def test_addon_select_follows_group_and_applies(manager):
    manager.transport.manager_status.update(editor_api=10, profile_schema=2)
    await manager._accept_backup(backup(document=addon_document(), selection="automatic", active_profile="dark"))
    entry = SimpleNamespace(entry_id="test", runtime_data=manager)
    main = ProfileSelection(entry)
    assert "DTM fix" not in main.options, "Add-ons are not main profiles"
    entity = AddonSelection(entry, "Switch 2 HDR")
    assert entity.name == "Switch 2 HDR add-on"
    assert entity.unique_id == "test_addon_switch_2_hdr"
    assert entity.available
    assert entity.options == [ADDON_OFF, "DTM fix", "Dark fix"]
    assert entity.current_option == ADDON_OFF
    await entity.async_select_option("DTM fix")
    assert manager.transport.calls[-1] == (
        "apply_addon",
        {"group": "Switch 2 HDR", "profile_id": "p_dtm", "clear_adjustments": True},
    )
    manager.transport.manager_status["addons"] = {"Switch 2 HDR": "p_dtm"}
    assert entity.current_option == "DTM fix"
    assert entity.extra_state_attributes == {"group": "Switch 2 HDR", "profile_id": "p_dtm"}
    await entity.async_select_option(ADDON_OFF)
    assert manager.transport.calls[-1][1]["profile_id"] is None
    with pytest.raises(HomeAssistantError, match="refresh"):
        await entity.async_select_option("Missing")
    manager.transport.manager_status["editor_api"] = 9
    assert not entity.available
    with pytest.raises(HomeAssistantError, match="0.30.0"):
        await manager.async_apply_addon("Switch 2 HDR", "p_dtm")


async def test_apply_addon_action(manager):
    manager.hass.data["lg_picture_profiles"] = {"test": manager}
    manager.transport.manager_status["editor_api"] = 10
    _register_services(manager.hass)
    await manager.hass.services.async_call(
        "lg_picture_profiles",
        "apply_addon",
        {"group": "Switch 2 HDR", "profile_id": "none", "clear_adjustments": False},
        blocking=True,
    )
    assert manager.transport.calls == [
        (
            "apply_addon",
            {"group": "Switch 2 HDR", "profile_id": None, "clear_adjustments": False},
        )
    ]
