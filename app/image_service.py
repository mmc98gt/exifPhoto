from __future__ import annotations

from pathlib import Path
import re

from PIL import Image, ImageDraw, ImageFont, PngImagePlugin, UnidentifiedImageError

from app.overlay_config import FONT_FAMILY_TO_FILES, OverlayFieldConfig, OverlayPreset, OverlayStyle, WatermarkConfig, get_builtin_presets

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png"}
MAX_OUTPUT_HEIGHT = 2160
PHOTO_NUMBER_REGEX = re.compile(r"(\d+)(?!.*\d)")


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
    exif_data: dict[str, str] | None,
    preset: OverlayPreset,
    for_preview: bool = False,
) -> Image.Image:
    del for_preview

    path = Path(image_path)
    _validate_input_path(path)
    active_preset = preset.normalized()

    try:
        with Image.open(path) as image:
            save_as_png = path.suffix.lower() == ".png"
            _configure_decoder(image, save_as_png=save_as_png)
            prepared = _prepare_image(image, save_as_png=save_as_png)
            resized = _resize_for_timeline(prepared)
            return _render_prepared_image(resized, exif_data or {}, active_preset, path)
    except FileNotFoundError:
        raise
    except UnidentifiedImageError as exc:
        raise ValueError("El archivo seleccionado no es una imagen valida.") from exc
    except OSError as exc:
        raise RuntimeError(f"No se pudo procesar la imagen: {exc}") from exc


def create_annotated_copy(
    image_path: str,
    exif_data: dict[str, str] | None,
    preset: OverlayPreset | None = None,
    output_subfolder: str = "exportadas",
) -> str:
    path = Path(image_path)
    _validate_input_path(path)
    active_preset = preset.normalized() if preset is not None else get_builtin_presets()[0]
    output_path = _get_output_path(path, output_subfolder, active_preset.mode)
    save_as_png = path.suffix.lower() == ".png"
    annotated = render_overlay(image_path, exif_data, active_preset)
    source_metadata = _extract_source_metadata(path, save_as_png=save_as_png)
    _save_image(annotated, output_path, save_as_png=save_as_png, metadata=source_metadata)
    return str(output_path.resolve())


def _render_prepared_image(base_image: Image.Image, exif_data: dict[str, str], preset: OverlayPreset, image_path: Path) -> Image.Image:
    if preset.mode == "watermark":
        return _draw_watermark(base_image, preset, image_path)

    overlay_text = build_overlay_text(exif_data, preset.fields)
    return _draw_overlay_text(base_image, overlay_text, preset.style)


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


def _get_output_path(image_path: Path, output_subfolder: str, mode: str) -> Path:
    output_dir = _get_output_dir(image_path, output_subfolder)
    output_dir.mkdir(parents=True, exist_ok=True)

    extension = ".png" if image_path.suffix.lower() == ".png" else ".jpg"
    suffix = "_watermark" if mode == "watermark" else "_exif"
    base_name = f"{image_path.stem}{suffix}"
    candidate = output_dir / f"{base_name}{extension}"

    counter = 1
    while candidate.exists():
        candidate = output_dir / f"{base_name}_{counter}{extension}"
        counter += 1

    return candidate


def _get_output_dir(image_path: Path, output_subfolder: str) -> Path:
    source_dir = image_path.parent
    folder_name = _build_export_folder_name(source_dir, output_subfolder)
    parent_dir = source_dir.parent if source_dir.parent != source_dir else source_dir
    return parent_dir / folder_name


def _build_export_folder_name(source_dir: Path, output_subfolder: str) -> str:
    base_name = source_dir.name.strip() or "imagenes"
    suffix = output_subfolder.strip()
    if not suffix:
        return f"{base_name}_exportadas"
    if suffix.startswith("_"):
        return f"{base_name}{suffix}"
    return f"{base_name}_{suffix}"


def _draw_overlay_text(base_image: Image.Image, text: str, style: OverlayStyle) -> Image.Image:
    if not text:
        return base_image.copy()

    normalized_style = style.normalized()
    canvas = base_image.convert("RGBA")
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    width, height = canvas.size
    text_box_height = _calculate_text_box_height(height)

    draw = ImageDraw.Draw(overlay)
    font = _select_font(draw, text, width, text_box_height, normalized_style)
    text_bbox = draw.textbbox((0, 0), text, font=font)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]
    text_x, text_y = _resolve_text_position(width, height, text_width, text_height, text_bbox, normalized_style)

    _draw_text_with_effects(draw, text, text_x, text_y, font, normalized_style, overall_opacity=100)

    composited = Image.alpha_composite(canvas, overlay)
    if "A" in base_image.getbands():
        return composited
    return composited.convert(base_image.mode)


