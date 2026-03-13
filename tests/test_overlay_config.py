import unittest

from app.overlay_config import (
    OverlayFieldConfig,
    OverlayPreset,
    OverlayStyle,
    ShadowStyle,
    StrokeStyle,
    WatermarkConfig,
    get_builtin_presets,
    get_default_user_presets,
)


class OverlayConfigTests(unittest.TestCase):
    def test_round_trips_overlay_preset(self) -> None:
        preset = OverlayPreset(
            preset_id="custom",
            name="Custom",
            built_in=False,
            mode="watermark",
            fields=OverlayFieldConfig(show_iso=False, separator=" / "),
            style=OverlayStyle(
                font_family="DejaVu Sans",
                font_size_mode="manual",
                font_size=48,
                text_color="#abcdef",
                vertical_offset=-22,
                shadow=ShadowStyle(enabled=True, color="#123456", opacity=45, offset_x=2, offset_y=3),
                stroke=StrokeStyle(enabled=True, color="#654321", opacity=80, width=4),
            ),
            watermark=WatermarkConfig(
                source_type="image",
                text="Logo",
                image_path="C:/tmp/logo.png",
                show_detected_number=True,
                opacity=63,
                scale_percent=22,
                position="top_right",
                margin_ratio=0.08,
                vertical_offset=37,
            ),
        )

        restored = OverlayPreset.from_dict(preset.to_dict())

        self.assertEqual(restored, preset.normalized())

    def test_normalizes_invalid_style_values(self) -> None:
        style = OverlayStyle(
            font_family="Unknown",
            font_size_mode="broken",
            font_size=999,
            text_color="bad",
            bottom_padding_ratio=999,
            side_padding_ratio=999,
            vertical_offset=999,
            shadow=ShadowStyle(color="oops", opacity=120, offset_x=99, offset_y=-99),
            stroke=StrokeStyle(color="oops", opacity=-1, width=99),
        ).normalized()

        self.assertEqual(style.font_family, "Arial")
        self.assertEqual(style.font_size_mode, "auto")
        self.assertEqual(style.font_size, 160)
        self.assertEqual(style.text_color, "#ffdc5a")
        self.assertEqual(style.bottom_padding_ratio, 0.3)
        self.assertEqual(style.side_padding_ratio, 0.3)
        self.assertEqual(style.vertical_offset, 400)
        self.assertEqual(style.shadow.color, "#000000")
        self.assertEqual(style.shadow.opacity, 100)
        self.assertEqual(style.shadow.offset_x, 20)
        self.assertEqual(style.shadow.offset_y, -20)
        self.assertEqual(style.stroke.color, "#141414")
        self.assertEqual(style.stroke.opacity, 0)
        self.assertEqual(style.stroke.width, 12)

    def test_normalizes_invalid_watermark_values(self) -> None:
        watermark = WatermarkConfig(
            source_type="broken",
            text="  Demo  ",
            image_path="  C:/logo.png  ",
            show_detected_number=1,
            opacity=999,
            scale_percent=1,
            position="middle",
            margin_ratio=2,
            vertical_offset=-999,
        ).normalized()

        self.assertEqual(watermark.source_type, "text")
        self.assertEqual(watermark.text, "Demo")
        self.assertEqual(watermark.image_path, "C:/logo.png")
        self.assertTrue(watermark.show_detected_number)
        self.assertEqual(watermark.opacity, 100)
        self.assertEqual(watermark.scale_percent, 5)
        self.assertEqual(watermark.position, "bottom_right")
        self.assertEqual(watermark.margin_ratio, 0.3)
        self.assertEqual(watermark.vertical_offset, -400)

    def test_builtin_and_user_presets_have_expected_defaults(self) -> None:
        builtins = get_builtin_presets()
        users = get_default_user_presets()

        self.assertEqual(len(builtins), 3)
        self.assertEqual(len(users), 3)
        self.assertEqual(builtins[0].name, "Clasico EXIF")
        self.assertEqual(users[0].preset_id, "user_1")
        self.assertFalse(users[0].built_in)


if __name__ == "__main__":
    unittest.main()
