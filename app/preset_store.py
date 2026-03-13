from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from app.overlay_config import OverlayPreset, clone_preset, get_default_user_presets

STORE_VERSION = 2


@dataclass(frozen=True, slots=True)
class PresetStoreData:
    user_presets: list[OverlayPreset]
    last_selected_preset_id: str
    last_watermark_image_path: str = ""
    warning_message: str | None = None


def load_preset_store(storage_path: Path | None = None) -> PresetStoreData:
    path = storage_path or get_preset_store_path()
    default_user_presets = get_default_user_presets()
    default_selected_preset_id = "builtin_classic"

    if not path.exists():
        return PresetStoreData(default_user_presets, default_selected_preset_id)

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return PresetStoreData(
            default_user_presets,
            default_selected_preset_id,
            "",
            warning_message="No se pudieron cargar los presets guardados; se han restaurado los valores por defecto.",
        )

    user_payload = payload.get("user_presets", [])
    loaded_presets: list[OverlayPreset] = []
    default_slots = get_default_user_presets()
    for index, default_preset in enumerate(default_slots):
        if index < len(user_payload) and isinstance(user_payload[index], dict):
            loaded = OverlayPreset.from_dict(user_payload[index])
            loaded_presets.append(
                clone_preset(
                    loaded,
                    preset_id=default_preset.preset_id,
                    name=default_preset.name,
                    built_in=False,
                )
            )
        else:
            loaded_presets.append(default_preset)

    last_selected_preset_id = str(payload.get("last_selected_preset_id", default_selected_preset_id))
    last_watermark_image_path = str(payload.get("last_watermark_image_path", "")).strip()
    if not last_watermark_image_path:
        last_watermark_image_path = _resolve_legacy_watermark_image_path(loaded_presets)
    return PresetStoreData(loaded_presets, last_selected_preset_id, last_watermark_image_path)


def save_preset_store(
    user_presets: list[OverlayPreset],
    last_selected_preset_id: str,
    last_watermark_image_path: str = "",
    storage_path: Path | None = None,
) -> None:
    path = storage_path or get_preset_store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": STORE_VERSION,
        "user_presets": [_serialize_user_preset(preset) for preset in user_presets[:3]],
        "last_selected_preset_id": last_selected_preset_id,
        "last_watermark_image_path": str(last_watermark_image_path).strip(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


def get_preset_store_path() -> Path:
    appdata = os.getenv("APPDATA")
    if appdata:
        return Path(appdata) / "ExifOverlay" / "presets.json"
    return Path.home() / ".config" / "exif-overlay" / "presets.json"


def _serialize_user_preset(preset: OverlayPreset) -> dict[str, object]:
    serialized = clone_preset(preset, built_in=False).to_dict()
    watermark = serialized.get("watermark")
    if isinstance(watermark, dict):
        watermark["image_path"] = ""
    return serialized


def _resolve_legacy_watermark_image_path(user_presets: list[OverlayPreset]) -> str:
    for preset in user_presets:
        image_path = preset.watermark.image_path.strip()
        if image_path:
            return image_path
    return ""
