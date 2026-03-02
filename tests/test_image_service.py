import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from PIL import Image

from app.image_service import create_annotated_copy


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
                    },
                )
            )

            self.assertTrue(output_path.exists())
            self.assertEqual(output_path.parent.name, "exportadas")
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

            first_output = Path(create_annotated_copy(str(image_path), _sample_data()))
            second_output = Path(create_annotated_copy(str(image_path), _sample_data()))

            self.assertTrue(first_output.exists())
            self.assertTrue(second_output.exists())
            self.assertEqual(first_output.name, "source_exif.jpg")
            self.assertEqual(second_output.name, "source_exif_1.jpg")

    def test_preserves_png_extension_for_png_output(self) -> None:
        with temporary_test_dir() as temp_dir:
            image_path = Path(temp_dir) / "source.png"
            Image.new("RGBA", (200, 100), (10, 20, 30, 255)).save(image_path, format="PNG")

            output_path = Path(create_annotated_copy(str(image_path), _sample_data()))

            self.assertTrue(output_path.exists())
            self.assertEqual(output_path.suffix.lower(), ".png")

            with Image.open(output_path) as processed_image:
                self.assertEqual(processed_image.size[0], 200)
                self.assertEqual(processed_image.size[1], 100)

    def test_resizes_tall_image_to_2160_height(self) -> None:
        with temporary_test_dir() as temp_dir:
            image_path = Path(temp_dir) / "large.jpg"
            Image.new("RGB", (6000, 4000), "white").save(image_path, format="JPEG")

            output_path = Path(create_annotated_copy(str(image_path), _sample_data()))

            with Image.open(output_path) as processed_image:
                self.assertEqual(processed_image.size, (3240, 2160))
                self.assertTrue(_has_non_background_pixels_near_bottom(processed_image))

    def test_raises_for_non_image_file_with_supported_extension(self) -> None:
        with temporary_test_dir() as temp_dir:
            image_path = Path(temp_dir) / "broken.jpg"
            image_path.write_text("invalid image content", encoding="utf-8")

            with self.assertRaises(ValueError):
                create_annotated_copy(str(image_path), _sample_data())


def _sample_data() -> dict[str, str]:
    return {
        "exposure": "1/250 s",
        "iso": "ISO 400",
        "aperture": "f/2.8",
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


@contextmanager
def temporary_test_dir():
    temp_root = Path(__file__).resolve().parent / ".tmp"
    temp_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=temp_root) as temp_dir:
        yield temp_dir


if __name__ == "__main__":
    unittest.main()
