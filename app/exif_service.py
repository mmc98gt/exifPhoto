from __future__ import annotations

from fractions import Fraction
from pathlib import Path
from typing import Any

import piexif

NOT_AVAILABLE = "N/D"
SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png"}
INVALID_EXIF_ERRORS = tuple(
    error
    for error in (
        OSError,
        ValueError,
        getattr(piexif, "InvalidImageDataError", None),
        getattr(getattr(piexif, "_exceptions", object()), "InvalidImageDataError", None),
    )
    if error is not None
)


def extract_display_data(image_path: str) -> dict[str, str]:
    path = Path(image_path)
    _validate_input_path(path)

    exif_dict = _safe_load_exif(path)
    if not exif_dict:
        return _empty_display_data()

    exif_ifd = exif_dict.get("Exif", {})
    exposure_value = exif_ifd.get(piexif.ExifIFD.ExposureTime)
    aperture_value = exif_ifd.get(piexif.ExifIFD.FNumber)
    iso_value = _get_iso_value(exif_ifd)
    focal_length_value = exif_ifd.get(piexif.ExifIFD.FocalLength)

    return {
        "exposure": _format_exposure(exposure_value),
        "aperture": _format_fnumber(aperture_value),
        "iso": _format_iso(iso_value),
        "focal_length": _format_focal_length(focal_length_value),
    }


def _validate_input_path(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"No se encontro el archivo: {path}")
    if not path.is_file():
        raise ValueError(f"La ruta seleccionada no es un archivo valido: {path}")
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ValueError("Formato no soportado. Usa archivos JPG, JPEG o PNG.")


def _safe_load_exif(image_path: Path) -> dict[str, Any] | None:
    try:
        return piexif.load(str(image_path))
    except INVALID_EXIF_ERRORS:
        return None


def _empty_display_data() -> dict[str, str]:
    return {
        "exposure": NOT_AVAILABLE,
        "aperture": NOT_AVAILABLE,
        "iso": NOT_AVAILABLE,
        "focal_length": NOT_AVAILABLE,
    }


def _get_iso_value(exif_ifd: dict[int, Any]) -> Any:
    iso_keys = [
        getattr(piexif.ExifIFD, "ISOSpeedRatings", None),
        getattr(piexif.ExifIFD, "PhotographicSensitivity", None),
    ]

    for key in iso_keys:
        if key is not None and key in exif_ifd:
            return exif_ifd.get(key)

    return None


def _format_exposure(value: Any) -> str:
    if value is None:
        return NOT_AVAILABLE

    if isinstance(value, (tuple, list)) and len(value) == 2:
        seconds = _rational_to_float(value)
        if seconds is None or seconds <= 0:
            return NOT_AVAILABLE
        numerator, denominator = value
        if isinstance(numerator, int) and isinstance(denominator, int) and numerator < denominator:
            return f"{numerator}/{denominator} s"
        if seconds >= 1:
            return f"{_format_decimal(seconds)} s"
        return f"{_format_decimal(seconds, precision=4)} s"

    seconds = _rational_to_float(value)
    if seconds is None or seconds <= 0:
        return NOT_AVAILABLE

    if seconds >= 1:
        return f"{_format_decimal(seconds)} s"

    fraction = Fraction(seconds).limit_denominator(8000)
    if abs(float(fraction) - seconds) <= 0.0001:
        return f"{fraction.numerator}/{fraction.denominator} s"

    return f"{_format_decimal(seconds, precision=4)} s"


def _format_fnumber(value: Any) -> str:
    aperture = _rational_to_float(value)
    if aperture is None or aperture <= 0:
        return NOT_AVAILABLE
    return f"f/{_format_decimal(aperture)}"


def _format_iso(value: Any) -> str:
    iso_value = _rational_to_float(value)
    if iso_value is None or iso_value <= 0:
        return NOT_AVAILABLE
    return f"ISO {int(round(iso_value))}"


def _format_focal_length(value: Any) -> str:
    focal_length = _rational_to_float(value)
    if focal_length is None or focal_length <= 0:
        return NOT_AVAILABLE
    return f"{_format_decimal(focal_length)} mm"


def _rational_to_float(value: Any) -> float | None:
    if value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    if isinstance(value, (tuple, list)) and len(value) == 2:
        numerator, denominator = value
        try:
            numerator = float(numerator)
            denominator = float(denominator)
        except (TypeError, ValueError):
            return None
        if denominator == 0:
            return None
        return numerator / denominator

    return None


def _format_decimal(value: float, precision: int = 2) -> str:
    text = f"{value:.{precision}f}"
    return text.rstrip("0").rstrip(".")
