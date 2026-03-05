from __future__ import annotations

from pathlib import Path
from queue import Empty, Queue
from threading import Event, Thread
import tkinter as tk
from tkinter import filedialog, ttk

from app.batch_service import BatchProcessingResult, BatchProgress, process_images as process_images_batch

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png"}


class ExifOverlayApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("EXIF Overlay")
        self.root.geometry("760x320")
        self.root.minsize(760, 320)
        self.root.protocol("WM_DELETE_WINDOW", self._handle_close_request)

        self.selected_paths: list[str] = []
        self.selection_var = tk.StringVar(value="No has seleccionado imagenes.")
        self.progress_text_var = tk.StringVar(value="Progreso: 0/0")
        self.progress_var = tk.DoubleVar(value=0.0)
        self.status_var = tk.StringVar(
            value="Selecciona varias imagenes o una carpeta con archivos JPG, JPEG o PNG."
        )
        self._event_queue: Queue[tuple[str, BatchProgress | BatchProcessingResult | str]] | None = None
        self._worker_thread: Thread | None = None
        self._cancel_event: Event | None = None
        self._close_requested = False

        self._build_ui()

    def _build_ui(self) -> None:
        container = ttk.Frame(self.root, padding=16)
        container.pack(fill="both", expand=True)
        container.columnconfigure(1, weight=1)

        self.select_files_button = ttk.Button(
            container,
            text="Seleccionar imagenes",
            command=self.select_images,
        )
        self.select_files_button.grid(row=0, column=0, sticky="w", padx=(0, 12), pady=(0, 12))

        self.select_folder_button = ttk.Button(
            container,
            text="Seleccionar carpeta",
            command=self.select_folder,
        )
        self.select_folder_button.grid(row=0, column=1, sticky="w", padx=(0, 12), pady=(0, 12))

        self.process_button = ttk.Button(
            container,
            text="Procesar",
            command=self.process_images,
            state="disabled",
        )
        self.process_button.grid(row=0, column=2, sticky="e", pady=(0, 12))

        self.stop_button = ttk.Button(
            container,
            text="Parar",
            command=self.stop_processing,
            state="disabled",
        )
        self.stop_button.grid(row=0, column=3, sticky="e", padx=(12, 0), pady=(0, 12))

        selection_label = ttk.Label(container, text="Seleccion:")
        selection_label.grid(row=1, column=0, sticky="nw", padx=(0, 12))

        selection_entry = ttk.Entry(
            container,
            textvariable=self.selection_var,
            state="readonly",
        )
        selection_entry.grid(row=1, column=1, columnspan=2, sticky="ew")

        self.progress_bar = ttk.Progressbar(
            container,
            orient="horizontal",
            mode="determinate",
            maximum=100,
            variable=self.progress_var,
        )
        self.progress_bar.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(16, 6))

        progress_label = ttk.Label(container, textvariable=self.progress_text_var, anchor="w")
        progress_label.grid(row=3, column=0, columnspan=3, sticky="ew")

        self.status_label = tk.Label(
            container,
            textvariable=self.status_var,
            anchor="w",
            justify="left",
            fg="#1f1f1f",
            wraplength=720,
        )
        self.status_label.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(16, 0))

    def select_images(self) -> None:
        file_paths = filedialog.askopenfilenames(
            title="Selecciona una o varias imagenes",
            filetypes=[
                ("Imagenes compatibles", "*.jpg *.jpeg *.png"),
                ("JPEG", "*.jpg *.jpeg"),
                ("PNG", "*.png"),
            ],
        )

        if not file_paths:
            self._set_status("Seleccion de archivos cancelada.", is_error=False)
            return

        self.selected_paths = normalize_paths(file_paths)
        self._update_selection_state()
        self._set_status(
            f"{len(self.selected_paths)} imagen(es) lista(s) para procesar.",
            is_error=False,
        )

    def select_folder(self) -> None:
        folder_path = filedialog.askdirectory(title="Selecciona una carpeta con imagenes")
        if not folder_path:
            self._set_status("Seleccion de carpeta cancelada.", is_error=False)
            return

        self.selected_paths = collect_supported_images_from_folder(folder_path)
        if not self.selected_paths:
            self.selection_var.set(folder_path)
            self.process_button.config(state="disabled")
            self._set_status(
                "La carpeta seleccionada no contiene archivos JPG, JPEG o PNG.",
                is_error=True,
            )
            return

        self._update_selection_state(source_path=folder_path)
        self._set_status(
            f"Se encontraron {len(self.selected_paths)} imagen(es) en la carpeta seleccionada.",
            is_error=False,
        )

    def process_images(self) -> None:
        if not self.selected_paths:
            self._set_status("Selecciona imagenes o una carpeta antes de procesar.", is_error=True)
            return

        total_images = len(self.selected_paths)

        self._set_processing_state(is_processing=True)
        self._update_progress(0, total_images)
        self._set_status(f"Procesando {total_images} imagen(es)...", is_error=False)
        self._close_requested = False
        self._cancel_event = Event()
        self.stop_button.config(state="normal")
        self._event_queue = Queue()
        self._worker_thread = Thread(
            target=self._process_images_worker,
            args=(list(self.selected_paths), self._event_queue, self._cancel_event),
            daemon=True,
            name="exif-overlay-ui-worker",
        )
        self._worker_thread.start()
        self.root.after(50, self._poll_processing_events)

    def _process_images_worker(
        self,
        image_paths: list[str],
        event_queue: Queue[tuple[str, BatchProgress | BatchProcessingResult | str]],
        cancel_event: Event,
    ) -> None:
        try:
            result = process_images_batch(
                image_paths,
                output_subfolder="exportadas",
                progress_callback=lambda progress: event_queue.put(("progress", progress)),
                cancel_event=cancel_event,
            )
        except Exception as exc:
            event_queue.put(("fatal_error", str(exc)))
            return

        event_queue.put(("completed", result))

    def stop_processing(self) -> None:
        if self._cancel_event is None or self._cancel_event.is_set():
            return

        self._cancel_event.set()
        self.stop_button.config(state="disabled")
        self._set_status(
            "Deteniendo exportacion. Se finalizaran solo las imagenes ya iniciadas.",
            is_error=False,
        )

    def _poll_processing_events(self) -> None:
        event_queue = self._event_queue
        if event_queue is None:
            return

        should_continue = True

        while True:
            try:
                event_type, payload = event_queue.get_nowait()
            except Empty:
                break

            if event_type == "progress":
                if isinstance(payload, BatchProgress):
                    self._handle_progress_update(payload)
                continue

            if event_type == "completed":
                if isinstance(payload, BatchProcessingResult):
                    self._finish_processing(payload)
                should_continue = False
                break

            if event_type == "fatal_error":
                message = payload if isinstance(payload, str) else "Error interno durante el procesamiento."
                self._worker_thread = None
                self._event_queue = None
                self._cancel_event = None
                self._set_processing_state(is_processing=False)
                self._set_status(message, is_error=True)
                if self._close_requested:
                    self.root.destroy()
                should_continue = False
                break

        if should_continue:
            self.root.after(50, self._poll_processing_events)

    def _handle_progress_update(self, progress: BatchProgress) -> None:
        if progress.succeeded:
            status_message = f"Procesada {progress.current}/{progress.total}: {progress.image_name}"
            is_error = False
        else:
            status_message = progress.error_message or f"Error procesando {progress.image_name}"
            is_error = True

        self._update_progress(progress.current, progress.total)
        self._set_status(status_message, is_error=is_error)

    def _finish_processing(self, result: BatchProcessingResult) -> None:
        self._worker_thread = None
        self._event_queue = None
        self._cancel_event = None
        self._set_processing_state(is_processing=False)

        is_error = bool(result.failures) and not result.cancelled
        self._set_status(
            _build_batch_status(result.processed_count, result.failures, result.cancelled),
            is_error=is_error and result.processed_count == 0,
        )

        if self._close_requested:
            self.root.destroy()

    def _handle_close_request(self) -> None:
        if self._worker_thread is None:
            self.root.destroy()
            return

        self._close_requested = True
        self.stop_processing()

    def _update_selection_state(self, source_path: str | None = None) -> None:
        self.selection_var.set(_format_selection_text(self.selected_paths, source_path=source_path))
        self.process_button.config(state="normal" if self.selected_paths else "disabled")

    def _set_processing_state(self, is_processing: bool) -> None:
        button_state = "disabled" if is_processing else ("normal" if self.selected_paths else "disabled")
        self.process_button.config(state=button_state)
        self.select_files_button.config(state="disabled" if is_processing else "normal")
        self.select_folder_button.config(state="disabled" if is_processing else "normal")
        self.stop_button.config(state="normal" if is_processing and self._cancel_event is not None else "disabled")

    def _update_progress(self, current: int, total: int) -> None:
        percentage = 0 if total <= 0 else (current / total) * 100
        self.progress_var.set(percentage)
        self.progress_text_var.set(f"Progreso: {current}/{total}")

    def _set_status(self, message: str, is_error: bool) -> None:
        self.status_var.set(message)
        self.status_label.config(fg="#b00020" if is_error else "#1f1f1f")


