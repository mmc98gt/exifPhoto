from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from typing import Any

FONT_FAMILY_TO_FILES = {
    "Arial": ("arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"),
    "DejaVu Sans": ("DejaVuSans.ttf", "LiberationSans-Regular.ttf", "arial.ttf"),
    "Liberation Sans": ("LiberationSans-Regular.ttf", "DejaVuSans.ttf", "arial.ttf"),
}
FONT_FAMILIES = tuple(FONT_FAMILY_TO_FILES)
MIN_FONT_SIZE = 12
MAX_FONT_SIZE = 160
DEFAULT_SEPARATOR = "  |  "
OVERLAY_MODES = ("exif", "watermark")
WATERMARK_SOURCE_TYPES = ("text", "image")
OVERLAY_POSITIONS = (
    "bottom_center",
    "bottom_left",
    "bottom_right",
    "top_left",
    "top_right",
    "center",
)


@dataclass(frozen=True, slots=True)
class OverlayFieldConfig:
    show_exposure: bool = True
    show_iso: bool = True
    show_aperture: bool = True
    show_focal_length: bool = True
    separator: str = DEFAULT_SEPARATOR

    def normalized(self) -> OverlayFieldConfig:
        separator = self.separator if self.separator else DEFAULT_SEPARATOR
        return replace(
            self,
            show_exposure=bool(self.show_exposure),
            show_iso=bool(self.show_iso),
            show_aperture=bool(self.show_aperture),
            show_focal_length=bool(self.show_focal_length),
            separator=separator,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self.normalized())

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> OverlayFieldConfig:
        payload = data or {}
        return cls(
            show_exposure=bool(payload.get("show_exposure", True)),
            show_iso=bool(payload.get("show_iso", True)),
            show_aperture=bool(payload.get("show_aperture", True)),
            show_focal_length=bool(payload.get("show_focal_length", True)),
            separator=str(payload.get("separator", DEFAULT_SEPARATOR)),
        ).normalized()


@dataclass(frozen=True, slots=True)
class ShadowStyle:
    enabled: bool = True
    color: str = "#000000"
    opacity: int = 55
    offset_x: int = 3
    offset_y: int = 3

    def normalized(self) -> ShadowStyle:
        return replace(
            self,
            enabled=bool(self.enabled),
            color=_normalize_hex_color(self.color, "#000000"),
            opacity=_clamp_int(self.opacity, 0, 100),
            offset_x=_clamp_int(self.offset_x, -20, 20),
            offset_y=_clamp_int(self.offset_y, -20, 20),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self.normalized())

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ShadowStyle:
        payload = data or {}
        return cls(
            enabled=bool(payload.get("enabled", True)),
            color=str(payload.get("color", "#000000")),
            opacity=int(payload.get("opacity", 55)),
            offset_x=int(payload.get("offset_x", 3)),
            offset_y=int(payload.get("offset_y", 3)),
        ).normalized()


@dataclass(frozen=True, slots=True)
class StrokeStyle:
    enabled: bool = True
    color: str = "#141414"
    opacity: int = 100
    width: int = 2

    def normalized(self) -> StrokeStyle:
        return replace(
            self,
            enabled=bool(self.enabled),
            color=_normalize_hex_color(self.color, "#141414"),
            opacity=_clamp_int(self.opacity, 0, 100),
            width=_clamp_int(self.width, 0, 12),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self.normalized())

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> StrokeStyle:
        payload = data or {}
        return cls(
            enabled=bool(payload.get("enabled", True)),
            color=str(payload.get("color", "#141414")),
            opacity=int(payload.get("opacity", 100)),
            width=int(payload.get("width", 2)),
        ).normalized()


