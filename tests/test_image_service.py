import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

import piexif
from PIL import Image
from PIL import PngImagePlugin

from app.image_service import build_overlay_text, create_annotated_copy, render_overlay
from app.overlay_config import OverlayFieldConfig, OverlayPreset, OverlayStyle, ShadowStyle, StrokeStyle, WatermarkConfig, get_builtin_presets


class CreateAnnotatedCopyTests(unittest.TestCase):
    def test_creates_jpeg_copy_in_export_folder_with_overlay_text(self) -> None:
        with temporary_test_dir() as temp_dir:
            image_path = Path(temp_dir) / "source.jpg"
            Image.new("RGB", (320, 200), "white").save(image_path, format="JPEG")

            output_path = Path(
                create_annotated_copy(
                    str(image_path),
                    {
                        "exposure": "1/250 s",
                        "iso": "ISO 400",
                        "aperture": "f/2.8",
                        "focal_length": "50 mm",
                    },
                    get_builtin_presets()[0],
                )
            )

            self.assertTrue(output_path.exists())
            self.assertEqual(output_path.parent.name, f"{image_path.parent.name}_exportadas")
            self.assertEqual(output_path.name, "source_exif.jpg")

            with Image.open(image_path) as original_image:
                original_size = original_image.size

            with Image.open(output_path) as processed_image:
                processed_size = processed_image.size
                has_overlay = _has_non_background_pixels_near_bottom(processed_image)

            self.assertEqual(original_size, (320, 200))
            self.assertEqual(processed_size[0], original_size[0])
            self.assertEqual(processed_size[1], original_size[1])
            self.assertTrue(has_overlay)

    def test_creates_incremental_name_when_output_already_exists(self) -> None:
        with temporary_test_dir() as temp_dir:
            image_path = Path(temp_dir) / "source.jpg"
            Image.new("RGB", (240, 120), "white").save(image_path, format="JPEG")

            first_output = Path(create_annotated_copy(str(image_path), _sample_data(), get_builtin_presets()[0]))
            second_output = Path(create_annotated_copy(str(image_path), _sample_data(), get_builtin_presets()[0]))

            self.assertTrue(first_output.exists())
            self.assertTrue(second_output.exists())
            self.assertEqual(first_output.name, "source_exif.jpg")
            self.assertEqual(second_output.name, "source_exif_1.jpg")

    def test_preserves_png_extension_for_png_output(self) -> None:
        with temporary_test_dir() as temp_dir:
            image_path = Path(temp_dir) / "source.png"
            Image.new("RGBA", (200, 100), (10, 20, 30, 255)).save(image_path, format="PNG")

            output_path = Path(create_annotated_copy(str(image_path), _sample_data(), get_builtin_presets()[0]))

            self.assertTrue(output_path.exists())
            self.assertEqual(output_path.suffix.lower(), ".png")

            with Image.open(output_path) as processed_image:
                self.assertEqual(processed_image.size[0], 200)
                self.assertEqual(processed_image.size[1], 100)

    def test_preserves_jpeg_exif_metadata_in_export(self) -> None:
        with temporary_test_dir() as temp_dir:
            image_path = Path(temp_dir) / "source.jpg"
            Image.new("RGB", (320, 200), "white").save(image_path, format="JPEG")
            original_exif = {
                "0th": {
                    piexif.ImageIFD.Make: b"Nikon",
                    piexif.ImageIFD.Model: b"D750",
                },
                "Exif": {
                    piexif.ExifIFD.ExposureTime: (1, 250),
                    piexif.ExifIFD.FNumber: (28, 10),
                    piexif.ExifIFD.ISOSpeedRatings: 400,
                },
                "GPS": {},
                "1st": {},
                "thumbnail": None,
            }
            piexif.insert(piexif.dump(original_exif), str(image_path))

            output_path = Path(create_annotated_copy(str(image_path), _sample_data(), get_builtin_presets()[0]))

            with Image.open(output_path) as processed_image:
                exported_exif = piexif.load(processed_image.info["exif"])

            self.assertEqual(exported_exif["0th"][piexif.ImageIFD.Make], b"Nikon")
            self.assertEqual(exported_exif["0th"][piexif.ImageIFD.Model], b"D750")
            self.assertEqual(exported_exif["Exif"][piexif.ExifIFD.ISOSpeedRatings], 400)

    def test_preserves_png_text_metadata_in_export(self) -> None:
        with temporary_test_dir() as temp_dir:
            image_path = Path(temp_dir) / "source.png"
            pnginfo = PngImagePlugin.PngInfo()
            pnginfo.add_text("Author", "Maci")
            pnginfo.add_text("Description", "Partido")
            Image.new("RGBA", (200, 100), (10, 20, 30, 255)).save(image_path, format="PNG", pnginfo=pnginfo)

            output_path = Path(create_annotated_copy(str(image_path), _sample_data(), get_builtin_presets()[0]))

            with Image.open(output_path) as processed_image:
                self.assertEqual(processed_image.text.get("Author"), "Maci")
                self.assertEqual(processed_image.text.get("Description"), "Partido")

    def test_resizes_tall_image_to_2160_height(self) -> None:
        with temporary_test_dir() as temp_dir:
            image_path = Path(temp_dir) / "large.jpg"
            Image.new("RGB", (6000, 4000), "white").save(image_path, format="JPEG")

            output_path = Path(create_annotated_copy(str(image_path), _sample_data(), get_builtin_presets()[0]))

            with Image.open(output_path) as processed_image:
                self.assertEqual(processed_image.size, (3240, 2160))
                self.assertTrue(_has_non_background_pixels_near_bottom(processed_image))

    def test_raises_for_non_image_file_with_supported_extension(self) -> None:
        with temporary_test_dir() as temp_dir:
            image_path = Path(temp_dir) / "broken.jpg"
            image_path.write_text("invalid image content", encoding="utf-8")

            with self.assertRaises(ValueError):
                create_annotated_copy(str(image_path), _sample_data(), get_builtin_presets()[0])

    def test_build_overlay_text_omits_disabled_fields(self) -> None:
        text = build_overlay_text(
            _sample_data(),
            OverlayFieldConfig(show_iso=False, show_focal_length=False, separator=" / "),
        )

        self.assertEqual(text, "1/250 s / f/2.8")

    def test_build_overlay_text_returns_empty_when_all_fields_disabled(self) -> None:
        text = build_overlay_text(
            _sample_data(),
            OverlayFieldConfig(
                show_exposure=False,
                show_iso=False,
                show_aperture=False,
                show_focal_length=False,
            ),
        )

        self.assertEqual(text, "")

    def test_render_overlay_without_shadow_and_stroke_still_draws_text(self) -> None:
        with temporary_test_dir() as temp_dir:
            image_path = Path(temp_dir) / "source.jpg"
            Image.new("RGB", (320, 200), "white").save(image_path, format="JPEG")
            preset = get_builtin_presets()[0]
            preset = preset.__class__(
                preset_id=preset.preset_id,
                name=preset.name,
                built_in=preset.built_in,
                fields=preset.fields,
                style=OverlayStyle(
                    font_family="Arial",
                    font_size_mode="manual",
                    font_size=28,
                    text_color="#ff0000",
                    shadow=ShadowStyle(enabled=False, color="#000000", opacity=0, offset_x=0, offset_y=0),
                    stroke=StrokeStyle(enabled=False, color="#000000", opacity=0, width=0),
                ),
            )

            rendered = render_overlay(str(image_path), _sample_data(), preset)

            self.assertTrue(_has_non_background_pixels_near_bottom(rendered))

    def test_create_annotated_copy_uses_received_preset(self) -> None:
        with temporary_test_dir() as temp_dir:
            image_path = Path(temp_dir) / "source.jpg"
            Image.new("RGB", (320, 200), "white").save(image_path, format="JPEG")
            preset = get_builtin_presets()[0]
            custom_preset = preset.__class__(
                preset_id=preset.preset_id,
                name=preset.name,
                built_in=preset.built_in,
                fields=OverlayFieldConfig(show_iso=False, show_focal_length=False, separator=" - "),
                style=OverlayStyle(
                    font_family="Arial",
                    font_size_mode="manual",
                    font_size=28,
                    text_color="#00aa00",
                    shadow=preset.style.shadow,
                    stroke=preset.style.stroke,
                ),
            )

            output_path = Path(create_annotated_copy(str(image_path), _sample_data(), custom_preset))

            self.assertTrue(output_path.exists())
            with Image.open(output_path) as processed_image:
                self.assertTrue(_has_non_background_pixels_near_bottom(processed_image))

    def test_creates_watermark_text_copy_in_export_folder(self) -> None:
        with temporary_test_dir() as temp_dir:
            image_path = Path(temp_dir) / "@maciphotographs_0001.jpg"
            Image.new("RGB", (400, 240), "white").save(image_path, format="JPEG")
            preset = OverlayPreset(
                preset_id="wm_text",
                name="Watermark text",
                built_in=False,
                mode="watermark",
                style=OverlayStyle(
                    font_family="Arial",
                    font_size_mode="manual",
                    font_size=30,
                    text_color="#000000",
                    shadow=ShadowStyle(enabled=False, color="#000000", opacity=0, offset_x=0, offset_y=0),
                    stroke=StrokeStyle(enabled=False, color="#000000", opacity=0, width=0),
                ),
                watermark=WatermarkConfig(
                    source_type="text",
                    text="Studio",
                    opacity=70,
                    position="bottom_right",
                ),
            )

            output_path = Path(create_annotated_copy(str(image_path), None, preset))

            self.assertTrue(output_path.exists())
            self.assertEqual(output_path.name, "@maciphotographs_0001_watermark.jpg")
            with Image.open(output_path) as processed_image:
                self.assertTrue(_has_non_background_pixels(processed_image))

    def test_render_overlay_supports_image_watermark(self) -> None:
        with temporary_test_dir() as temp_dir:
            image_path = Path(temp_dir) / "source.png"
            watermark_path = Path(temp_dir) / "wm.png"
            Image.new("RGBA", (320, 200), (255, 255, 255, 255)).save(image_path, format="PNG")
            Image.new("RGBA", (64, 32), (255, 0, 0, 180)).save(watermark_path, format="PNG")
            preset = OverlayPreset(
                preset_id="wm_image",
                name="Watermark image",
                built_in=False,
                mode="watermark",
                style=get_builtin_presets()[0].style,
                watermark=WatermarkConfig(
                    source_type="image",
                    image_path=str(watermark_path),
                    opacity=100,
                    scale_percent=25,
                    position="top_left",
                ),
            )

            rendered = render_overlay(str(image_path), None, preset)

            self.assertTrue(_has_non_background_pixels(rendered))

    def test_exif_vertical_offset_moves_overlay_up(self) -> None:
        with temporary_test_dir() as temp_dir:
            image_path = Path(temp_dir) / "source.jpg"
            Image.new("RGB", (400, 240), "white").save(image_path, format="JPEG")
            base_preset = OverlayPreset(
                preset_id="exif_base",
                name="Exif base",
                built_in=False,
                mode="exif",
                fields=OverlayFieldConfig(),
                style=OverlayStyle(
                    font_family="Arial",
                    font_size_mode="manual",
                    font_size=28,
                    text_color="#000000",
                    vertical_offset=0,
                    shadow=ShadowStyle(enabled=False, color="#000000", opacity=0, offset_x=0, offset_y=0),
                    stroke=StrokeStyle(enabled=False, color="#000000", opacity=0, width=0),
                ),
            )
            moved_preset = OverlayPreset(
                preset_id="exif_up",
                name="Exif up",
                built_in=False,
                mode="exif",
                fields=base_preset.fields,
                style=OverlayStyle.from_dict({**base_preset.style.to_dict(), "vertical_offset": -40}),
            )

            baseline = render_overlay(str(image_path), _sample_data(), base_preset)
            moved = render_overlay(str(image_path), _sample_data(), moved_preset)

            self.assertLess(_topmost_non_background_pixel_y(moved), _topmost_non_background_pixel_y(baseline))

    def test_image_watermark_vertical_offset_moves_overlay_up(self) -> None:
        with temporary_test_dir() as temp_dir:
            image_path = Path(temp_dir) / "source.png"
            watermark_path = Path(temp_dir) / "wm.png"
            Image.new("RGBA", (320, 220), (255, 255, 255, 255)).save(image_path, format="PNG")
            Image.new("RGBA", (60, 30), (255, 0, 0, 255)).save(watermark_path, format="PNG")
            base_preset = OverlayPreset(
                preset_id="wm_base",
                name="Watermark base",
                built_in=False,
                mode="watermark",
                style=get_builtin_presets()[0].style,
                watermark=WatermarkConfig(
                    source_type="image",
                    image_path=str(watermark_path),
                    opacity=100,
                    scale_percent=25,
                    position="bottom_center",
                    vertical_offset=0,
                ),
            )
            moved_preset = OverlayPreset(
                preset_id="wm_up",
                name="Watermark up",
                built_in=False,
                mode="watermark",
                style=base_preset.style,
                watermark=WatermarkConfig.from_dict({**base_preset.watermark.to_dict(), "vertical_offset": -50}),
            )

            baseline = render_overlay(str(image_path), None, base_preset)
            moved = render_overlay(str(image_path), None, moved_preset)

            self.assertLess(_topmost_non_background_pixel_y(moved), _topmost_non_background_pixel_y(baseline))

    def test_detected_number_is_drawn_below_text_watermark(self) -> None:
        with temporary_test_dir() as temp_dir:
            image_path = Path(temp_dir) / "@maciphotographs_0001.jpg"
            Image.new("RGB", (420, 260), "white").save(image_path, format="JPEG")
            base_style = OverlayStyle(
                font_family="Arial",
                font_size_mode="manual",
                font_size=30,
                text_color="#000000",
                shadow=ShadowStyle(enabled=False, color="#000000", opacity=0, offset_x=0, offset_y=0),
                stroke=StrokeStyle(enabled=False, color="#000000", opacity=0, width=0),
            )
            base_preset = OverlayPreset(
                preset_id="wm_text_base",
                name="Watermark text base",
                built_in=False,
                mode="watermark",
                style=base_style,
                watermark=WatermarkConfig(
                    source_type="text",
                    text="@maciphotographs",
                    position="bottom_center",
                    opacity=100,
                    show_detected_number=False,
                ),
            )
            numbered_preset = OverlayPreset(
                preset_id="wm_text_num",
                name="Watermark text num",
                built_in=False,
                mode="watermark",
                style=base_style,
                watermark=WatermarkConfig.from_dict({**base_preset.watermark.to_dict(), "show_detected_number": True}),
            )

            baseline = render_overlay(str(image_path), None, base_preset)
            numbered = render_overlay(str(image_path), None, numbered_preset)

            self.assertLess(_topmost_non_background_pixel_y(numbered), _topmost_non_background_pixel_y(baseline))

    def test_detected_number_is_drawn_below_image_watermark(self) -> None:
        with temporary_test_dir() as temp_dir:
            image_path = Path(temp_dir) / "@maciphotographs_0042.png"
            watermark_path = Path(temp_dir) / "wm.png"
            Image.new("RGBA", (380, 260), (255, 255, 255, 255)).save(image_path, format="PNG")
            Image.new("RGBA", (90, 36), (255, 0, 0, 255)).save(watermark_path, format="PNG")
            base_preset = OverlayPreset(
                preset_id="wm_image_base",
                name="Watermark image base",
                built_in=False,
                mode="watermark",
                style=OverlayStyle(
                    font_family="Arial",
                    font_size_mode="manual",
                    font_size=28,
                    text_color="#000000",
                    shadow=ShadowStyle(enabled=False, color="#000000", opacity=0, offset_x=0, offset_y=0),
                    stroke=StrokeStyle(enabled=False, color="#000000", opacity=0, width=0),
                ),
                watermark=WatermarkConfig(
                    source_type="image",
                    image_path=str(watermark_path),
                    position="bottom_center",
                    opacity=100,
                    scale_percent=28,
                    show_detected_number=False,
                ),
            )
            numbered_preset = OverlayPreset(
                preset_id="wm_image_num",
                name="Watermark image num",
                built_in=False,
                mode="watermark",
                style=base_preset.style,
                watermark=WatermarkConfig.from_dict({**base_preset.watermark.to_dict(), "show_detected_number": True}),
            )

            baseline = render_overlay(str(image_path), None, base_preset)
            numbered = render_overlay(str(image_path), None, numbered_preset)

            self.assertLess(_topmost_non_background_pixel_y(numbered), _topmost_non_background_pixel_y(baseline))


