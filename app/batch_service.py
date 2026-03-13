from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from os import cpu_count
from pathlib import Path
from threading import Event
from typing import Callable

from app.exif_service import extract_display_data
from app.image_service import create_annotated_copy
from app.overlay_config import OverlayPreset, get_builtin_presets


@dataclass(frozen=True, slots=True)
class BatchProgress:
    current: int
    total: int
    image_path: str
    error_message: str | None = None

    @property
    def image_name(self) -> str:
        return Path(self.image_path).name

    @property
    def succeeded(self) -> bool:
        return self.error_message is None


@dataclass(frozen=True, slots=True)
class BatchProcessingResult:
    processed_count: int
    failures: list[str]
    cancelled: bool = False


def process_image(
    image_path: str,
    preset: OverlayPreset | None = None,
    output_subfolder: str = "exportadas",
) -> str:
    active_preset = preset.normalized() if preset is not None else get_builtin_presets()[0]
    exif_data = extract_display_data(image_path) if active_preset.mode == "exif" else None
    return create_annotated_copy(image_path, exif_data, active_preset, output_subfolder=output_subfolder)


def process_images(
    image_paths: list[str],
    preset: OverlayPreset | None = None,
    output_subfolder: str = "exportadas",
    max_workers: int | None = None,
    progress_callback: Callable[[BatchProgress], None] | None = None,
    cancel_event: Event | None = None,
) -> BatchProcessingResult:
    if not image_paths:
        return BatchProcessingResult(processed_count=0, failures=[])

    total_images = len(image_paths)
    worker_count = _resolve_worker_count(total_images, max_workers)
    active_preset = preset.normalized() if preset is not None else get_builtin_presets()[0]
    processed_count = 0
    failures: list[str] = []
    completed_count = 0
    cancelled = False

    with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="exif-overlay") as executor:
        pending_paths = iter(image_paths)
        active_futures: dict[Future[str], str] = {}

        while len(active_futures) < worker_count:
            if _cancel_requested(cancel_event):
                cancelled = True
                break

            image_path = next(pending_paths, None)
            if image_path is None:
                break
            future = executor.submit(process_image, image_path, active_preset, output_subfolder)
            active_futures[future] = image_path

        while active_futures:
            done_futures, _ = wait(active_futures, return_when=FIRST_COMPLETED)

            for future in done_futures:
                image_path = active_futures.pop(future)
                completed_count += 1
                error_message = _resolve_future_error(image_path, future)

                if error_message is None:
                    processed_count += 1
                else:
                    failures.append(error_message)

                if progress_callback is not None:
                    progress_callback(
                        BatchProgress(
                            current=completed_count,
                            total=total_images,
                            image_path=image_path,
                            error_message=error_message,
                        )
                    )

                if _cancel_requested(cancel_event):
                    cancelled = True
                    continue

                next_path = next(pending_paths, None)
                if next_path is not None:
                    next_future = executor.submit(process_image, next_path, active_preset, output_subfolder)
                    active_futures[next_future] = next_path

            if cancelled:
                for future in list(active_futures):
                    future.cancel()
                break

    return BatchProcessingResult(
        processed_count=processed_count,
        failures=failures,
        cancelled=cancelled,
    )


def _resolve_worker_count(total_images: int, max_workers: int | None) -> int:
    if total_images <= 0:
        return 1

    if max_workers is not None:
        return max(1, min(total_images, max_workers))

    available_cpus = cpu_count() or 1
    suggested_workers = min(8, available_cpus)
    return max(1, min(total_images, suggested_workers))


def _cancel_requested(cancel_event: Event | None) -> bool:
    return cancel_event is not None and cancel_event.is_set()


def _resolve_future_error(image_path: str, future: Future[str]) -> str | None:
    try:
        future.result()
    except (FileNotFoundError, ValueError, RuntimeError, OSError) as exc:
        return f"{Path(image_path).name}: {exc}"
    except Exception as exc:
        return f"{Path(image_path).name}: error inesperado: {exc}"
    return None