@dataclass(frozen=True, slots=True)
class OverlayStyle:
    font_family: str = "Arial"
    font_size_mode: str = "auto"
    font_size: int = 36
    text_color: str = "#ffdc5a"
    position: str = "bottom_center"
    bottom_padding_ratio: float = 0.04
    side_padding_ratio: float = 0.04
    vertical_offset: int = 0
    shadow: ShadowStyle = field(default_factory=ShadowStyle)
    stroke: StrokeStyle = field(default_factory=StrokeStyle)

    def normalized(self) -> OverlayStyle:
        font_family = self.font_family if self.font_family in FONT_FAMILIES else "Arial"
        font_size_mode = self.font_size_mode if self.font_size_mode in {"auto", "manual"} else "auto"
        position = self.position if self.position in OVERLAY_POSITIONS else "bottom_center"
        bottom_padding_ratio = min(max(float(self.bottom_padding_ratio), 0.0), 0.3)
        side_padding_ratio = min(max(float(self.side_padding_ratio), 0.0), 0.3)
        return replace(
            self,
            font_family=font_family,
            font_size_mode=font_size_mode,
            font_size=_clamp_int(self.font_size, MIN_FONT_SIZE, MAX_FONT_SIZE),
            text_color=_normalize_hex_color(self.text_color, "#ffdc5a"),
            position=position,
            bottom_padding_ratio=bottom_padding_ratio,
            side_padding_ratio=side_padding_ratio,
            vertical_offset=_clamp_int(self.vertical_offset, -400, 400),
            shadow=self.shadow.normalized(),
            stroke=self.stroke.normalized(),
        )

    def to_dict(self) -> dict[str, Any]:
        style = self.normalized()
        return {
            "font_family": style.font_family,
            "font_size_mode": style.font_size_mode,
            "font_size": style.font_size,
            "text_color": style.text_color,
            "position": style.position,
            "bottom_padding_ratio": style.bottom_padding_ratio,
            "side_padding_ratio": style.side_padding_ratio,
            "vertical_offset": style.vertical_offset,
            "shadow": style.shadow.to_dict(),
            "stroke": style.stroke.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> OverlayStyle:
        payload = data or {}
        return cls(
            font_family=str(payload.get("font_family", "Arial")),
            font_size_mode=str(payload.get("font_size_mode", "auto")),
            font_size=int(payload.get("font_size", 36)),
            text_color=str(payload.get("text_color", "#ffdc5a")),
            position=str(payload.get("position", "bottom_center")),
            bottom_padding_ratio=float(payload.get("bottom_padding_ratio", 0.04)),
            side_padding_ratio=float(payload.get("side_padding_ratio", payload.get("bottom_padding_ratio", 0.04))),
            vertical_offset=int(payload.get("vertical_offset", 0)),
            shadow=ShadowStyle.from_dict(_safe_mapping(payload.get("shadow"))),
            stroke=StrokeStyle.from_dict(_safe_mapping(payload.get("stroke"))),
        ).normalized()


@dataclass(frozen=True, slots=True)
class WatermarkConfig:
    source_type: str = "text"
    text: str = "Marca de agua"
    image_path: str = ""
    show_detected_number: bool = False
    opacity: int = 45
    scale_percent: int = 18
    position: str = "bottom_right"
    margin_ratio: float = 0.04
    vertical_offset: int = 0

    def normalized(self) -> WatermarkConfig:
        source_type = self.source_type if self.source_type in WATERMARK_SOURCE_TYPES else "text"
        position = self.position if self.position in OVERLAY_POSITIONS else "bottom_right"
        text = str(self.text).strip()
        image_path = str(self.image_path).strip()
        return replace(
            self,
            source_type=source_type,
            text=text,
            image_path=image_path,
            show_detected_number=bool(self.show_detected_number),
            opacity=_clamp_int(self.opacity, 0, 100),
            scale_percent=_clamp_int(self.scale_percent, 5, 60),
            position=position,
            margin_ratio=min(max(float(self.margin_ratio), 0.0), 0.3),
            vertical_offset=_clamp_int(self.vertical_offset, -400, 400),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self.normalized())

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> WatermarkConfig:
        payload = data or {}
        return cls(
            source_type=str(payload.get("source_type", "text")),
            text=str(payload.get("text", "Marca de agua")),
            image_path=str(payload.get("image_path", "")),
            show_detected_number=bool(payload.get("show_detected_number", False)),
            opacity=int(payload.get("opacity", 45)),
            scale_percent=int(payload.get("scale_percent", 18)),
            position=str(payload.get("position", "bottom_right")),
            margin_ratio=float(payload.get("margin_ratio", 0.04)),
            vertical_offset=int(payload.get("vertical_offset", 0)),
        ).normalized()


@dataclass(frozen=True, slots=True)
class OverlayPreset:
    preset_id: str
    name: str
    built_in: bool
    mode: str = "exif"
    fields: OverlayFieldConfig = field(default_factory=OverlayFieldConfig)
    style: OverlayStyle = field(default_factory=OverlayStyle)
    watermark: WatermarkConfig = field(default_factory=WatermarkConfig)

    def normalized(self) -> OverlayPreset:
        mode = self.mode if self.mode in OVERLAY_MODES else "exif"
        return replace(
            self,
            preset_id=str(self.preset_id),
            name=str(self.name),
            built_in=bool(self.built_in),
            mode=mode,
            fields=self.fields.normalized(),
            style=self.style.normalized(),
            watermark=self.watermark.normalized(),
        )

    def to_dict(self) -> dict[str, Any]:
        preset = self.normalized()
        return {
            "preset_id": preset.preset_id,
            "name": preset.name,
            "built_in": preset.built_in,
            "mode": preset.mode,
            "fields": preset.fields.to_dict(),
            "style": preset.style.to_dict(),
            "watermark": preset.watermark.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OverlayPreset:
        payload = data or {}
        return cls(
            preset_id=str(payload.get("preset_id", "")),
            name=str(payload.get("name", "")),
            built_in=bool(payload.get("built_in", False)),
            mode=str(payload.get("mode", "exif")),
            fields=OverlayFieldConfig.from_dict(_safe_mapping(payload.get("fields"))),
            style=OverlayStyle.from_dict(_safe_mapping(payload.get("style"))),
            watermark=WatermarkConfig.from_dict(_safe_mapping(payload.get("watermark"))),
        ).normalized()


@dataclass(frozen=True, slots=True)
class OverlaySettingsState:
    selected_preset_id: str
    draft_preset: OverlayPreset


def get_builtin_presets() -> list[OverlayPreset]:
    return [
        OverlayPreset(
            preset_id="builtin_classic",
            name="Clasico EXIF",
            built_in=True,
            mode="exif",
            fields=OverlayFieldConfig(separator="  |  "),
            style=OverlayStyle(
                font_family="Arial",
                font_size_mode="auto",
                font_size=36,
                text_color="#ffdc5a",
                position="bottom_center",
                shadow=ShadowStyle(enabled=True, color="#000000", opacity=55, offset_x=3, offset_y=3),
                stroke=StrokeStyle(enabled=True, color="#141414", opacity=100, width=2),
            ),
            watermark=WatermarkConfig(
                source_type="text",
                text="Marca de agua",
                opacity=45,
                scale_percent=18,
                position="bottom_right",
                margin_ratio=0.04,
                vertical_offset=0,
            ),
        ),
        OverlayPreset(
            preset_id="builtin_clean",
            name="Blanco limpio",
            built_in=True,
            mode="exif",
            fields=OverlayFieldConfig(separator="  |  "),
            style=OverlayStyle(
                font_family="Arial",
                font_size_mode="auto",
                font_size=36,
                text_color="#ffffff",
                position="bottom_center",
                shadow=ShadowStyle(enabled=True, color="#000000", opacity=40, offset_x=2, offset_y=2),
                stroke=StrokeStyle(enabled=True, color="#000000", opacity=70, width=2),
            ),
        ),
        OverlayPreset(
            preset_id="builtin_cinema",
            name="Cine discreto",
            built_in=True,
            mode="exif",
            fields=OverlayFieldConfig(separator=" · "),
            style=OverlayStyle(
                font_family="Arial",
                font_size_mode="auto",
                font_size=36,
                text_color="#f2ede3",
                position="bottom_center",
                shadow=ShadowStyle(enabled=True, color="#000000", opacity=70, offset_x=4, offset_y=4),
                stroke=StrokeStyle(enabled=False, color="#141414", opacity=100, width=0),
            ),
        ),
    ]


def get_default_user_presets() -> list[OverlayPreset]:
    base = get_builtin_presets()[0]
    return [
        replace(base, preset_id="user_1", name="Usuario 1", built_in=False),
        replace(base, preset_id="user_2", name="Usuario 2", built_in=False),
        replace(base, preset_id="user_3", name="Usuario 3", built_in=False),
    ]


def clone_preset(preset: OverlayPreset, *, preset_id: str | None = None, name: str | None = None, built_in: bool | None = None) -> OverlayPreset:
    return replace(
        preset.normalized(),
        preset_id=preset.preset_id if preset_id is None else preset_id,
        name=preset.name if name is None else name,
        built_in=preset.built_in if built_in is None else built_in,
    )


def _normalize_hex_color(value: str, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback

    text = value.strip()
    if len(text) == 7 and text.startswith("#"):
        try:
            int(text[1:], 16)
        except ValueError:
            return fallback
        return text.lower()
    return fallback


def _clamp_int(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, int(value)))


def _safe_mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
