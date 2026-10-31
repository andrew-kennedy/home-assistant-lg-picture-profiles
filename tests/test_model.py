from copy import deepcopy

import pytest

from custom_components.lg_picture_profiles.model import (
    ProfileError,
    desired,
    equal,
    is_active,
    validate,
)

from .conftest import document


def test_round_trip_and_shared_device_binding():
    doc = document()
    assert validate(doc) == doc
    assert doc["banks"][0]["devices"] == ["apple", "shield"]
    assert desired(doc["banks"][0], "bright", {}, {"backlight": 25})["backlight"] == 25
    assert equal("50", 50)
    assert not equal(True, 1)


def test_expanded_native_catalog_and_signal_validation():
    doc = document()
    presets = ["game", "filmMaker", "normal", "vivid", "cinema", "expert1", "expert2",
               "hdrGame", "hdrFilmMaker", "hdrCinemaBright", "hdrStandard", "hdrVivid",
               "dolbyHdrGame", "dolbyHdrCinema", "dolbyHdrCinemaBright", "dolbyHdrStandard"]
    doc["banks"] = [
        {"id": f"native_{port}_{pc}_{mode}", "name": mode, "devices": [],
         "target": {"category": "picture", "dimension": {
             "input": f"hdmi{port}" + ("_pc" if pc else ""), "pictureMode": mode}},
         "settings": {"backlight": 50}}
        for port in range(1, 5) for pc in (False, True) for mode in presets
    ]
    assert len(doc["banks"]) == 128
    assert validate(doc) == doc
    mapping = {"id": "mapping", "name": "HDR mapping", "devices": [],
               "target": {"category": "picture", "dimension": {"input": "hdmi3", "dynamicRange": "hdr"}},
               "settings": {"pictureMode": "hdrCinemaBright"}}
    doc["banks"].append(mapping)
    assert validate(doc) == doc
    mapping["settings"]["pictureMode"] = "expert1"
    with pytest.raises(ProfileError, match="signal range"):
        validate(doc)


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d["banks"].append({**deepcopy(d["banks"][0]), "id": "duplicate"}),
        lambda d: d["banks"][0]["settings"].update({"factoryReset": True}),
        lambda d: d["banks"][0]["target"]["dimension"].update({"input": "hdmi5"}),
        lambda d: d["banks"][0]["target"].update({"app_id": "com.webos.app.hdmi4"}),
        lambda d: d["banks"][0]["variants"]["bright"].update({"new_key": 3}),
        lambda d: d["banks"][0].update({"id": "__proto__"}),
        lambda d: d["banks"][1]["target"]["dimension"].update({"gameInput": "hdmi3_pc"}),
    ],
)
def test_invalid_or_ambiguous_profiles_rejected(change):
    doc = document()
    change(doc)
    with pytest.raises(ProfileError):
        validate(doc)


def test_exact_mode_and_range_identity():
    bank = document()["banks"][1]
    assert is_active(bank, {"input": "hdmi3", "mode": "hdrGame", "range": "hdrALLM"})
    assert not is_active(bank, {"input": "hdmi3", "mode": "game", "range": "sdrALLM"})
    assert not is_active(bank, {"input": "hdmi4", "mode": "hdrGame", "range": "hdrALLM"})


def test_motion_controls_use_their_native_database_scope():
    doc = document()
    bank = doc["banks"][0]
    bank["settings"].update({"realCinema": "on", "truMotionJudder": 0, "truMotionBlur": 0})
    assert validate(doc) == doc
    motion = deepcopy(bank)
    motion.update({"id": "motion", "settings": {"truMotionMode": "off"}})
    motion.pop("variants", None)
    motion.pop("brightness_role", None)
    motion["target"]["app_id"] = "com.webos.app.hdmi3"
    doc["banks"].append(motion)
    assert validate(doc) == doc
    motion["settings"]["truMotionJudder"] = 0
    with pytest.raises(ProfileError):
        validate(doc)
