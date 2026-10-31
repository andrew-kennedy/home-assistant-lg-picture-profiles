from types import SimpleNamespace

from custom_components.lg_picture_profiles.number import ProfileBrightness


def test_shared_brightness_is_available_only_with_linked_profiles():
    manager = SimpleNamespace(
        available=True,
        devices=None,
        snapshot={
            "document": {"banks": [{"brightness_role": "game_sdr"}]},
            "preferences": {"game_sdr": 80},
        },
    )
    entry = SimpleNamespace(runtime_data=manager, entry_id="test")
    game, movie = ProfileBrightness(entry, "game_sdr"), ProfileBrightness(entry, "movie_dark")
    assert game.available and game.native_value == 80
    assert not movie.available
    manager.snapshot["document"]["banks"][0].pop("brightness_role")
    assert not game.available
    manager.snapshot["document"]["banks"].append({"brightness_role": "game_sdr"})
    assert game.available
    manager.available = False
    assert not game.available
