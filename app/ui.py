from __future__ import annotations

from pathlib import Path
from queue import Empty, Queue
from threading import Event, Thread
import tkinter as tk
from tkinter import colorchooser, filedialog, ttk

from PIL import Image, ImageTk

from app.batch_service import BatchProcessingResult, BatchProgress, process_images as process_images_batch
from app.exif_service import extract_display_data
from app.image_service import render_overlay
from app.overlay_config import FONT_FAMILIES, OverlayFieldConfig, OverlayPreset, OverlayStyle, ShadowStyle, StrokeStyle, clone_preset, get_builtin_presets
from app.preset_store import PresetStoreData, load_preset_store, save_preset_store

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png"}
BG_COLOR = "#f3ede2"
SURFACE_COLOR = "#fffaf4"
BORDER_COLOR = "#dacfbf"
TEXT_COLOR = "#1f2a30"
MUTED_TEXT_COLOR = "#6d756e"
ACCENT_COLOR = "#156b6c"
ACCENT_HOVER_COLOR = "#11595a"
STOP_COLOR = "#c96b4f"
STOP_HOVER_COLOR = "#af5b42"
TRACK_COLOR = "#e2d8ca"
ERROR_COLOR = "#b23a48"
LISTBOX_BG = "#fcf8f2"
PREVIEW_FRAME_BG = "#f7f1e8"
PREVIEW_BG = "#ece4d7"
PREVIEW_DEBOUNCE_MS = 150
PREVIEW_SIZE = (420, 420)


class ExifOverlayApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("EXIF Overlay")
        self.root.geometry("1380x860")
        self.root.minsize(1220, 760)
        self.root.protocol("WM_DELETE_WINDOW", self._handle_close_request)

        self.selected_paths: list[str] = []
        self._preview_photo: ImageTk.PhotoImage | None = None
        self._preview_job: str | None = None
        self._preview_exif_cache: tuple[str, dict[str, str]] | None = None
        self._syncing_controls = False

        self._builtin_presets = get_builtin_presets()
        self._preset_store = load_preset_store()
        self._user_presets = self._preset_store.user_presets
        self._presets_by_id = _build_presets_by_id(self._builtin_presets, self._user_presets)
        self._selected_preset_id = _resolve_selected_preset_id(self._preset_store, self._presets_by_id)
        self._draft_preset = clone_preset(self._presets_by_id[self._selected_preset_id])
        self._preset_label_to_id = _build_preset_label_to_id(self._builtin_presets, self._user_presets)

        self.selection_var = tk.StringVar(value="No has seleccionado imagenes.")
        self.selection_count_var = tk.StringVar(value="0 imagenes")
        self.destination_var = tk.StringVar(value="Salida: subcarpeta exportadas junto al archivo original.")
        self.progress_text_var = tk.StringVar(value="0 de 0")
        self.progress_percent_var = tk.StringVar(value="0%")
        self.progress_var = tk.DoubleVar(value=0.0)
        self.current_file_var = tk.StringVar(value="Esperando seleccion.")
        self.status_title_var = tk.StringVar(value="Estado")
        self.status_var = tk.StringVar(
            value="Selecciona varias imagenes o una carpeta con archivos JPG, JPEG o PNG."
        )
        self.preview_caption_var = tk.StringVar(value="Preview de la primera foto del lote.")
        self.preview_meta_var = tk.StringVar(value="Sin imagen para previsualizar.")
        self.preview_items_var = tk.StringVar(value=("Todavia no hay archivos en el lote.",))

        self.preset_var = tk.StringVar()
        self.font_family_var = tk.StringVar()
        self.font_size_mode_var = tk.StringVar()
        self.font_size_var = tk.IntVar(value=36)
        self.text_color_var = tk.StringVar()
        self.shadow_enabled_var = tk.BooleanVar(value=True)
        self.shadow_color_var = tk.StringVar()
        self.shadow_opacity_var = tk.IntVar(value=55)
        self.shadow_offset_x_var = tk.IntVar(value=3)
        self.shadow_offset_y_var = tk.IntVar(value=3)
        self.stroke_enabled_var = tk.BooleanVar(value=True)
        self.stroke_color_var = tk.StringVar()
        self.stroke_opacity_var = tk.IntVar(value=100)
        self.stroke_width_var = tk.IntVar(value=2)
        self.show_exposure_var = tk.BooleanVar(value=True)
        self.show_iso_var = tk.BooleanVar(value=True)
        self.show_aperture_var = tk.BooleanVar(value=True)
        self.show_focal_length_var = tk.BooleanVar(value=True)
        self.separator_var = tk.StringVar(value="  |  ")

        self._event_queue: Queue[tuple[str, BatchProgress | BatchProcessingResult | str]] | None = None
        self._worker_thread: Thread | None = None
        self._cancel_event: Event | None = None
        self._close_requested = False

        self._configure_theme()
        self._build_ui()
        self._bind_control_changes()
        self._load_preset_into_controls(self._draft_preset)
        self._refresh_preview()

        if self._preset_store.warning_message:
            self._set_status(self._preset_store.warning_message, is_error=False, title="Presets")

    def _configure_theme(self) -> None:
        self.root.configure(bg=BG_COLOR)
        style = ttk.Style(self.root)

        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure("App.TFrame", background=BG_COLOR)
        style.configure("HeaderTitle.TLabel", background=BG_COLOR, foreground=TEXT_COLOR, font=("Segoe UI Semibold", 24))
        style.configure("HeaderSubtitle.TLabel", background=BG_COLOR, foreground=MUTED_TEXT_COLOR, font=("Segoe UI", 11))
        style.configure("PanelTitle.TLabel", background=SURFACE_COLOR, foreground=TEXT_COLOR, font=("Segoe UI Semibold", 13))
        style.configure("PanelBody.TLabel", background=SURFACE_COLOR, foreground=MUTED_TEXT_COLOR, font=("Segoe UI", 10))
        style.configure("EditorLabel.TLabel", background=SURFACE_COLOR, foreground=TEXT_COLOR, font=("Segoe UI Semibold", 10))
        style.configure("Micro.TLabel", background=SURFACE_COLOR, foreground=MUTED_TEXT_COLOR, font=("Segoe UI", 9))
        style.configure("ProgressValue.TLabel", background=SURFACE_COLOR, foreground=TEXT_COLOR, font=("Segoe UI Semibold", 11))
        style.configure("Surface.TFrame", background=SURFACE_COLOR)
        style.configure("Action.TButton", font=("Segoe UI Semibold", 10), padding=(16, 10), borderwidth=0)
        style.configure(
            "Accent.TButton",
            font=("Segoe UI Semibold", 10),
            padding=(18, 11),
            borderwidth=0,
            background=ACCENT_COLOR,
            foreground="white",
        )
        style.map("Accent.TButton", background=[("active", ACCENT_HOVER_COLOR), ("disabled", TRACK_COLOR)])
        style.configure(
            "Stop.TButton",
            font=("Segoe UI Semibold", 10),
            padding=(18, 11),
            borderwidth=0,
            background=STOP_COLOR,
            foreground="white",
        )
        style.map("Stop.TButton", background=[("active", STOP_HOVER_COLOR), ("disabled", TRACK_COLOR)])
        style.configure(
            "Overlay.Horizontal.TProgressbar",
            troughcolor=TRACK_COLOR,
            background=ACCENT_COLOR,
            bordercolor=TRACK_COLOR,
            lightcolor=ACCENT_COLOR,
            darkcolor=ACCENT_COLOR,
            thickness=16,
        )
        style.configure("Editor.TCheckbutton", background=SURFACE_COLOR, foreground=TEXT_COLOR, font=("Segoe UI", 10))

    def _build_ui(self) -> None:
        container = ttk.Frame(self.root, padding=24, style="App.TFrame")
        container.pack(fill="both", expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(2, weight=1)

        header = ttk.Frame(container, style="App.TFrame")
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)

        ttk.Label(header, text="EXIF Overlay Studio", style="HeaderTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text="Preview en vivo de la primera foto, presets persistentes y exportacion con el mismo motor de render.",
            style="HeaderSubtitle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(6, 0))

        self.count_badge = tk.Label(
            header,
            textvariable=self.selection_count_var,
            bg=ACCENT_COLOR,
            fg="white",
            font=("Segoe UI Semibold", 10),
            padx=14,
            pady=8,
        )
        self.count_badge.grid(row=0, column=1, rowspan=2, sticky="e")

        actions_panel = self._create_panel(container)
        actions_panel.grid(row=1, column=0, sticky="ew", pady=(18, 18))
        actions_panel.columnconfigure(0, weight=1)
        actions_panel.columnconfigure(1, weight=1)
        actions_panel.columnconfigure(2, weight=1)
        actions_panel.columnconfigure(3, weight=1)

        self.select_files_button = ttk.Button(
            actions_panel,
            text="Seleccionar imagenes",
            command=self.select_images,
            style="Action.TButton",
        )
        self.select_files_button.grid(row=0, column=0, sticky="ew", padx=(0, 10))

        self.select_folder_button = ttk.Button(
            actions_panel,
            text="Seleccionar carpeta",
            command=self.select_folder,
            style="Action.TButton",
        )
        self.select_folder_button.grid(row=0, column=1, sticky="ew", padx=(0, 10))

        self.process_button = ttk.Button(
            actions_panel,
            text="Exportar lote",
            command=self.process_images,
            state="disabled",
            style="Accent.TButton",
        )
        self.process_button.grid(row=0, column=2, sticky="ew", padx=(0, 10))

        self.stop_button = ttk.Button(
            actions_panel,
            text="Parar",
            command=self.stop_processing,
            state="disabled",
            style="Stop.TButton",
        )
        self.stop_button.grid(row=0, column=3, sticky="ew")

        ttk.Label(
            actions_panel,
            text="La exportacion se guarda en una carpeta exportadas dentro de la ruta original de cada imagen.",
            style="PanelBody.TLabel",
        ).grid(row=1, column=0, columnspan=4, sticky="w", pady=(14, 0))

        content = ttk.Frame(container, style="App.TFrame")
        content.grid(row=2, column=0, sticky="nsew")
        content.columnconfigure(0, weight=2)
        content.columnconfigure(1, weight=3)
        content.columnconfigure(2, weight=2)
        content.rowconfigure(0, weight=1)

        self._build_selection_panel(content)
        self._build_preview_panel(content)
        self._build_editor_panel(content)

        footer = self._create_panel(container)
        footer.grid(row=3, column=0, sticky="ew", pady=(18, 0))
        footer.columnconfigure(0, weight=1)

        ttk.Label(footer, text="Progreso del lote", style="PanelTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(footer, textvariable=self.current_file_var, style="PanelBody.TLabel", wraplength=1120).grid(
            row=1, column=0, sticky="ew", pady=(6, 12)
        )

        self.progress_bar = ttk.Progressbar(
            footer,
            orient="horizontal",
            mode="determinate",
            maximum=100,
            variable=self.progress_var,
            style="Overlay.Horizontal.TProgressbar",
        )
        self.progress_bar.grid(row=2, column=0, sticky="ew")

        footer_meta = ttk.Frame(footer, style="Surface.TFrame")
        footer_meta.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        footer_meta.columnconfigure(0, weight=1)
        footer_meta.columnconfigure(1, weight=0)

        ttk.Label(footer_meta, textvariable=self.progress_text_var, style="ProgressValue.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(footer_meta, textvariable=self.progress_percent_var, style="ProgressValue.TLabel").grid(row=0, column=1, sticky="e")

        ttk.Label(footer, textvariable=self.status_title_var, style="PanelTitle.TLabel").grid(row=4, column=0, sticky="w", pady=(16, 0))
        self.status_label = tk.Label(
            footer,
            textvariable=self.status_var,
            bg=SURFACE_COLOR,
            fg=TEXT_COLOR,
            anchor="nw",
            justify="left",
            wraplength=1120,
            font=("Segoe UI", 10),
        )
        self.status_label.grid(row=5, column=0, sticky="ew", pady=(8, 0))

    def _build_selection_panel(self, parent: ttk.Frame) -> None:
        selection_panel = self._create_panel(parent)
        selection_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        selection_panel.columnconfigure(0, weight=1)
        selection_panel.rowconfigure(3, weight=1)

        ttk.Label(selection_panel, text="Lote seleccionado", style="PanelTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(selection_panel, textvariable=self.selection_var, style="PanelBody.TLabel", wraplength=320).grid(row=1, column=0, sticky="ew", pady=(6, 4))
        ttk.Label(selection_panel, textvariable=self.destination_var, style="PanelBody.TLabel", wraplength=320).grid(row=2, column=0, sticky="ew", pady=(0, 14))

        preview_frame = tk.Frame(selection_panel, bg=LISTBOX_BG, highlightthickness=1, highlightbackground=BORDER_COLOR, highlightcolor=BORDER_COLOR)
        preview_frame.grid(row=3, column=0, sticky="nsew")
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(0, weight=1)

        self.preview_listbox = tk.Listbox(
            preview_frame,
            listvariable=self.preview_items_var,
            bg=LISTBOX_BG,
            fg=TEXT_COLOR,
            selectbackground="#d8ecec",
            selectforeground=TEXT_COLOR,
            activestyle="none",
            relief="flat",
            highlightthickness=0,
            borderwidth=0,
            font=("Consolas", 10),
        )
        self.preview_listbox.grid(row=0, column=0, sticky="nsew")

        preview_scrollbar = ttk.Scrollbar(preview_frame, orient="vertical", command=self.preview_listbox.yview)
        preview_scrollbar.grid(row=0, column=1, sticky="ns")
        self.preview_listbox.config(yscrollcommand=preview_scrollbar.set)

    def _build_preview_panel(self, parent: ttk.Frame) -> None:
        preview_panel = self._create_panel(parent)
        preview_panel.grid(row=0, column=1, sticky="nsew", padx=(0, 12))
        preview_panel.columnconfigure(0, weight=1)
        preview_panel.rowconfigure(2, weight=1)

        ttk.Label(preview_panel, text="Preview visual", style="PanelTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(preview_panel, textvariable=self.preview_caption_var, style="PanelBody.TLabel", wraplength=460).grid(row=1, column=0, sticky="ew", pady=(6, 14))

        preview_frame = tk.Frame(preview_panel, bg=PREVIEW_FRAME_BG, highlightthickness=1, highlightbackground=BORDER_COLOR, highlightcolor=BORDER_COLOR)
        preview_frame.grid(row=2, column=0, sticky="nsew")
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(0, weight=1)

        self.preview_label = tk.Label(
            preview_frame,
            bg=PREVIEW_BG,
            fg=MUTED_TEXT_COLOR,
            text="Selecciona imagenes para generar el preview.",
            justify="center",
            font=("Segoe UI", 11),
            width=46,
            height=24,
        )
        self.preview_label.grid(row=0, column=0, sticky="nsew")

        ttk.Label(preview_panel, textvariable=self.preview_meta_var, style="Micro.TLabel", wraplength=460).grid(row=3, column=0, sticky="ew", pady=(10, 0))

    def _build_editor_panel(self, parent: ttk.Frame) -> None:
        editor_panel = self._create_panel(parent)
        editor_panel.grid(row=0, column=2, sticky="nsew")
        editor_panel.columnconfigure(0, weight=1)

        ttk.Label(editor_panel, text="Editor del overlay", style="PanelTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(editor_panel, text="Fuente, color, sombra, borde, campos visibles y presets persistentes por usuario.", style="PanelBody.TLabel", wraplength=320).grid(row=1, column=0, sticky="ew", pady=(6, 14))

        preset_frame = ttk.Frame(editor_panel, style="Surface.TFrame")
        preset_frame.grid(row=2, column=0, sticky="ew")
        preset_frame.columnconfigure(0, weight=1)
        ttk.Label(preset_frame, text="Preset activo", style="EditorLabel.TLabel").grid(row=0, column=0, sticky="w")
        self.preset_combo = ttk.Combobox(
            preset_frame,
            textvariable=self.preset_var,
            state="readonly",
            values=list(self._preset_label_to_id.keys()),
        )
        self.preset_combo.grid(row=1, column=0, sticky="ew", pady=(6, 10))
        self.preset_combo.bind("<<ComboboxSelected>>", self._on_preset_selected)
        ttk.Button(preset_frame, text="Restaurar preset", command=self.restore_selected_preset, style="Action.TButton").grid(row=2, column=0, sticky="ew")

        save_frame = ttk.Frame(editor_panel, style="Surface.TFrame")
        save_frame.grid(row=3, column=0, sticky="ew", pady=(16, 0))
        save_frame.columnconfigure(0, weight=1)
        save_frame.columnconfigure(1, weight=1)
        save_frame.columnconfigure(2, weight=1)
        ttk.Label(save_frame, text="Guardar configuracion actual", style="EditorLabel.TLabel").grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Button(save_frame, text="Guardar U1", command=lambda: self.save_to_user_preset(0), style="Action.TButton").grid(row=1, column=0, sticky="ew", padx=(0, 6), pady=(6, 0))
        ttk.Button(save_frame, text="Guardar U2", command=lambda: self.save_to_user_preset(1), style="Action.TButton").grid(row=1, column=1, sticky="ew", padx=(0, 6), pady=(6, 0))
        ttk.Button(save_frame, text="Guardar U3", command=lambda: self.save_to_user_preset(2), style="Action.TButton").grid(row=1, column=2, sticky="ew", pady=(6, 0))

        typography = ttk.Frame(editor_panel, style="Surface.TFrame")
        typography.grid(row=4, column=0, sticky="ew", pady=(18, 0))
        typography.columnconfigure(1, weight=1)
        ttk.Label(typography, text="Fuente", style="EditorLabel.TLabel").grid(row=0, column=0, sticky="w")
        self.font_combo = ttk.Combobox(typography, textvariable=self.font_family_var, state="readonly", values=FONT_FAMILIES)
        self.font_combo.grid(row=0, column=1, sticky="ew", pady=(0, 6))
        ttk.Label(typography, text="Tamano", style="EditorLabel.TLabel").grid(row=1, column=0, sticky="w")
        self.font_mode_combo = ttk.Combobox(typography, textvariable=self.font_size_mode_var, state="readonly", values=("auto", "manual"))
        self.font_mode_combo.grid(row=1, column=1, sticky="ew", pady=(0, 6))
        ttk.Label(typography, text="Tamano manual", style="EditorLabel.TLabel").grid(row=2, column=0, sticky="w")
        self.font_size_scale = ttk.Scale(typography, from_=12, to=160, orient="horizontal", variable=self.font_size_var)
        self.font_size_scale.grid(row=2, column=1, sticky="ew")
        ttk.Label(typography, textvariable=self.font_size_var, style="Micro.TLabel").grid(row=2, column=2, sticky="w", padx=(8, 0))
        self._bind_scale_reset(self.font_size_scale, "font_size")

        color_frame = ttk.Frame(editor_panel, style="Surface.TFrame")
        color_frame.grid(row=5, column=0, sticky="ew", pady=(18, 0))
        color_frame.columnconfigure(1, weight=1)
        ttk.Label(color_frame, text="Color del texto", style="EditorLabel.TLabel").grid(row=0, column=0, sticky="w")
        self.text_color_button = self._create_color_button(color_frame, self.text_color_var, self.choose_text_color)
        self.text_color_button.grid(row=0, column=1, sticky="ew")

        shadow_frame = ttk.Frame(editor_panel, style="Surface.TFrame")
        shadow_frame.grid(row=6, column=0, sticky="ew", pady=(18, 0))
        shadow_frame.columnconfigure(1, weight=1)
        ttk.Checkbutton(shadow_frame, text="Sombra", variable=self.shadow_enabled_var, style="Editor.TCheckbutton").grid(row=0, column=0, sticky="w")
        self.shadow_color_button = self._create_color_button(shadow_frame, self.shadow_color_var, self.choose_shadow_color)
        self.shadow_color_button.grid(row=0, column=1, sticky="ew")
        ttk.Label(shadow_frame, text="Opacidad", style="EditorLabel.TLabel").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.shadow_opacity_scale = ttk.Scale(shadow_frame, from_=0, to=100, orient="horizontal", variable=self.shadow_opacity_var)
        self.shadow_opacity_scale.grid(row=1, column=1, sticky="ew", pady=(8, 0))
        ttk.Label(shadow_frame, textvariable=self.shadow_opacity_var, style="Micro.TLabel").grid(row=1, column=2, sticky="w", padx=(8, 0), pady=(8, 0))
        self._bind_scale_reset(self.shadow_opacity_scale, "shadow_opacity")
        ttk.Label(shadow_frame, text="Offset X", style="EditorLabel.TLabel").grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.shadow_offset_x_scale = ttk.Scale(shadow_frame, from_=-20, to=20, orient="horizontal", variable=self.shadow_offset_x_var)
        self.shadow_offset_x_scale.grid(row=2, column=1, sticky="ew", pady=(8, 0))
        ttk.Label(shadow_frame, textvariable=self.shadow_offset_x_var, style="Micro.TLabel").grid(row=2, column=2, sticky="w", padx=(8, 0), pady=(8, 0))
        self._bind_scale_reset(self.shadow_offset_x_scale, "shadow_offset_x")
        ttk.Label(shadow_frame, text="Offset Y", style="EditorLabel.TLabel").grid(row=3, column=0, sticky="w", pady=(8, 0))
        self.shadow_offset_y_scale = ttk.Scale(shadow_frame, from_=-20, to=20, orient="horizontal", variable=self.shadow_offset_y_var)
        self.shadow_offset_y_scale.grid(row=3, column=1, sticky="ew", pady=(8, 0))
        ttk.Label(shadow_frame, textvariable=self.shadow_offset_y_var, style="Micro.TLabel").grid(row=3, column=2, sticky="w", padx=(8, 0), pady=(8, 0))
        self._bind_scale_reset(self.shadow_offset_y_scale, "shadow_offset_y")

        stroke_frame = ttk.Frame(editor_panel, style="Surface.TFrame")
        stroke_frame.grid(row=7, column=0, sticky="ew", pady=(18, 0))
        stroke_frame.columnconfigure(1, weight=1)
        ttk.Checkbutton(stroke_frame, text="Borde / resalte", variable=self.stroke_enabled_var, style="Editor.TCheckbutton").grid(row=0, column=0, sticky="w")
        self.stroke_color_button = self._create_color_button(stroke_frame, self.stroke_color_var, self.choose_stroke_color)
        self.stroke_color_button.grid(row=0, column=1, sticky="ew")
        ttk.Label(stroke_frame, text="Opacidad", style="EditorLabel.TLabel").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.stroke_opacity_scale = ttk.Scale(stroke_frame, from_=0, to=100, orient="horizontal", variable=self.stroke_opacity_var)
        self.stroke_opacity_scale.grid(row=1, column=1, sticky="ew", pady=(8, 0))
        ttk.Label(stroke_frame, textvariable=self.stroke_opacity_var, style="Micro.TLabel").grid(row=1, column=2, sticky="w", padx=(8, 0), pady=(8, 0))
        self._bind_scale_reset(self.stroke_opacity_scale, "stroke_opacity")
        ttk.Label(stroke_frame, text="Ancho", style="EditorLabel.TLabel").grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.stroke_width_scale = ttk.Scale(stroke_frame, from_=0, to=12, orient="horizontal", variable=self.stroke_width_var)
        self.stroke_width_scale.grid(row=2, column=1, sticky="ew", pady=(8, 0))
        ttk.Label(stroke_frame, textvariable=self.stroke_width_var, style="Micro.TLabel").grid(row=2, column=2, sticky="w", padx=(8, 0), pady=(8, 0))
        self._bind_scale_reset(self.stroke_width_scale, "stroke_width")

        field_frame = ttk.Frame(editor_panel, style="Surface.TFrame")
        field_frame.grid(row=8, column=0, sticky="ew", pady=(18, 0))
        field_frame.columnconfigure(0, weight=1)
        field_frame.columnconfigure(1, weight=1)
        ttk.Label(field_frame, text="Campos EXIF visibles", style="EditorLabel.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Checkbutton(field_frame, text="Exposicion", variable=self.show_exposure_var, style="Editor.TCheckbutton").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Checkbutton(field_frame, text="ISO", variable=self.show_iso_var, style="Editor.TCheckbutton").grid(row=1, column=1, sticky="w", pady=(6, 0))
        ttk.Checkbutton(field_frame, text="Apertura", variable=self.show_aperture_var, style="Editor.TCheckbutton").grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Checkbutton(field_frame, text="Focal", variable=self.show_focal_length_var, style="Editor.TCheckbutton").grid(row=2, column=1, sticky="w", pady=(6, 0))
        ttk.Label(field_frame, text="Separador", style="EditorLabel.TLabel").grid(row=3, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(field_frame, textvariable=self.separator_var).grid(row=3, column=1, sticky="ew", pady=(10, 0))

    def _create_panel(self, parent: tk.Misc) -> tk.Frame:
        return tk.Frame(
            parent,
            bg=SURFACE_COLOR,
            highlightthickness=1,
            highlightbackground=BORDER_COLOR,
            highlightcolor=BORDER_COLOR,
            padx=18,
            pady=18,
        )

    def _create_color_button(self, parent: tk.Misc, variable: tk.StringVar, command) -> tk.Button:
        return tk.Button(
            parent,
            textvariable=variable,
            command=command,
            relief="flat",
            borderwidth=0,
            padx=8,
            pady=6,
            fg="white",
            activeforeground="white",
            font=("Segoe UI Semibold", 9),
            cursor="hand2",
        )

    def _bind_control_changes(self) -> None:
        variables: list[tk.Variable] = [
            self.font_family_var,
            self.font_size_mode_var,
            self.font_size_var,
            self.text_color_var,
            self.shadow_enabled_var,
            self.shadow_color_var,
            self.shadow_opacity_var,
            self.shadow_offset_x_var,
            self.shadow_offset_y_var,
            self.stroke_enabled_var,
            self.stroke_color_var,
            self.stroke_opacity_var,
            self.stroke_width_var,
            self.show_exposure_var,
            self.show_iso_var,
            self.show_aperture_var,
            self.show_focal_length_var,
            self.separator_var,
        ]

        for variable in variables:
            variable.trace_add("write", self._on_editor_control_changed)

    def _bind_scale_reset(self, scale: ttk.Scale, setting_name: str) -> None:
        scale.bind("<Double-Button-1>", lambda _event, name=setting_name: self._reset_scale_to_selected_preset(name))

    def _reset_scale_to_selected_preset(self, setting_name: str) -> None:
        preset = self._presets_by_id[self._selected_preset_id].normalized()
        reset_actions = {
            "font_size": lambda: self.font_size_var.set(preset.style.font_size),
            "shadow_opacity": lambda: self.shadow_opacity_var.set(preset.style.shadow.opacity),
            "shadow_offset_x": lambda: self.shadow_offset_x_var.set(preset.style.shadow.offset_x),
            "shadow_offset_y": lambda: self.shadow_offset_y_var.set(preset.style.shadow.offset_y),
            "stroke_opacity": lambda: self.stroke_opacity_var.set(preset.style.stroke.opacity),
            "stroke_width": lambda: self.stroke_width_var.set(preset.style.stroke.width),
        }
        action = reset_actions.get(setting_name)
        if action is None:
            return

        action()
        self._set_status("Control restaurado al valor base del preset seleccionado.", is_error=False, title="Preset")

    def restore_selected_preset(self) -> None:
        preset = self._presets_by_id[self._selected_preset_id]
        self._draft_preset = clone_preset(preset)
        self._load_preset_into_controls(self._draft_preset)
        self._set_status(f"Se ha restaurado el preset '{preset.name}'.", is_error=False, title="Preset restaurado")
        self._schedule_preview_refresh()

    def save_to_user_preset(self, user_index: int) -> None:
        if not 0 <= user_index < len(self._user_presets):
            return

        target = self._user_presets[user_index]
        draft = self._build_draft_preset()
        saved = clone_preset(draft, preset_id=target.preset_id, name=target.name, built_in=False)
        self._user_presets[user_index] = saved
        self._presets_by_id = _build_presets_by_id(self._builtin_presets, self._user_presets)
        self._preset_label_to_id = _build_preset_label_to_id(self._builtin_presets, self._user_presets)
        self._selected_preset_id = saved.preset_id
        self._draft_preset = clone_preset(saved)
        self._sync_preset_combobox_values()
        self._load_preset_into_controls(self._draft_preset)
        save_preset_store(self._user_presets, self._selected_preset_id)
        self._set_status(f"Configuracion guardada en '{saved.name}'.", is_error=False, title="Preset guardado")
        self._schedule_preview_refresh()

    def choose_text_color(self) -> None:
        self._choose_color(self.text_color_var, "Color del texto")

    def choose_shadow_color(self) -> None:
        self._choose_color(self.shadow_color_var, "Color de la sombra")

    def choose_stroke_color(self) -> None:
        self._choose_color(self.stroke_color_var, "Color del borde")

    def _choose_color(self, variable: tk.StringVar, title: str) -> None:
        chosen_color = colorchooser.askcolor(color=variable.get(), title=title, parent=self.root)
        if not chosen_color or not chosen_color[1]:
            return
        variable.set(chosen_color[1].lower())

    def _on_preset_selected(self, _event: tk.Event) -> None:
        selected_label = self.preset_var.get()
        preset_id = self._preset_label_to_id.get(selected_label)
        if preset_id is None or preset_id == self._selected_preset_id:
            return

        self._selected_preset_id = preset_id
        self._draft_preset = clone_preset(self._presets_by_id[preset_id])
        self._load_preset_into_controls(self._draft_preset)
        save_preset_store(self._user_presets, self._selected_preset_id)
        self._set_status(f"Preset activo: {self._draft_preset.name}.", is_error=False, title="Preset cargado")
        self._schedule_preview_refresh()

    def _on_editor_control_changed(self, *_args) -> None:
        if self._syncing_controls:
            return

        self._draft_preset = self._build_draft_preset()
        self._update_color_buttons()
        self._update_size_controls_state()
        self._schedule_preview_refresh()

    def _build_draft_preset(self) -> OverlayPreset:
        base_preset = self._presets_by_id[self._selected_preset_id]
        return OverlayPreset(
            preset_id=base_preset.preset_id,
            name=base_preset.name,
            built_in=base_preset.built_in,
            fields=OverlayFieldConfig(
                show_exposure=self.show_exposure_var.get(),
                show_iso=self.show_iso_var.get(),
                show_aperture=self.show_aperture_var.get(),
                show_focal_length=self.show_focal_length_var.get(),
                separator=self.separator_var.get(),
            ).normalized(),
            style=OverlayStyle(
                font_family=self.font_family_var.get(),
                font_size_mode=self.font_size_mode_var.get(),
                font_size=int(round(self.font_size_var.get())),
                text_color=self.text_color_var.get(),
                shadow=ShadowStyle(
                    enabled=self.shadow_enabled_var.get(),
                    color=self.shadow_color_var.get(),
                    opacity=int(round(self.shadow_opacity_var.get())),
                    offset_x=int(round(self.shadow_offset_x_var.get())),
                    offset_y=int(round(self.shadow_offset_y_var.get())),
                ),
                stroke=StrokeStyle(
                    enabled=self.stroke_enabled_var.get(),
                    color=self.stroke_color_var.get(),
                    opacity=int(round(self.stroke_opacity_var.get())),
                    width=int(round(self.stroke_width_var.get())),
                ),
            ).normalized(),
        )

    def _load_preset_into_controls(self, preset: OverlayPreset) -> None:
        self._syncing_controls = True
        normalized = preset.normalized()
        self.preset_var.set(_preset_label_for_preset(normalized))
        self.font_family_var.set(normalized.style.font_family)
        self.font_size_mode_var.set(normalized.style.font_size_mode)
        self.font_size_var.set(normalized.style.font_size)
        self.text_color_var.set(normalized.style.text_color)
        self.shadow_enabled_var.set(normalized.style.shadow.enabled)
        self.shadow_color_var.set(normalized.style.shadow.color)
        self.shadow_opacity_var.set(normalized.style.shadow.opacity)
        self.shadow_offset_x_var.set(normalized.style.shadow.offset_x)
        self.shadow_offset_y_var.set(normalized.style.shadow.offset_y)
        self.stroke_enabled_var.set(normalized.style.stroke.enabled)
        self.stroke_color_var.set(normalized.style.stroke.color)
        self.stroke_opacity_var.set(normalized.style.stroke.opacity)
        self.stroke_width_var.set(normalized.style.stroke.width)
        self.show_exposure_var.set(normalized.fields.show_exposure)
        self.show_iso_var.set(normalized.fields.show_iso)
        self.show_aperture_var.set(normalized.fields.show_aperture)
        self.show_focal_length_var.set(normalized.fields.show_focal_length)
        self.separator_var.set(normalized.fields.separator)
        self._syncing_controls = False
        self._draft_preset = clone_preset(normalized)
        self._update_color_buttons()
        self._update_size_controls_state()

    def _update_color_buttons(self) -> None:
        self._style_color_button(self.text_color_button, self.text_color_var.get())
        self._style_color_button(self.shadow_color_button, self.shadow_color_var.get())
        self._style_color_button(self.stroke_color_button, self.stroke_color_var.get())

    def _style_color_button(self, button: tk.Button, color: str) -> None:
        button.config(bg=color, activebackground=color)

    def _update_size_controls_state(self) -> None:
        if self.font_size_mode_var.get() == "manual":
            self.font_size_scale.state(["!disabled"])
        else:
            self.font_size_scale.state(["disabled"])

    def _sync_preset_combobox_values(self) -> None:
        self.preset_combo.configure(values=list(self._preset_label_to_id.keys()))
        self.preset_var.set(_preset_label_for_preset(self._presets_by_id[self._selected_preset_id]))

    def _schedule_preview_refresh(self) -> None:
        if self._preview_job is not None:
            self.root.after_cancel(self._preview_job)
        self._preview_job = self.root.after(PREVIEW_DEBOUNCE_MS, self._refresh_preview)

    def _refresh_preview(self) -> None:
        self._preview_job = None
        if not self.selected_paths:
            self._show_preview_placeholder("Selecciona imagenes para generar el preview.")
            return

        preview_path = self.selected_paths[0]
        try:
            exif_data = self._get_preview_exif_data(preview_path)
            rendered = render_overlay(preview_path, exif_data, self._draft_preset, for_preview=True)
        except (FileNotFoundError, ValueError, RuntimeError, OSError) as exc:
            self._show_preview_placeholder(f"No se pudo generar el preview.\n{exc}")
            return

        image = rendered.copy()
        image.thumbnail(PREVIEW_SIZE, Image.Resampling.LANCZOS)
        self._preview_photo = ImageTk.PhotoImage(image)
        self.preview_label.config(image=self._preview_photo, text="")
        self.preview_caption_var.set(f"Preview de: {Path(preview_path).name}")
        self.preview_meta_var.set(
            f"Resolucion del preview: {image.width}x{image.height}. El render final usa el mismo estilo sobre la imagen exportada."
        )

    def _get_preview_exif_data(self, image_path: str) -> dict[str, str]:
        if self._preview_exif_cache is not None and self._preview_exif_cache[0] == image_path:
            return self._preview_exif_cache[1]

        exif_data = extract_display_data(image_path)
        self._preview_exif_cache = (image_path, exif_data)
        return exif_data

    def _show_preview_placeholder(self, message: str) -> None:
        self._preview_photo = None
        self.preview_label.config(image="", text=message)
        self.preview_caption_var.set("Preview de la primera foto del lote.")
        self.preview_meta_var.set("Sin imagen para previsualizar.")

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
            self._set_status("Seleccion de archivos cancelada.", is_error=False, title="Sin cambios")
            return

        self.selected_paths = normalize_paths(file_paths)
        self._preview_exif_cache = None
        self._update_selection_state()
        self._set_status(
            f"{len(self.selected_paths)} imagen(es) lista(s) para procesar.",
            is_error=False,
            title="Lote preparado",
        )
        self._schedule_preview_refresh()

    def select_folder(self) -> None:
        folder_path = filedialog.askdirectory(title="Selecciona una carpeta con imagenes")
        if not folder_path:
            self._set_status("Seleccion de carpeta cancelada.", is_error=False, title="Sin cambios")
            return

        self.selected_paths = collect_supported_images_from_folder(folder_path)
        self._preview_exif_cache = None
        if not self.selected_paths:
            self.selection_var.set(f"{folder_path} (sin imagenes compatibles)")
            self.selection_count_var.set("0 imagenes")
            self.destination_var.set("Salida: no disponible hasta que haya archivos compatibles.")
            self.preview_items_var.set(("La carpeta seleccionada no contiene archivos JPG, JPEG o PNG.",))
            self.preview_listbox.selection_clear(0, "end")
            self.process_button.config(state="disabled")
            self._show_preview_placeholder("La carpeta seleccionada no contiene imagenes compatibles.")
            self._set_status(
                "La carpeta seleccionada no contiene archivos JPG, JPEG o PNG.",
                is_error=True,
                title="Carpeta vacia",
            )
            return

        self._update_selection_state(source_path=folder_path)
        self._set_status(
            f"Se encontraron {len(self.selected_paths)} imagen(es) en la carpeta seleccionada.",
            is_error=False,
            title="Carpeta cargada",
        )
        self._schedule_preview_refresh()

    def process_images(self) -> None:
        if not self.selected_paths:
            self._set_status("Selecciona imagenes o una carpeta antes de procesar.", is_error=True, title="Falta seleccion")
            return

        total_images = len(self.selected_paths)
        preset_snapshot = self._build_draft_preset().normalized()

        self._set_processing_state(is_processing=True)
        self._update_progress(0, total_images)
        self.current_file_var.set("Preparando lote para exportacion...")
        self._set_status(f"Procesando {total_images} imagen(es)...", is_error=False, title="Procesando")
        self._close_requested = False
        self._cancel_event = Event()
        self.stop_button.config(state="normal")
        self._event_queue = Queue()
        self._worker_thread = Thread(
            target=self._process_images_worker,
            args=(list(self.selected_paths), preset_snapshot, self._event_queue, self._cancel_event),
            daemon=True,
            name="exif-overlay-ui-worker",
        )
        self._worker_thread.start()
        self.root.after(50, self._poll_processing_events)

    def _process_images_worker(
        self,
        image_paths: list[str],
        preset: OverlayPreset,
        event_queue: Queue[tuple[str, BatchProgress | BatchProcessingResult | str]],
        cancel_event: Event,
    ) -> None:
        try:
            result = process_images_batch(
                image_paths,
                preset=preset,
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
        self.current_file_var.set("Deteniendo el lote. Se completaran solo las tareas ya iniciadas.")
        self._set_status(
            "Deteniendo exportacion. Se finalizaran solo las imagenes ya iniciadas.",
            is_error=False,
            title="Parando",
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
                self.current_file_var.set("El lote se ha detenido por un error interno.")
                self._set_status(message, is_error=True, title="Error")
                if self._close_requested:
                    self.root.destroy()
                should_continue = False
                break

        if should_continue:
            self.root.after(50, self._poll_processing_events)

    def _handle_progress_update(self, progress: BatchProgress) -> None:
        self.current_file_var.set(f"Archivo actual: {progress.image_name}")

        if progress.succeeded:
            status_message = f"Procesada {progress.current}/{progress.total}: {progress.image_name}"
            self._set_status(status_message, is_error=False, title="Procesando")
        else:
            status_message = progress.error_message or f"Error procesando {progress.image_name}"
            self._set_status(status_message, is_error=True, title="Incidencia")

        self._update_progress(progress.current, progress.total)

    def _finish_processing(self, result: BatchProcessingResult) -> None:
        self._worker_thread = None
        self._event_queue = None
        self._cancel_event = None
        self._set_processing_state(is_processing=False)

        if result.cancelled:
            self.current_file_var.set("Exportacion detenida por el usuario.")
            status_title = "Exportacion detenida"
        elif result.failures:
            self.current_file_var.set("Lote completado con incidencias.")
            status_title = "Completado con incidencias"
        else:
            self.current_file_var.set("Lote completado correctamente.")
            status_title = "Completado"

        is_error = bool(result.failures) and not result.cancelled and result.processed_count == 0
        self._set_status(
            _build_batch_status(result.processed_count, result.failures, result.cancelled),
            is_error=is_error,
            title=status_title,
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
        self.selection_count_var.set(_format_selection_count(self.selected_paths))
        self.destination_var.set(_format_destination_text(self.selected_paths))
        self.preview_items_var.set(tuple(_build_preview_items(self.selected_paths)))
        self.preview_listbox.selection_clear(0, "end")
        if self.selected_paths:
            self.preview_listbox.selection_set(0)
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
        self.progress_text_var.set(f"{current} de {total}")
        self.progress_percent_var.set(f"{percentage:.0f}%")

    def _set_status(self, message: str, is_error: bool, title: str = "Estado") -> None:
        self.status_title_var.set(title)
        self.status_var.set(message)
        self.status_label.config(fg=ERROR_COLOR if is_error else TEXT_COLOR)


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


def _format_selection_count(selected_paths: list[str]) -> str:
    count = len(selected_paths)
    return f"{count} imagen" if count == 1 else f"{count} imagenes"


def _format_destination_text(selected_paths: list[str]) -> str:
    if not selected_paths:
        return "Salida: subcarpeta exportadas junto al archivo original."

    parent_dirs = sorted({str(Path(path).resolve().parent) for path in selected_paths})
    if len(parent_dirs) == 1:
        return f"Salida: {parent_dirs[0]}\\exportadas"
    return "Salida: subcarpeta exportadas en cada carpeta original."


def _build_preview_items(selected_paths: list[str]) -> list[str]:
    if not selected_paths:
        return ["Todavia no hay archivos en el lote."]

    preview_lines: list[str] = []
    for index, path in enumerate(selected_paths, start=1):
        resolved_path = Path(path)
        preview_lines.append(f"{index:>2}. {resolved_path.name}")
    return preview_lines


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


def _build_presets_by_id(builtin_presets: list[OverlayPreset], user_presets: list[OverlayPreset]) -> dict[str, OverlayPreset]:
    return {preset.preset_id: preset for preset in builtin_presets + user_presets}


def _build_preset_label_to_id(builtin_presets: list[OverlayPreset], user_presets: list[OverlayPreset]) -> dict[str, str]:
    labels: dict[str, str] = {}
    for preset in builtin_presets + user_presets:
        labels[_preset_label_for_preset(preset)] = preset.preset_id
    return labels


def _preset_label_for_preset(preset: OverlayPreset) -> str:
    prefix = "Fijo" if preset.built_in else "Usuario"
    return f"{prefix} · {preset.name}"


def _resolve_selected_preset_id(store: PresetStoreData, presets_by_id: dict[str, OverlayPreset]) -> str:
    if store.last_selected_preset_id in presets_by_id:
        return store.last_selected_preset_id
    return "builtin_classic"
