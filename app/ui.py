from __future__ import annotations

from pathlib import Path
import tkinter as tk
from tkinter import filedialog, ttk

from app.exif_service import extract_display_data
from app.image_service import create_annotated_copy

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png"}


class ExifOverlayApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("EXIF Overlay")
        self.root.geometry("760x320")
        self.root.minsize(760, 320)

        self.selected_paths: list[str] = []
        self.selection_var = tk.StringVar(value="No has seleccionado imagenes.")
        self.progress_text_var = tk.StringVar(value="Progreso: 0/0")
        self.progress_var = tk.DoubleVar(value=0.0)
        self.status_var = tk.StringVar(
            value="Selecciona varias imagenes o una carpeta con archivos JPG, JPEG o PNG."
        )

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
        processed_count = 0
        failures: list[str] = []

        self._set_processing_state(is_processing=True)
        self._update_progress(0, total_images)
        self._set_status(f"Procesando {total_images} imagen(es)...", is_error=False)
        self.root.update_idletasks()

        try:
            for index, image_path in enumerate(self.selected_paths, start=1):
                path = Path(image_path)
                self._set_status(f"Procesando {index}/{total_images}: {path.name}", is_error=False)
                self.root.update_idletasks()

                if not path.exists():
                    failures.append(f"{path.name}: el archivo ya no existe.")
                    self._update_progress(index, total_images)
                    continue

                try:
                    exif_data = extract_display_data(str(path))
                    create_annotated_copy(str(path), exif_data, output_subfolder="exportadas")
                except (FileNotFoundError, ValueError, RuntimeError, OSError) as exc:
                    failures.append(f"{path.name}: {exc}")
                except Exception as exc:
                    failures.append(f"{path.name}: error inesperado: {exc}")
                else:
                    processed_count += 1

                self._update_progress(index, total_images)
                self.root.update_idletasks()
        finally:
            self._set_processing_state(is_processing=False)

        if failures and processed_count == 0:
            self._set_status(_build_batch_status(processed_count, failures), is_error=True)
            return

        self._set_status(_build_batch_status(processed_count, failures), is_error=bool(failures))

    def _update_selection_state(self, source_path: str | None = None) -> None:
        self.selection_var.set(_format_selection_text(self.selected_paths, source_path=source_path))
        self.process_button.config(state="normal" if self.selected_paths else "disabled")

    def _set_processing_state(self, is_processing: bool) -> None:
        button_state = "disabled" if is_processing else ("normal" if self.selected_paths else "disabled")
        self.process_button.config(state=button_state)
        self.select_files_button.config(state="disabled" if is_processing else "normal")
        self.select_folder_button.config(state="disabled" if is_processing else "normal")

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


def _build_batch_status(processed_count: int, failures: list[str]) -> str:
    if not failures:
        return f"Procesadas correctamente {processed_count} imagen(es)."

    summary = f"Procesadas {processed_count} imagen(es). Errores: {len(failures)}."
    details = " | ".join(failures[:3])
    if len(failures) > 3:
        details = f"{details} | ..."
    return f"{summary} {details}"
