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
