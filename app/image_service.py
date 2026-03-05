from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError

from app.overlay_config import FONT_FAMILY_TO_FILES, OverlayFieldConfig, OverlayPreset, get_builtin_presets

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png"}
MAX_OUTPUT_HEIGHT = 2160


def build_overlay_text(exif_data: dict[str, str], field_config: OverlayFieldConfig) -> str:
    config = field_config.normalized()
    fields: list[str] = []

    if config.show_exposure:
        fields.append(exif_data.get("exposure", "N/D"))
    if config.show_iso:
        fields.append(exif_data.get("iso", "N/D"))
    if config.show_aperture:
        fields.append(exif_data.get("aperture", "N/D"))
    if config.show_focal_length:
        fields.append(exif_data.get("focal_length", "N/D"))

    if not fields:
        return ""
    return config.separator.join(fields)


def render_overlay(
    image_path: str,
    exif_data: dict[str, str],
    preset: OverlayPreset,
    for_preview: bool = False,
) -> Image.Image:
    del for_preview

    path = Path(image_path)
    _validate_input_path(path)
    overlay_text = build_overlay_text(exif_data, preset.fields)

    try:
        with Image.open(path) as image:
            save_as_png = path.suffix.lower() == ".png"
            _configure_decoder(image, save_as_png=save_as_png)
            prepared = _prepare_image(image, save_as_png=save_as_png)
            resized = _resize_for_timeline(prepared)
            return _draw_overlay_text(resized, overlay_text, preset)
    except FileNotFoundError:
        raise
    except UnidentifiedImageError as exc:
        raise ValueError("El archivo seleccionado no es una imagen valida.") from exc
    except OSError as exc:
        raise RuntimeError(f"No se pudo procesar la imagen: {exc}") from exc


def create_annotated_copy(
    image_path: str,
    exif_data: dict[str, str],
    preset: OverlayPreset | None = None,
    output_subfolder: str = "exportadas",
) -> str:
    path = Path(image_path)
    _validate_input_path(path)
    active_preset = preset.normalized() if preset is not None else get_builtin_presets()[0]
    output_path = _get_output_path(path, output_subfolder)
    save_as_png = path.suffix.lower() == ".png"
    annotated = render_overlay(image_path, exif_data, active_preset)
    _save_image(annotated, output_path, save_as_png=save_as_png)
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


def _draw_overlay_text(base_image: Image.Image, text: str, preset: OverlayPreset) -> Image.Image:
    if not text:
        return base_image.copy()

    style = preset.style.normalized()
    canvas = base_image.convert("RGBA")
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    width, height = canvas.size
    text_box_height = _calculate_text_box_height(height)

    draw = ImageDraw.Draw(overlay)
    font = _select_font(draw, text, width, text_box_height, style)
    text_bbox = draw.textbbox((0, 0), text, font=font)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]
    text_x = max(10, (width - text_width) // 2)
    bottom_padding = max(18, int(height * style.bottom_padding_ratio))
    text_y = height - bottom_padding - text_height - text_bbox[1]

    if style.shadow.enabled and style.shadow.opacity > 0:
        shadow_fill = _hex_to_rgba(style.shadow.color, style.shadow.opacity)
        draw.text(
            (text_x + style.shadow.offset_x, text_y + style.shadow.offset_y),
            text,
            fill=shadow_fill,
            font=font,
        )

    stroke_width = style.stroke.width if style.stroke.enabled and style.stroke.opacity > 0 else 0
    draw.text(
        (text_x, text_y),
        text,
        fill=_hex_to_rgba(style.text_color, 100),
        font=font,
        stroke_width=stroke_width,
        stroke_fill=_hex_to_rgba(style.stroke.color, style.stroke.opacity) if stroke_width > 0 else None,
    )

    composited = Image.alpha_composite(canvas, overlay)
    if "A" in base_image.getbands():
        return composited
    return composited.convert(base_image.mode)


def _calculate_text_box_height(image_height: int) -> int:
    return max(80, min(220, int(image_height * 0.16)))


def _select_font(
    draw: ImageDraw.ImageDraw,
    text: str,
    width: int,
    text_box_height: int,
    style,
) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    if style.font_size_mode == "manual":
        font_size = style.font_size
    else:
        font_size = min(72, max(20, text_box_height // 3))

    while font_size >= 12:
        font = _load_font(style.font_family, font_size)
        bbox = draw.textbbox((0, 0), text, font=font)
        if (bbox[2] - bbox[0]) <= width - 40 or font_size == 12:
            return font
        font_size -= 2

    return ImageFont.load_default()


def _load_font(font_family: str, size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    font_files = FONT_FAMILY_TO_FILES.get(font_family, FONT_FAMILY_TO_FILES["Arial"])
    for font_name in font_files:
        try:
            return ImageFont.truetype(font_name, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _hex_to_rgba(color: str, opacity_percent: int) -> tuple[int, int, int, int]:
    normalized = color.strip().lstrip("#")
    red = int(normalized[0:2], 16)
    green = int(normalized[2:4], 16)
    blue = int(normalized[4:6], 16)
    alpha = max(0, min(255, int(round((opacity_percent / 100) * 255))))
    return (red, green, blue, alpha)


def _save_image(image: Image.Image, output_path: Path, save_as_png: bool) -> None:
    if save_as_png:
        image.save(output_path, format="PNG")
        return

    image.convert("RGB").save(output_path, format="JPEG", quality=95)
