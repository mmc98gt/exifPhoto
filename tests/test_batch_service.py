import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from threading import Event
from unittest.mock import patch

from PIL import Image

from app.batch_service import BatchProgress, process_images, process_images_to_16_9_frame
from app.overlay_config import OverlayPreset, OverlayStyle, ShadowStyle, StrokeStyle, WatermarkConfig, get_builtin_presets


class ProcessImagesTests(unittest.TestCase):
    def test_processes_multiple_images_and_reports_progress(self) -> None:
        with temporary_test_dir() as temp_dir:
            image_one = Path(temp_dir) / "one.jpg"
            image_two = Path(temp_dir) / "two.jpg"
            Image.new("RGB", (320, 200), "white").save(image_one, format="JPEG")
            Image.new("RGB", (200, 120), "white").save(image_two, format="JPEG")

            progress_events: list[BatchProgress] = []
            result = process_images(
                [str(image_one), str(image_two)],
                preset=get_builtin_presets()[0],
                max_workers=2,
                progress_callback=progress_events.append,
            )

            self.assertEqual(result.processed_count, 2)
            self.assertEqual(result.failures, [])
            self.assertEqual(len(progress_events), 2)
            self.assertEqual(progress_events[-1].current, 2)
            self.assertEqual(progress_events[-1].total, 2)
            self.assertEqual({event.image_name for event in progress_events}, {"one.jpg", "two.jpg"})
            export_dir = _expected_export_dir(image_one.parent)
            self.assertTrue((export_dir / "one_exif.jpg").exists())
            self.assertTrue((export_dir / "two_exif.jpg").exists())

    def test_collects_failures_without_stopping_other_images(self) -> None:
        with temporary_test_dir() as temp_dir:
            valid_image = Path(temp_dir) / "valid.jpg"
            broken_image = Path(temp_dir) / "broken.jpg"
            missing_image = Path(temp_dir) / "missing.jpg"

            Image.new("RGB", (200, 120), "white").save(valid_image, format="JPEG")
            broken_image.write_text("not an image", encoding="utf-8")

            progress_events: list[BatchProgress] = []
            result = process_images(
                [str(valid_image), str(broken_image), str(missing_image)],
                preset=get_builtin_presets()[0],
                max_workers=3,
                progress_callback=progress_events.append,
            )

            self.assertEqual(result.processed_count, 1)
            self.assertEqual(len(result.failures), 2)
            self.assertEqual(len(progress_events), 3)
            self.assertTrue(any("broken.jpg" in failure for failure in result.failures))
            self.assertTrue(any("missing.jpg" in failure for failure in result.failures))
            self.assertTrue((_expected_export_dir(valid_image.parent) / "valid_exif.jpg").exists())

    def test_stops_submitting_new_images_after_cancellation(self) -> None:
        with temporary_test_dir() as temp_dir:
            image_paths: list[str] = []
            for index in range(3):
                image_path = Path(temp_dir) / f"image_{index}.jpg"
                Image.new("RGB", (240, 120), "white").save(image_path, format="JPEG")
                image_paths.append(str(image_path))

            cancel_event = Event()
            progress_events: list[BatchProgress] = []

            def on_progress(progress: BatchProgress) -> None:
                progress_events.append(progress)
                cancel_event.set()

            result = process_images(
                image_paths,
                preset=get_builtin_presets()[0],
                max_workers=1,
                progress_callback=on_progress,
                cancel_event=cancel_event,
            )

            self.assertTrue(result.cancelled)
            self.assertEqual(result.processed_count, 1)
            self.assertEqual(result.failures, [])
            self.assertEqual(len(progress_events), 1)
            export_dir = _expected_export_dir(Path(temp_dir))
            self.assertTrue((export_dir / "image_0_exif.jpg").exists())
            self.assertFalse((export_dir / "image_1_exif.jpg").exists())

    def test_uses_snapshot_of_preset_passed_at_start(self) -> None:
        with temporary_test_dir() as temp_dir:
            image_path = Path(temp_dir) / "snapshot.jpg"
            Image.new("RGB", (240, 120), "white").save(image_path, format="JPEG")
            preset = get_builtin_presets()[0]
            snapshot_preset = preset.__class__(
                preset_id=preset.preset_id,
                name=preset.name,
                built_in=preset.built_in,
                fields=preset.fields,
                style=OverlayStyle.from_dict({**preset.style.to_dict(), "text_color": "#123456"}),
            )

            result = process_images([str(image_path)], preset=snapshot_preset, max_workers=1)

            self.assertEqual(result.processed_count, 1)
            self.assertTrue((_expected_export_dir(Path(temp_dir)) / "snapshot_exif.jpg").exists())

    def test_skips_exif_extraction_for_watermark_mode(self) -> None:
        with temporary_test_dir() as temp_dir:
            image_path = Path(temp_dir) / "watermark.jpg"
            Image.new("RGB", (240, 120), "white").save(image_path, format="JPEG")
            preset = OverlayPreset(
                preset_id="wm",
                name="Watermark",
                built_in=False,
                mode="watermark",
                style=OverlayStyle.from_dict({**get_builtin_presets()[0].style.to_dict(), "font_size_mode": "manual", "font_size": 28}),
                watermark=WatermarkConfig(source_type="text", text="Brand", opacity=60, position="bottom_right"),
            )

            with patch("app.batch_service.extract_display_data", side_effect=AssertionError("No deberia leer EXIF")):
                result = process_images([str(image_path)], preset=preset, max_workers=1)

            self.assertEqual(result.processed_count, 1)
            self.assertTrue((_expected_export_dir(Path(temp_dir)) / "watermark_watermark.jpg").exists())

    def test_process_images_to_16_9_frame_uses_selected_exif_preset(self) -> None:
        with temporary_test_dir() as temp_dir:
            image_path = Path(temp_dir) / "frame.jpg"
            Image.new("RGB", (800, 1200), "white").save(image_path, format="JPEG")
            preset = OverlayPreset(
                preset_id="frame_exif",
                name="Frame EXIF",
                built_in=False,
                mode="exif",
                style=OverlayStyle(
                    font_family="Arial",
                    font_size_mode="manual",
                    font_size=80,
                    text_color="#000000",
                    shadow=ShadowStyle(enabled=False, color="#000000", opacity=0, offset_x=0, offset_y=0),
                    stroke=StrokeStyle(enabled=False, color="#000000", opacity=0, width=0),
                ),
            )

            with patch("app.batch_service.extract_display_data", return_value=_sample_data()):
                result = process_images_to_16_9_frame([str(image_path)], preset=preset, max_workers=1)

            self.assertEqual(result.processed_count, 1)
            self.assertTrue((_expected_export_dir_16_9(Path(temp_dir)) / "frame_16x9_4k.jpg").exists())

    def test_process_images_to_16_9_frame_skips_exif_for_none_mode(self) -> None:
        with temporary_test_dir() as temp_dir:
            image_path = Path(temp_dir) / "plain.jpg"
            Image.new("RGB", (800, 1200), "white").save(image_path, format="JPEG")
            preset = OverlayPreset(
                preset_id="frame_none",
                name="Frame none",
                built_in=False,
                mode="none",
            )

            with patch("app.batch_service.extract_display_data", side_effect=AssertionError("No deberia leer EXIF")):
                result = process_images_to_16_9_frame([str(image_path)], preset=preset, max_workers=1)

            self.assertEqual(result.processed_count, 1)
            self.assertTrue((_expected_export_dir_16_9(Path(temp_dir)) / "plain_16x9_4k.jpg").exists())


@contextmanager
def temporary_test_dir():
    temp_root = Path(__file__).resolve().parent / ".tmp"
    temp_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=temp_root) as temp_dir:
        yield temp_dir


def _expected_export_dir(source_dir: Path) -> Path:
    return source_dir.parent / f"{source_dir.name}_exportadas"


def _expected_export_dir_16_9(source_dir: Path) -> Path:
    return source_dir.parent / f"{source_dir.name}_exportadas_16x9_4k"


def _sample_data() -> dict[str, str]:
    return {
        "exposure": "1/250 s",
        "iso": "ISO 400",
        "aperture": "f/2.8",
        "focal_length": "50 mm",
    }


if __name__ == "__main__":
    unittest.main()