def _draw_watermark(base_image: Image.Image, preset: OverlayPreset, image_path: Path) -> Image.Image:
    watermark = preset.watermark.normalized()
    detected_number = _extract_photo_number(image_path) if watermark.show_detected_number else ""
    if watermark.source_type == "image":
        return _draw_image_watermark(base_image, watermark, preset.style, detected_number)
    return _draw_text_watermark(base_image, watermark, preset.style, detected_number)


def _draw_text_watermark(base_image: Image.Image, watermark: WatermarkConfig, style: OverlayStyle, detected_number: str) -> Image.Image:
    if not watermark.text:
        return base_image.copy()

    normalized_style = style.normalized()
    canvas = base_image.convert("RGBA")
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    width, height = canvas.size
    margin = max(18, int(min(width, height) * watermark.margin_ratio))
    max_text_width = max(80, width - (margin * 2))
    text_box_height = max(60, min(240, int(height * 0.18)))
    style_for_watermark = OverlayStyle(
        font_family=normalized_style.font_family,
        font_size_mode=normalized_style.font_size_mode,
        font_size=normalized_style.font_size,
        text_color=normalized_style.text_color,
        position=watermark.position,
        bottom_padding_ratio=watermark.margin_ratio,
        side_padding_ratio=watermark.margin_ratio,
        vertical_offset=watermark.vertical_offset,
        shadow=normalized_style.shadow,
        stroke=normalized_style.stroke,
    ).normalized()

    font = _select_font(draw, watermark.text, max_text_width, text_box_height, style_for_watermark)
    text_bbox = draw.textbbox((0, 0), watermark.text, font=font)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]
    number_layout = _build_detected_number_layout(draw, detected_number, text_width, text_box_height, style_for_watermark)
    group_width = max(text_width, number_layout["width"])
    group_height = text_height + number_layout["gap"] + number_layout["height"]
    group_x, group_y = _resolve_box_position(
        width,
        height,
        group_width,
        group_height,
        watermark.position,
        margin,
        watermark.vertical_offset,
    )
    text_x = group_x + (group_width - text_width) // 2 - text_bbox[0]
    text_y = group_y - text_bbox[1]

    _draw_text_with_effects(draw, watermark.text, text_x, text_y, font, style_for_watermark, overall_opacity=watermark.opacity)
    _draw_detected_number(
        draw,
        number_layout=number_layout,
        style=style_for_watermark,
        overall_opacity=watermark.opacity,
        group_x=group_x,
        primary_height=text_height,
        group_width=group_width,
        base_y=group_y,
    )

    composited = Image.alpha_composite(canvas, overlay)
    if "A" in base_image.getbands():
        return composited
    return composited.convert(base_image.mode)


def _draw_image_watermark(base_image: Image.Image, watermark: WatermarkConfig, style: OverlayStyle, detected_number: str) -> Image.Image:
    if not watermark.image_path:
        return base_image.copy()

    watermark_path = Path(watermark.image_path)
    if not watermark_path.exists() or not watermark_path.is_file():
        raise ValueError(f"No se encontro la imagen de marca de agua: {watermark.image_path}")

    canvas = base_image.convert("RGBA")
    width, height = canvas.size
    margin = max(18, int(min(width, height) * watermark.margin_ratio))

    try:
        with Image.open(watermark_path) as watermark_image:
            watermark_rgba = watermark_image.convert("RGBA")
    except UnidentifiedImageError as exc:
        raise ValueError("La imagen usada como marca de agua no es valida.") from exc
    except OSError as exc:
        raise RuntimeError(f"No se pudo abrir la imagen de la marca de agua: {exc}") from exc

    target_width = max(1, int(width * (watermark.scale_percent / 100)))
    scale = target_width / max(1, watermark_rgba.width)
    target_height = max(1, int(watermark_rgba.height * scale))
    resized = watermark_rgba.resize((target_width, target_height), Image.Resampling.LANCZOS)

    if watermark.opacity < 100:
        alpha = resized.getchannel("A")
        alpha = alpha.point(lambda value: int(value * (watermark.opacity / 100)))
        resized.putalpha(alpha)

    normalized_style = style.normalized()
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    number_layout = _build_detected_number_layout(draw, detected_number, resized.width, resized.height, normalized_style)
    group_width = max(resized.width, number_layout["width"])
    group_height = resized.height + number_layout["gap"] + number_layout["height"]
    group_x, group_y = _resolve_box_position(
        width,
        height,
        group_width,
        group_height,
        watermark.position,
        margin,
        watermark.vertical_offset,
    )
    paste_x = group_x + (group_width - resized.width) // 2
    paste_y = group_y
    overlay.alpha_composite(resized, dest=(paste_x, paste_y))
    _draw_detected_number(
        draw,
        number_layout=number_layout,
        style=normalized_style,
        overall_opacity=watermark.opacity,
        group_x=group_x,
        primary_height=resized.height,
        group_width=group_width,
        base_y=group_y,
    )

    composited = Image.alpha_composite(canvas, overlay)
    if "A" in base_image.getbands():
        return composited
    return composited.convert(base_image.mode)


