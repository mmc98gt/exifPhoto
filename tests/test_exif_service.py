import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

import piexif
from PIL import Image

from app.exif_service import extract_display_data


class ExtractDisplayDataTests(unittest.TestCase):
    def test_extracts_and_formats_jpeg_exif_fields(self) -> None:
        with temporary_test_dir() as temp_dir:
            image_path = Path(temp_dir) / "sample.jpg"
            self._create_jpeg_with_exif(
                image_path,
                exposure=(1, 250),
                aperture=(28, 10),
                iso=400,
            )

            display_data = extract_display_data(str(image_path))

            self.assertEqual(
                display_data,
                {
                    "exposure": "1/250 s",
                    "aperture": "f/2.8",
                    "iso": "ISO 400",
                },
            )

    def test_returns_nd_for_missing_jpeg_exif(self) -> None:
        with temporary_test_dir() as temp_dir:
            image_path = Path(temp_dir) / "sample.jpg"
            Image.new("RGB", (120, 80), "white").save(image_path, format="JPEG")

            display_data = extract_display_data(str(image_path))

            self.assertEqual(
                display_data,
                {
                    "exposure": "N/D",
                    "aperture": "N/D",
                    "iso": "N/D",
                },
            )

    def test_returns_nd_for_png_without_useful_exif(self) -> None:
        with temporary_test_dir() as temp_dir:
            image_path = Path(temp_dir) / "sample.png"
            Image.new("RGBA", (120, 80), "blue").save(image_path, format="PNG")

            display_data = extract_display_data(str(image_path))

            self.assertEqual(
                display_data,
                {
                    "exposure": "N/D",
                    "aperture": "N/D",
                    "iso": "N/D",
                },
            )

    def test_raises_for_unsupported_extension(self) -> None:
        with temporary_test_dir() as temp_dir:
            file_path = Path(temp_dir) / "sample.txt"
            file_path.write_text("not an image", encoding="utf-8")

            with self.assertRaises(ValueError):
                extract_display_data(str(file_path))

    @staticmethod
    def _create_jpeg_with_exif(
        image_path: Path,
        exposure: tuple[int, int],
        aperture: tuple[int, int],
        iso: int,
    ) -> None:
        Image.new("RGB", (120, 80), "white").save(image_path, format="JPEG")
        exif_dict = {
            "0th": {},
            "Exif": {
                piexif.ExifIFD.ExposureTime: exposure,
                piexif.ExifIFD.FNumber: aperture,
                piexif.ExifIFD.ISOSpeedRatings: iso,
            },
            "GPS": {},
            "1st": {},
            "thumbnail": None,
        }
        piexif.insert(piexif.dump(exif_dict), str(image_path))


@contextmanager
def temporary_test_dir():
    temp_root = Path(__file__).resolve().parent / ".tmp"
    temp_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=temp_root) as temp_dir:
        yield temp_dir


if __name__ == "__main__":
    unittest.main()
