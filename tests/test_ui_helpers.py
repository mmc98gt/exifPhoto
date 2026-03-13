import tempfile
import unittest
from pathlib import Path

from app.ui import _format_destination_text, collect_supported_images_from_folder, normalize_paths


class UiHelperTests(unittest.TestCase):
    def test_normalize_paths_filters_unsupported_and_removes_duplicates(self) -> None:
        with temporary_test_dir() as temp_dir:
            folder = Path(temp_dir)
            jpg_file = folder / "photo.jpg"
            png_file = folder / "graphic.png"
            txt_file = folder / "notes.txt"

            jpg_file.write_bytes(b"jpg")
            png_file.write_bytes(b"png")
            txt_file.write_text("unsupported", encoding="utf-8")

            normalized = normalize_paths(
                [
                    str(jpg_file),
                    str(png_file),
                    str(txt_file),
                    str(jpg_file),
                ]
            )

            self.assertEqual(normalized, sorted([str(jpg_file.resolve()), str(png_file.resolve())]))

    def test_collect_supported_images_from_folder_returns_only_supported_files(self) -> None:
        with temporary_test_dir() as temp_dir:
            folder = Path(temp_dir)
            jpg_file = folder / "b.jpg"
            jpeg_file = folder / "a.jpeg"
            png_file = folder / "c.png"
            subdir = folder / "nested"
            txt_file = folder / "z.txt"

            jpg_file.write_bytes(b"jpg")
            jpeg_file.write_bytes(b"jpeg")
            png_file.write_bytes(b"png")
            txt_file.write_text("unsupported", encoding="utf-8")
            subdir.mkdir()
            (subdir / "hidden.jpg").write_bytes(b"nested")

            collected = collect_supported_images_from_folder(str(folder))

            self.assertEqual(
                collected,
                [
                    str(jpeg_file.resolve()),
                    str(jpg_file.resolve()),
                    str(png_file.resolve()),
                ],
            )

    def test_collect_supported_images_from_folder_returns_empty_for_invalid_path(self) -> None:
        with temporary_test_dir() as temp_dir:
            missing = Path(temp_dir) / "missing"
            self.assertEqual(collect_supported_images_from_folder(str(missing)), [])

    def test_format_destination_text_uses_root_folder_name_with_export_suffix(self) -> None:
        with temporary_test_dir() as temp_dir:
            source_dir = Path(temp_dir) / "partido_01"
            source_dir.mkdir()
            image_path = source_dir / "foto.jpg"
            image_path.write_bytes(b"jpg")

            destination_text = _format_destination_text([str(image_path.resolve())])

            self.assertEqual(destination_text, f"Salida: {source_dir.parent / 'partido_01_exportadas'}")


def temporary_test_dir():
    temp_root = Path(__file__).resolve().parent / ".tmp"
    temp_root.mkdir(exist_ok=True)
    return tempfile.TemporaryDirectory(dir=temp_root)


if __name__ == "__main__":
    unittest.main()