def _build_detected_number_layout(
    draw: ImageDraw.ImageDraw,
    detected_number: str,
    primary_width: int,
    primary_height: int,
    style: OverlayStyle,
) -> dict[str, object]:
    if not detected_number:
        return {
            "text": "",
            "font": None,
            "bbox": (0, 0, 0, 0),
            "width": 0,
            "height": 0,
            "gap": 0,
        }

    number_style = OverlayStyle(
        font_family=style.font_family,
        font_size_mode="manual",
        font_size=max(12, int(round(max(style.font_size, primary_height * 0.45) * 0.55))),
        text_color=style.text_color,
        position=style.position,
        bottom_padding_ratio=style.bottom_padding_ratio,
        side_padding_ratio=style.side_padding_ratio,
        vertical_offset=0,
        shadow=style.shadow,
        stroke=style.stroke,
    ).normalized()
    font = _select_font(draw, detected_number, max(primary_width, 80), max(28, int(primary_height * 0.4)), number_style)
    bbox = draw.textbbox((0, 0), detected_number, font=font)
    return {
        "text": detected_number,
        "font": font,
        "bbox": bbox,
        "width": bbox[2] - bbox[0],
        "height": bbox[3] - bbox[1],
        "gap": max(4, int(primary_height * 0.12)),
    }


def _draw_detected_number(
    draw: ImageDraw.ImageDraw,
    *,
    number_layout: dict[str, object],
    style: OverlayStyle,
    overall_opacity: int,
    group_x: int,
    primary_height: int,
    group_width: int,
    base_y: int,
) -> None:
    detected_number = str(number_layout["text"])
    font = number_layout["font"]
    if not detected_number or font is None:
        return

    bbox = number_layout["bbox"]
    number_width = int(number_layout["width"])
    gap = int(number_layout["gap"])
    number_x = group_x + (group_width - number_width) // 2 - int(bbox[0])
    number_y = base_y + primary_height + gap - int(bbox[1])
    _draw_text_with_effects(draw, detected_number, number_x, number_y, font, style, overall_opacity=overall_opacity)


def _extract_photo_number(image_path: Path) -> str:
    match = PHOTO_NUMBER_REGEX.search(image_path.stem)
    return match.group(1) if match is not None else ""


def _draw_text_with_effects(
    draw: ImageDraw.ImageDraw,
    text: str,
    x: int,
    y: int,
    font: ImageFont.ImageFont | ImageFont.FreeTypeFont,
    style: OverlayStyle,
    overall_opacity: int,
) -> None:
    if style.shadow.enabled and style.shadow.opacity > 0 and overall_opacity > 0:
        shadow_fill = _hex_to_rgba(style.shadow.color, _combine_opacity(style.shadow.opacity, overall_opacity))
        draw.text(
            (x + style.shadow.offset_x, y + style.shadow.offset_y),
            text,
            fill=shadow_fill,
            font=font,
        )

    stroke_width = style.stroke.width if style.stroke.enabled and style.stroke.opacity > 0 and overall_opacity > 0 else 0
    draw.text(
        (x, y),
        text,
        fill=_hex_to_rgba(style.text_color, overall_opacity),
        font=font,
        stroke_width=stroke_width,
        stroke_fill=_hex_to_rgba(style.stroke.color, _combine_opacity(style.stroke.opacity, overall_opacity)) if stroke_width > 0 else None,
    )


def _calculate_text_box_height(image_height: int) -> int:
    return max(80, min(220, int(image_height * 0.16)))