def normalize_paths(paths: tuple[str, ...] | list[str]) -> list[str]:
    unique_paths = {str(Path(path).resolve()) for path in paths if Path(path).suffix.lower() in SUPPORTED_EXTENSIONS}
    return sorted(unique_paths)


def collect_supported_images_from_folder(folder_path: str) -> list[str]:
    folder = Path(folder_path)
    if not folder.exists() or not folder.is_dir():
        return []

    image_paths = [
        str(path.resolve())
        for path in sorted(folder.iterdir())
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    ]
    return image_paths


def _format_selection_text(selected_paths: list[str], source_path: str | None = None) -> str:
    if not selected_paths:
        return "No has seleccionado imagenes."

    if source_path:
        return f"{source_path} ({len(selected_paths)} imagenes compatibles)"

    if len(selected_paths) == 1:
        return selected_paths[0]

    preview = ", ".join(Path(path).name for path in selected_paths[:3])
    if len(selected_paths) > 3:
        preview = f"{preview}, ..."
    return f"{len(selected_paths)} imagenes: {preview}"


def _build_batch_status(processed_count: int, failures: list[str], cancelled: bool = False) -> str:
    if cancelled:
        summary = f"Exportacion detenida. Procesadas {processed_count} imagen(es)."
        if not failures:
            return summary

        details = " | ".join(failures[:3])
        if len(failures) > 3:
            details = f"{details} | ..."
        return f"{summary} Errores: {len(failures)}. {details}"

    if not failures:
        return f"Procesadas correctamente {processed_count} imagen(es)."

    summary = f"Procesadas {processed_count} imagen(es). Errores: {len(failures)}."
    details = " | ".join(failures[:3])
    if len(failures) > 3:
        details = f"{details} | ..."
    return f"{summary} {details}"
