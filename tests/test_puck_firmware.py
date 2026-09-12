from pathlib import Path

import yaml


def test_stop_button_has_a_defined_unpressed_level():
    path = Path(__file__).resolve().parents[1] / "firmware/respeaker-lite/respeaker-lite.yaml"
    config = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
    button = next(item for item in config["binary_sensor"] if item["id"] == "user_button")
    assert button["pin"]["inverted"] == "true"
    assert button["pin"].get("mode", {}).get("pullup") == "true"
    assert button["on_press"] == [{"media_player.stop": "puck_media_player"}]