def _select_font(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    text_box_height: int,
    style: OverlayStyle,
) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    if style.font_size_mode == "manual":
        font_size = style.font_size
    else:
        font_size = min(72, max(20, text_box_height // 3))

    while font_size >= 12:
        font = _load_font(style.font_family, font_size)
        bbox = draw.textbbox((0, 0), text, font=font)
        if (bbox[2] - bbox[0]) <= max_width or font_size == 12:
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


def _resolve_text_position(
    width: int,
    height: int,
    text_width: int,
    text_height: int,
    text_bbox: tuple[int, int, int, int],
    style: OverlayStyle,
) -> tuple[int, int]:
    margin_x = max(18, int(width * style.side_padding_ratio))
    margin_y = max(18, int(height * style.bottom_padding_ratio))
    return _resolve_position(
        width=width,
        height=height,
        box_width=text_width,
        box_height=text_height,
        bbox_left=text_bbox[0],
        bbox_top=text_bbox[1],
        position=style.position,
        margin_x=margin_x,
        margin_y=margin_y,
        vertical_offset=style.vertical_offset,
    )


def _resolve_box_position(
    width: int,
    height: int,
    box_width: int,
    box_height: int,
    position: str,
    margin: int,
    vertical_offset: int,
) -> tuple[int, int]:
    x, y = _resolve_position(
        width=width,
        height=height,
        box_width=box_width,
        box_height=box_height,
        bbox_left=0,
        bbox_top=0,
        position=position,
        margin_x=margin,
        margin_y=margin,
        vertical_offset=vertical_offset,
    )
    return (max(0, x), max(0, y))


def _resolve_position(
    *,
    width: int,
    height: int,
    box_width: int,
    box_height: int,
    bbox_left: int,
    bbox_top: int,
    position: str,
    margin_x: int,
    margin_y: int,
    vertical_offset: int,
) -> tuple[int, int]:
    if position == "bottom_left":
        return (margin_x - bbox_left, height - margin_y - box_height - bbox_top + vertical_offset)
    if position == "bottom_right":
        return (width - margin_x - box_width - bbox_left, height - margin_y - box_height - bbox_top + vertical_offset)
    if position == "top_left":
        return (margin_x - bbox_left, margin_y - bbox_top + vertical_offset)
    if position == "top_right":
        return (width - margin_x - box_width - bbox_left, margin_y - bbox_top + vertical_offset)
    if position == "center":
        return ((width - box_width) // 2 - bbox_left, (height - box_height) // 2 - bbox_top + vertical_offset)
    return ((width - box_width) // 2 - bbox_left, height - margin_y - box_height - bbox_top + vertical_offset)


def _combine_opacity(base_opacity: int, overall_opacity: int) -> int:
    return max(0, min(100, int(round((base_opacity * overall_opacity) / 100))))


def _hex_to_rgba(color: str, opacity_percent: int) -> tuple[int, int, int, int]:
    normalized = color.strip().lstrip("#")
    red = int(normalized[0:2], 16)
    green = int(normalized[2:4], 16)
    blue = int(normalized[4:6], 16)
    alpha = max(0, min(255, int(round((opacity_percent / 100) * 255))))
    return (red, green, blue, alpha)


def _extract_source_metadata(image_path: Path, save_as_png: bool) -> dict[str, object]:
    try:
        with Image.open(image_path) as source_image:
            if save_as_png:
                return _extract_png_metadata(source_image)
            return _extract_jpeg_metadata(source_image)
    except (FileNotFoundError, UnidentifiedImageError, OSError):
        return {}


def _extract_jpeg_metadata(source_image: Image.Image) -> dict[str, object]:
    save_kwargs: dict[str, object] = {}
    info = source_image.info

    if info.get("exif"):
        save_kwargs["exif"] = info["exif"]
    if info.get("icc_profile"):
        save_kwargs["icc_profile"] = info["icc_profile"]
    if info.get("dpi"):
        save_kwargs["dpi"] = info["dpi"]
    if info.get("xmp"):
        save_kwargs["xmp"] = info["xmp"]
    if info.get("comment"):
        save_kwargs["comment"] = info["comment"]

    return save_kwargs


def _extract_png_metadata(source_image: Image.Image) -> dict[str, object]:
    save_kwargs: dict[str, object] = {}
    info = source_image.info
    pnginfo = PngImagePlugin.PngInfo()
    has_png_text = False

    text_chunks = getattr(source_image, "text", {}) or {}
    for key, value in text_chunks.items():
        if not isinstance(key, str):
            continue
        if isinstance(value, str):
            pnginfo.add_text(key, value)
            has_png_text = True

    for key, value in info.items():
        if key in {"dpi", "gamma", "transparency", "icc_profile", "exif"}:
            continue
        if not isinstance(key, str):
            continue
        if isinstance(value, str) and key not in text_chunks:
            pnginfo.add_text(key, value)
            has_png_text = True

    if has_png_text:
        save_kwargs["pnginfo"] = pnginfo
    if info.get("icc_profile"):
        save_kwargs["icc_profile"] = info["icc_profile"]
    if info.get("dpi"):
        save_kwargs["dpi"] = info["dpi"]
    if info.get("gamma") is not None:
        save_kwargs["gamma"] = info["gamma"]
    if info.get("transparency") is not None:
        save_kwargs["transparency"] = info["transparency"]
    if info.get("exif"):
        save_kwargs["exif"] = info["exif"]

    return save_kwargs


def _save_image(image: Image.Image, output_path: Path, save_as_png: bool, metadata: dict[str, object]) -> None:
    if save_as_png:
        image.save(output_path, format="PNG", **metadata)
        return

    image.convert("RGB").save(output_path, format="JPEG", quality=95, **metadata)
