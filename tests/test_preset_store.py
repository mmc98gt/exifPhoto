import json
import tempfile
import unittest
from pathlib import Path

from app.overlay_config import OverlayStyle, WatermarkConfig, get_default_user_presets
from app.preset_store import load_preset_store, save_preset_store


class PresetStoreTests(unittest.TestCase):
    def test_returns_defaults_when_file_does_not_exist(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "presets.json"

            store = load_preset_store(path)

            self.assertEqual(len(store.user_presets), 3)
            self.assertEqual(store.last_selected_preset_id, "builtin_classic")
            self.assertIsNone(store.warning_message)

    def test_persists_user_presets_and_last_selected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "presets.json"
            user_presets = get_default_user_presets()
            user_presets[0] = user_presets[0].__class__(
                preset_id=user_presets[0].preset_id,
                name=user_presets[0].name,
                built_in=False,
                fields=user_presets[0].fields,
                style=OverlayStyle.from_dict({**user_presets[0].style.to_dict(), "text_color": "#123456"}),
                watermark=WatermarkConfig.from_dict({**user_presets[0].watermark.to_dict(), "image_path": "C:/logos/logo.png"}),
            )

            save_preset_store(user_presets, "user_1", "C:/logos/logo.png", path)
            store = load_preset_store(path)

            self.assertEqual(store.last_selected_preset_id, "user_1")
            self.assertEqual(store.last_watermark_image_path, "C:/logos/logo.png")
            self.assertEqual(store.user_presets[0].style.text_color, "#123456")
            self.assertEqual(store.user_presets[0].preset_id, "user_1")
            self.assertEqual(store.user_presets[0].watermark.image_path, "")

    def test_falls_back_when_json_is_corrupt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "presets.json"
            path.write_text("{broken", encoding="utf-8")

            store = load_preset_store(path)

            self.assertEqual(len(store.user_presets), 3)
            self.assertIsNotNone(store.warning_message)

    def test_writes_expected_json_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "presets.json"
            save_preset_store(get_default_user_presets(), "builtin_classic", "C:/logos/logo.png", path)

            payload = json.loads(path.read_text(encoding="utf-8"))

            self.assertEqual(payload["version"], 2)
            self.assertEqual(len(payload["user_presets"]), 3)
            self.assertEqual(payload["last_selected_preset_id"], "builtin_classic")
            self.assertEqual(payload["last_watermark_image_path"], "C:/logos/logo.png")
            self.assertEqual(payload["user_presets"][0]["watermark"]["image_path"], "")

    def test_loads_legacy_watermark_path_from_user_presets_when_separate_field_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "presets.json"
            legacy_presets = get_default_user_presets()
            legacy_presets[1] = legacy_presets[1].__class__(
                preset_id=legacy_presets[1].preset_id,
                name=legacy_presets[1].name,
                built_in=False,
                fields=legacy_presets[1].fields,
                style=legacy_presets[1].style,
                watermark=WatermarkConfig.from_dict({**legacy_presets[1].watermark.to_dict(), "image_path": "D:/wm/logo.png"}),
            )
            payload = {
                "version": 1,
                "user_presets": [preset.to_dict() for preset in legacy_presets],
                "last_selected_preset_id": "user_2",
            }
            path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")

            store = load_preset_store(path)

            self.assertEqual(store.last_watermark_image_path, "D:/wm/logo.png")


if __name__ == "__main__":
    unittest.main()
