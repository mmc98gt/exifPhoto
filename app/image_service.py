from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png"}
MAX_OUTPUT_HEIGHT = 2160
TEXT_COLOR = (255, 220, 90)
STROKE_COLOR = (20, 20, 20)
SHADOW_COLOR = (0, 0, 0, 140)


def create_annotated_copy(
    image_path: str,
    exif_data: dict[str, str],
    output_subfolder: str = "exportadas",
) -> str:
    path = Path(image_path)
    _validate_input_path(path)

    overlay_text = _build_overlay_text(exif_data)
    output_path = _get_output_path(path, output_subfolder)

    try:
        with Image.open(path) as image:
            save_as_png = path.suffix.lower() == ".png"
            _configure_decoder(image, save_as_png=save_as_png)
            prepared = _prepare_image(image, save_as_png=save_as_png)
            resized = _resize_for_timeline(prepared)
            annotated = _draw_overlay_text(resized, overlay_text)
            _save_image(annotated, output_path, save_as_png=save_as_png)
    except FileNotFoundError:
        raise
    except UnidentifiedImageError as exc:
        raise ValueError("El archivo seleccionado no es una imagen valida.") from exc
    except OSError as exc:
        raise RuntimeError(f"No se pudo procesar la imagen: {exc}") from exc

    return str(output_path.resolve())


def _validate_input_path(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"No se encontro el archivo: {path}")
    if not path.is_file():
        raise ValueError(f"La ruta seleccionada no es un archivo valido: {path}")
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ValueError("Formato no soportado. Usa archivos JPG, JPEG o PNG.")


def _prepare_image(image: Image.Image, save_as_png: bool) -> Image.Image:
    if save_as_png:
        return image.convert("RGBA") if image.mode != "RGBA" else image.copy()
    return image.convert("RGB")


def _configure_decoder(image: Image.Image, save_as_png: bool) -> None:
    if save_as_png or image.height <= MAX_OUTPUT_HEIGHT:
        return

    target_width = max(1, int(image.width * (MAX_OUTPUT_HEIGHT / image.height)))
    image.draft("RGB", (target_width, MAX_OUTPUT_HEIGHT))


def _build_overlay_text(exif_data: dict[str, str]) -> str:
    exposure = exif_data.get("exposure", "N/D")
    iso = exif_data.get("iso", "N/D")
    aperture = exif_data.get("aperture", "N/D")
    focal_length = exif_data.get("focal_length", "N/D")
    return f"{exposure}  |  {iso}  |  {aperture}  |  {focal_length}"


def _resize_for_timeline(image: Image.Image) -> Image.Image:
    width, height = image.size
    if height <= MAX_OUTPUT_HEIGHT:
        return image

    scale = MAX_OUTPUT_HEIGHT / height
    resized_width = max(1, int(width * scale))
    return image.resize((resized_width, MAX_OUTPUT_HEIGHT), Image.Resampling.LANCZOS)


def _get_output_path(image_path: Path, output_subfolder: str) -> Path:
    output_dir = image_path.parent / output_subfolder
    output_dir.mkdir(parents=True, exist_ok=True)

    extension = ".png" if image_path.suffix.lower() == ".png" else ".jpg"
    base_name = f"{image_path.stem}_exif"
    candidate = output_dir / f"{base_name}{extension}"

    counter = 1
    while candidate.exists():
        candidate = output_dir / f"{base_name}_{counter}{extension}"
        counter += 1

    return candidate


def _draw_overlay_text(base_image: Image.Image, text: str) -> Image.Image:
    canvas = base_image.copy()
    width, height = canvas.size
    text_box_height = _calculate_text_box_height(height)

    draw = ImageDraw.Draw(canvas)
    font = _select_font(draw, text, width, text_box_height)
    text_bbox = draw.textbbox((0, 0), text, font=font)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]
    text_x = max(10, (width - text_width) // 2)
    bottom_padding = max(18, int(height * 0.04))
    text_y = height - bottom_padding - text_height - text_bbox[1]
    shadow_x = text_x + 3
    shadow_y = text_y + 3

    if "A" in canvas.getbands():
        shadow_fill = SHADOW_COLOR
    else:
        shadow_fill = SHADOW_COLOR[:3]

    draw.text((shadow_x, shadow_y), text, fill=shadow_fill, font=font)
    draw.text(
        (text_x, text_y),
        text,
        fill=TEXT_COLOR,
        font=font,
        stroke_width=max(2, font.size // 18) if hasattr(font, "size") else 2,
        stroke_fill=STROKE_COLOR,
    )

    return canvas


def _calculate_text_box_height(image_height: int) -> int:
    return max(80, min(220, int(image_height * 0.16)))


def _select_font(
    draw: ImageDraw.ImageDraw,
    text: str,
    width: int,
    text_box_height: int,
) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    font_size = min(72, max(20, text_box_height // 3))

    while font_size >= 12:
        font = _load_font(font_size)
        bbox = draw.textbbox((0, 0), text, font=font)
        if (bbox[2] - bbox[0]) <= width - 40 or font_size == 12:
            return font
        font_size -= 2

    return ImageFont.load_default()


def _load_font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    for font_name in ("arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"):
        try:
            return ImageFont.truetype(font_name, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _save_image(image: Image.Image, output_path: Path, save_as_png: bool) -> None:
    if save_as_png:
        image.save(output_path, format="PNG")
        return

    image.convert("RGB").save(output_path, format="JPEG", quality=95)