def _sample_data() -> dict[str, str]:
    return {
        "exposure": "1/250 s",
        "iso": "ISO 400",
        "aperture": "f/2.8",
        "focal_length": "50 mm",
    }


def _has_non_background_pixels_near_bottom(image: Image.Image) -> bool:
    rgb_image = image.convert("RGB")
    width, height = rgb_image.size
    start_y = max(0, height - max(25, height // 6))

    for y in range(start_y, height):
        for x in range(width):
            if rgb_image.getpixel((x, y)) != (255, 255, 255):
                return True

    return False


def _has_non_background_pixels(image: Image.Image) -> bool:
    rgb_image = image.convert("RGB")
    width, height = rgb_image.size

    for y in range(height):
        for x in range(width):
            if rgb_image.getpixel((x, y)) != (255, 255, 255):
                return True

    return False


def _topmost_non_background_pixel_y(image: Image.Image) -> int:
    rgb_image = image.convert("RGB")
    width, height = rgb_image.size

    for y in range(height):
        for x in range(width):
            if rgb_image.getpixel((x, y)) != (255, 255, 255):
                return y

    return height


def _bottommost_non_background_pixel_y(image: Image.Image) -> int:
    rgb_image = image.convert("RGB")
    width, height = rgb_image.size

    for y in range(height - 1, -1, -1):
        for x in range(width):
            if rgb_image.getpixel((x, y)) != (255, 255, 255):
                return y

    return -1


@contextmanager
def temporary_test_dir():
    temp_root = Path(__file__).resolve().parent / ".tmp"
    temp_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=temp_root) as temp_dir:
        yield temp_dir


if __name__ == "__main__":
    unittest.main()
