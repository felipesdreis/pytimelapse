"""PyTimelapse v2.0 — Sistema de Timelapse via Câmera do Notebook.

Interface gráfica (Tkinter) + Preview de câmera em tempo real + Persistência JSON.

Uso:
    python timelapse.py

Dependências:
    pip install opencv-python Pillow
"""

import json
import logging
import os
import platform
import shutil
import subprocess
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox
import tkinter as tk
from tkinter import ttk

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONFIG_FILE = Path(__file__).parent / "config.json"

DEFAULTS = {
    "interval": 5,
    "fps": 24,
    "duration": None,
    "camera_index": 0,
    "output_dir": "./timelapse_output",
    "keep_frames": False,
}

PREVIEW_FPS = 15  # UI refresh rate for the camera preview
FLASH_DURATION = 0.2  # seconds the red border stays after a capture


# ---------------------------------------------------------------------------
# Main Application
# ---------------------------------------------------------------------------


class TimelapseApp(tk.Tk):
    """Main Tkinter application for PyTimelapse."""

    def __init__(self) -> None:
        super().__init__()
        self.title("PyTimelapse")
        self.minsize(900, 600)
        self.resizable(True, True)

        # Runtime state
        self.stop_event = threading.Event()
        self.capture_thread: threading.Thread | None = None
        self.preview_thread: threading.Thread | None = None
        self.session_dir: Path | None = None
        self.frame_count = 0
        self.session_start: datetime | None = None
        self.capture_flag = threading.Event()  # pulses True for FLASH_DURATION
        self.latest_frame = None  # numpy array shared between threads
        self.frame_lock = threading.Lock()
        self.camera: "cv2.VideoCapture | None" = None  # type: ignore[name-defined]
        self.camera_lock = threading.Lock()
        self._running = False
        self._log_file: logging.FileHandler | None = None

        # Active max duration for timer mode (seconds, overrides var_duration when set)
        self._active_max_duration: int | None = None

        # Tkinter vars (will be populated by load_config)
        self.var_interval = tk.StringVar()
        self.var_fps = tk.StringVar()
        self.var_duration = tk.StringVar()
        self.var_camera_index = tk.StringVar()
        self.var_output_dir = tk.StringVar()
        self.var_keep_frames = tk.BooleanVar()
        self.var_timer_minutes = tk.StringVar(value="5")

        self.load_config()
        self._build_ui()
        self._bind_traces()
        self._create_app_icon()

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self._clock_after_id: str | None = None
        self._update_clock()

    # ------------------------------------------------------------------
    # Config persistence
    # ------------------------------------------------------------------

    def load_config(self) -> None:
        """Load settings from config.json; fall back to defaults on error."""
        cfg = dict(DEFAULTS)
        try:
            if CONFIG_FILE.exists():
                with CONFIG_FILE.open(encoding="utf-8") as fh:
                    loaded = json.load(fh)
                cfg.update({k: loaded[k] for k in DEFAULTS if k in loaded})
        except Exception:
            pass  # corrupted or missing — use defaults silently

        self.var_interval.set(str(cfg["interval"]))
        self.var_fps.set(str(cfg["fps"]))
        self.var_duration.set("" if cfg["duration"] is None else str(cfg["duration"]))
        self.var_camera_index.set(str(cfg["camera_index"]))
        self.var_output_dir.set(cfg["output_dir"])
        self.var_keep_frames.set(bool(cfg["keep_frames"]))

    def save_config(self) -> None:
        """Serialize current GUI settings to config.json (auto-save)."""
        try:
            duration_raw = self.var_duration.get().strip()
            cfg = {
                "interval": int(self.var_interval.get() or DEFAULTS["interval"]),
                "fps": int(self.var_fps.get() or DEFAULTS["fps"]),
                "duration": int(duration_raw) if duration_raw else None,
                "camera_index": int(self.var_camera_index.get() or DEFAULTS["camera_index"]),
                "output_dir": self.var_output_dir.get() or DEFAULTS["output_dir"],
                "keep_frames": bool(self.var_keep_frames.get()),
            }
            CONFIG_FILE.write_text(
                json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except (ValueError, OSError):
            pass  # don't crash the app on transient save errors

    def _bind_traces(self) -> None:
        """Attach auto-save callbacks to all config variables."""
        for var in (
            self.var_interval,
            self.var_fps,
            self.var_duration,
            self.var_camera_index,
            self.var_output_dir,
            self.var_keep_frames,
        ):
            var.trace_add("write", self._trace_save)

    def _trace_save(self, *_args) -> None:
        """Tkinter trace callback — saves config after each field change."""
        self.save_config()

    # ------------------------------------------------------------------
    # GUI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        """Build the two-column layout."""
        self.columnconfigure(0, weight=0, minsize=350)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        self._build_control_panel()
        self._build_preview_panel()

    def _build_control_panel(self) -> None:
        """Left panel: configuration fields, action buttons, status, log."""
        panel = tk.Frame(self, bd=1, relief=tk.RIDGE, padx=10, pady=10)
        panel.grid(row=0, column=0, sticky="nsew")
        panel.columnconfigure(1, weight=1)

        row = 0

        # Title
        tk.Label(panel, text="PyTimelapse", font=("Helvetica", 14, "bold")).grid(
            row=row, column=0, columnspan=3, pady=(0, 10), sticky="w"
        )
        row += 1

        # Helper to create a labelled entry row
        def add_field(label: str, var: tk.Variable, row_idx: int) -> tk.Entry:
            tk.Label(panel, text=label, anchor="w").grid(
                row=row_idx, column=0, sticky="w", pady=2
            )
            entry = tk.Entry(panel, textvariable=var, width=10)
            entry.grid(row=row_idx, column=1, sticky="ew", padx=(5, 0))
            return entry

        self._entry_interval = add_field("Intervalo (s):", self.var_interval, row)
        row += 1
        self._entry_fps = add_field("FPS do vídeo:", self.var_fps, row)
        row += 1
        self._entry_duration = add_field("Duração máx (min):", self.var_duration, row)
        row += 1
        self._entry_camera = add_field("Índice câmera:", self.var_camera_index, row)
        row += 1

        # Output dir row (entry + browse button)
        tk.Label(panel, text="Diretório de saída:", anchor="w").grid(
            row=row, column=0, sticky="w", pady=2
        )
        dir_frame = tk.Frame(panel)
        dir_frame.grid(row=row, column=1, sticky="ew", padx=(5, 0))
        dir_frame.columnconfigure(0, weight=1)
        self._entry_output = tk.Entry(dir_frame, textvariable=self.var_output_dir)
        self._entry_output.grid(row=0, column=0, sticky="ew")
        self._btn_browse = tk.Button(dir_frame, text="...", width=3, command=self._browse_dir)
        self._btn_browse.grid(row=0, column=1, padx=(4, 0))
        row += 1

        # Keep frames checkbox
        self._chk_keep = tk.Checkbutton(
            panel, text="Manter frames após compilar", variable=self.var_keep_frames
        )
        self._chk_keep.grid(row=row, column=0, columnspan=2, sticky="w", pady=4)
        row += 1

        # Separator
        ttk.Separator(panel, orient="horizontal").grid(
            row=row, column=0, columnspan=3, sticky="ew", pady=8
        )
        row += 1

        # Action buttons — Start + Videos side by side
        btn_row = tk.Frame(panel)
        btn_row.grid(row=row, column=0, columnspan=3, sticky="ew", pady=2)
        btn_row.columnconfigure(0, weight=1)
        btn_row.columnconfigure(1, weight=0)

        self._btn_start = tk.Button(
            btn_row,
            text="Iniciar Timelapse",
            bg="#27ae60",
            fg="white",
            font=("Helvetica", 10, "bold"),
            command=self._start_normal,
        )
        self._btn_start.grid(row=0, column=0, sticky="ew")

        self._btn_videos = tk.Button(
            btn_row,
            text="🎬 Vídeos",
            bg="#2980b9",
            fg="white",
            font=("Helvetica", 10, "bold"),
            command=self._open_videos_modal,
        )
        self._btn_videos.grid(row=0, column=1, padx=(4, 0))
        row += 1

        # Timer mode row
        timer_frame = tk.Frame(panel)
        timer_frame.grid(row=row, column=0, columnspan=3, sticky="ew", pady=2)
        timer_frame.columnconfigure(1, weight=1)

        tk.Label(timer_frame, text="Gravar por:", anchor="w").grid(row=0, column=0, sticky="w")
        self._entry_timer = tk.Entry(timer_frame, textvariable=self.var_timer_minutes, width=5)
        self._entry_timer.grid(row=0, column=1, sticky="ew", padx=(4, 2))
        tk.Label(timer_frame, text="min", anchor="w").grid(row=0, column=2, sticky="w")

        self._btn_timer_start = tk.Button(
            timer_frame,
            text="⏱ Iniciar com Timer",
            bg="#8e44ad",
            fg="white",
            font=("Helvetica", 9, "bold"),
            command=self._start_with_timer,
        )
        self._btn_timer_start.grid(row=0, column=3, padx=(6, 0))
        row += 1

        self._btn_stop = tk.Button(
            panel,
            text="Parar e Compilar",
            bg="#e74c3c",
            fg="white",
            font=("Helvetica", 10, "bold"),
            state=tk.DISABLED,
            command=self.stop_timelapse,
        )
        self._btn_stop.grid(row=row, column=0, columnspan=3, sticky="ew", pady=2)
        row += 1

        ttk.Separator(panel, orient="horizontal").grid(
            row=row, column=0, columnspan=3, sticky="ew", pady=8
        )
        row += 1

        # Status labels
        self._lbl_frames = tk.Label(panel, text="Frames: 0", anchor="w")
        self._lbl_frames.grid(row=row, column=0, columnspan=3, sticky="w")
        row += 1

        self._lbl_time = tk.Label(panel, text="Tempo: 00:00:00", anchor="w")
        self._lbl_time.grid(row=row, column=0, columnspan=3, sticky="w")
        row += 1

        self._lbl_session = tk.Label(
            panel, text="Sessão: —", anchor="w", wraplength=320, justify="left"
        )
        self._lbl_session.grid(row=row, column=0, columnspan=3, sticky="w")
        row += 1

        # Progress bar
        self._progressbar = ttk.Progressbar(panel, orient="horizontal", mode="determinate")
        self._progressbar.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        row += 1

        self._lbl_progress = tk.Label(panel, text="", anchor="w", fg="gray")
        self._lbl_progress.grid(row=row, column=0, columnspan=3, sticky="w")
        row += 1

        ttk.Separator(panel, orient="horizontal").grid(
            row=row, column=0, columnspan=3, sticky="ew", pady=8
        )
        row += 1

        # Log widget
        tk.Label(panel, text="Log de eventos:", anchor="w").grid(
            row=row, column=0, columnspan=3, sticky="w"
        )
        row += 1

        log_frame = tk.Frame(panel)
        log_frame.grid(row=row, column=0, columnspan=3, sticky="nsew", pady=(2, 0))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        panel.rowconfigure(row, weight=1)

        self._txt_log = tk.Text(log_frame, height=8, state=tk.DISABLED, wrap=tk.WORD, font=("Courier", 8))
        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self._txt_log.yview)
        self._txt_log.configure(yscrollcommand=scrollbar.set)
        self._txt_log.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        self._all_config_widgets = [
            self._entry_interval,
            self._entry_fps,
            self._entry_duration,
            self._entry_camera,
            self._entry_output,
            self._btn_browse,
            self._chk_keep,
            self._entry_timer,
        ]

    def _build_preview_panel(self) -> None:
        """Right panel: canvas for live camera preview."""
        panel = tk.Frame(self, bg="#1a1a1a")
        panel.grid(row=0, column=1, sticky="nsew")
        panel.rowconfigure(0, weight=1)
        panel.columnconfigure(0, weight=1)

        self._canvas = tk.Canvas(panel, bg="#1a1a1a", highlightthickness=0)
        self._canvas.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)

        self._no_camera_label = tk.Label(
            self._canvas,
            text="Câmera não encontrada",
            fg="#aaaaaa",
            bg="#1a1a1a",
            font=("Helvetica", 14),
        )

        self._photo_image = None  # keep reference to avoid GC

    # ------------------------------------------------------------------
    # Icon
    # ------------------------------------------------------------------

    def _create_app_icon(self) -> None:
        """Generate and set the application window icon using PIL."""
        try:
            from PIL import Image, ImageDraw, ImageTk
        except ImportError:
            return
        size = 64
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Camera body
        draw.rounded_rectangle([4, 18, 60, 54], radius=6, fill="#2c3e50")
        # Lens outer ring
        draw.ellipse([16, 22, 48, 50], fill="#3498db", outline="#2980b9", width=2)
        # Lens inner
        draw.ellipse([24, 30, 40, 44], fill="#1a252f")
        # Lens highlight
        draw.ellipse([26, 32, 34, 38], fill="#5dade2")
        # Viewfinder bump
        draw.rounded_rectangle([20, 10, 38, 20], radius=3, fill="#2c3e50")
        # Flash
        draw.rounded_rectangle([46, 12, 58, 20], radius=2, fill="#f1c40f")

        photo = ImageTk.PhotoImage(img)
        self._icon_photo = photo  # keep reference to prevent GC
        self.iconphoto(True, photo)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _browse_dir(self) -> None:
        """Open file dialog to choose the output directory."""
        chosen = filedialog.askdirectory(initialdir=self.var_output_dir.get() or ".")
        if chosen:
            self.var_output_dir.set(chosen)

    def _open_videos_modal(self) -> None:
        """Open a modal window listing all timelapse videos in the output directory."""
        output_dir = Path(self.var_output_dir.get())

        modal = tk.Toplevel(self)
        modal.title("Vídeos Criados")
        modal.minsize(560, 380)
        modal.transient(self)
        modal.grab_set()
        modal.columnconfigure(0, weight=1)
        modal.rowconfigure(1, weight=1)

        # Header
        tk.Label(modal, text="Timelapse Videos", font=("Helvetica", 12, "bold"), anchor="w").grid(
            row=0, column=0, columnspan=2, sticky="w", padx=12, pady=(10, 4)
        )

        # Listbox with scrollbar
        list_frame = tk.Frame(modal)
        list_frame.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=12, pady=4)
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        lb = tk.Listbox(list_frame, font=("Courier", 9), activestyle="dotbox", selectmode=tk.SINGLE)
        lb.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(list_frame, orient="vertical", command=lb.yview)
        sb.grid(row=0, column=1, sticky="ns")
        lb.configure(yscrollcommand=sb.set)

        # Populate list
        videos: list[Path] = []
        if output_dir.exists():
            videos = sorted(output_dir.rglob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)

        if videos:
            for vp in videos:
                size_mb = vp.stat().st_size / (1024 * 1024)
                mtime = datetime.fromtimestamp(vp.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
                lb.insert(tk.END, f"  {mtime}  {size_mb:5.1f} MB  {vp.name}")
        else:
            lb.insert(tk.END, "  Nenhum vídeo encontrado em: " + str(output_dir))

        # Status bar
        lbl_path = tk.Label(modal, text="", anchor="w", fg="#555", wraplength=520, justify="left")
        lbl_path.grid(row=2, column=0, columnspan=2, sticky="w", padx=12, pady=(2, 4))

        def _on_select(event=None):
            sel = lb.curselection()
            if sel and videos:
                lbl_path.config(text=str(videos[sel[0]]))

        lb.bind("<<ListboxSelect>>", _on_select)

        def _open_selected():
            sel = lb.curselection()
            if not sel or not videos:
                return
            path = videos[sel[0]]
            try:
                sys_name = platform.system()
                if sys_name == "Windows":
                    os.startfile(str(path))
                elif sys_name == "Darwin":
                    subprocess.Popen(["open", str(path)])
                else:
                    subprocess.Popen(["xdg-open", str(path)])
            except Exception as exc:
                messagebox.showerror("Erro ao abrir", str(exc), parent=modal)

        lb.bind("<Double-1>", lambda e: _open_selected())

        # Buttons
        btn_frame = tk.Frame(modal)
        btn_frame.grid(row=3, column=0, columnspan=2, sticky="e", padx=12, pady=(4, 10))

        tk.Button(btn_frame, text="Abrir Vídeo", bg="#27ae60", fg="white",
                  font=("Helvetica", 9, "bold"), command=_open_selected).pack(side=tk.LEFT, padx=4)
        tk.Button(btn_frame, text="Fechar", command=modal.destroy).pack(side=tk.LEFT, padx=4)

    def _start_normal(self) -> None:
        """Start timelapse without a forced timer (respects 'Duração máx' field)."""
        self._active_max_duration = None
        self.start_timelapse()

    def _start_with_timer(self) -> None:
        """Start timelapse and stop automatically after the configured timer minutes."""
        try:
            minutes = int(self.var_timer_minutes.get().strip())
            if minutes <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror(
                "Timer inválido",
                "Informe um número inteiro positivo de minutos para o timer.",
            )
            return
        self._active_max_duration = minutes * 60
        self.log_event(f"Modo Timer: gravação por {minutes} minuto(s).")
        self.start_timelapse()

    def start_timelapse(self) -> None:
        """Validate camera, create session directory and start threads.
        Call _start_normal() or _start_with_timer() instead of calling this directly.
        """
        try:
            import cv2  # noqa: F401
        except ImportError:
            messagebox.showerror(
                "Dependência ausente",
                "opencv-python não está instalado.\nExecute: pip install opencv-python",
            )
            return

        try:
            from PIL import Image, ImageTk  # noqa: F401
        except ImportError:
            messagebox.showerror(
                "Dependência ausente",
                "Pillow não está instalado.\nExecute: pip install Pillow",
            )
            return

        cam_idx = self._safe_int(self.var_camera_index.get(), DEFAULTS["camera_index"])
        import cv2

        cap = cv2.VideoCapture(cam_idx)
        if not cap.isOpened():
            self._show_no_camera()
            cap.release()
            messagebox.showerror(
                "Câmera não encontrada",
                f"Não foi possível abrir a câmera com índice {cam_idx}.\n"
                "Verifique o índice ou conecte uma câmera.",
            )
            return
        self.camera = cap

        self.session_dir = self.setup_output_dir(self.var_output_dir.get())
        self.frame_count = 0
        self.session_start = datetime.now()
        self._running = True
        self.stop_event.clear()
        self.capture_flag.clear()

        # Set up log file for this session
        log_path = self.session_dir.parent / "timelapse.log"
        self._session_log_path = log_path

        self._lbl_session.config(text=f"Sessão: {self.session_dir.parent}")
        self.log_event("Sessão iniciada")

        # Disable config fields, enable stop button
        self._set_controls_state(tk.DISABLED)
        self._btn_start.config(state=tk.DISABLED)
        self._btn_stop.config(state=tk.NORMAL)
        self._progressbar["value"] = 0
        self._lbl_progress.config(text="")

        # Start threads
        self.capture_thread = threading.Thread(
            target=self.capture_loop, args=(self.stop_event,), daemon=True
        )
        self.preview_thread = threading.Thread(
            target=self.preview_loop, args=(self.stop_event,), daemon=True
        )
        self.capture_thread.start()
        self.preview_thread.start()

    def stop_timelapse(self) -> None:
        """Signal threads to stop, then trigger video compilation."""
        if not self._running:
            return
        self._running = False
        self.stop_event.set()
        self._btn_stop.config(state=tk.DISABLED)
        self.log_event("Parando captura...")

        # Join threads in a background thread to avoid blocking the GUI
        def _wait_and_compile():
            if self.capture_thread:
                self.capture_thread.join(timeout=10)
            if self.preview_thread:
                self.preview_thread.join(timeout=5)

            with self.camera_lock:
                if self.camera:
                    self.camera.release()
                    self.camera = None

            if self.session_dir and self.session_dir.exists():
                self.after(0, lambda: self.compile_video(self.session_dir))
            else:
                self.after(0, self._on_compile_done, None)

        threading.Thread(target=_wait_and_compile, daemon=True).start()

    # ------------------------------------------------------------------
    # Background threads
    # ------------------------------------------------------------------

    def capture_loop(self, stop_evt: threading.Event) -> None:
        """Capture frames at the configured interval."""
        interval = self._safe_int(self.var_interval.get(), DEFAULTS["interval"])
        if self._active_max_duration is not None:
            max_duration = self._active_max_duration
        else:
            duration_raw = self.var_duration.get().strip()
            max_duration = int(duration_raw) * 60 if duration_raw else None

        import cv2

        while not stop_evt.is_set():
            if max_duration and self.session_start:
                elapsed = (datetime.now() - self.session_start).total_seconds()
                if elapsed >= max_duration:
                    self.after(0, self.stop_timelapse)
                    break

            frame = None
            with self.camera_lock:
                if self.camera and self.camera.isOpened():
                    ret, frame = self.camera.read()
                    if not ret:
                        frame = None

            if frame is not None:
                self.frame_count += 1
                filename = self.session_dir / f"frame_{self.frame_count:05d}.jpg"
                cv2.imwrite(str(filename), frame)
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                log_line = f"{ts} — frame_{self.frame_count:05d}.jpg capturado"
                try:
                    with self._session_log_path.open("a", encoding="utf-8") as fh:
                        fh.write(log_line + "\n")
                except OSError:
                    pass
                self.after(0, self._update_status)
                # Trigger flash
                self.capture_flag.set()
                threading.Timer(FLASH_DURATION, self.capture_flag.clear).start()

            # Wait for interval, checking stop_event frequently
            deadline = time.monotonic() + interval
            while time.monotonic() < deadline and not stop_evt.is_set():
                time.sleep(0.05)

    def preview_loop(self, stop_evt: threading.Event) -> None:
        """Continuously read camera frames and push them to the canvas."""
        sleep_interval = 1.0 / PREVIEW_FPS

        while not stop_evt.is_set():
            frame = None
            with self.camera_lock:
                if self.camera and self.camera.isOpened():
                    ret, frame = self.camera.read()
                    if not ret:
                        frame = None

            with self.frame_lock:
                self.latest_frame = frame

            self.after(0, self._update_canvas)
            time.sleep(sleep_interval)

        # Clear canvas when stopped
        self.after(0, self._clear_canvas)

    # ------------------------------------------------------------------
    # Canvas update (main thread)
    # ------------------------------------------------------------------

    def _update_canvas(self) -> None:
        """Draw the latest camera frame onto the Tkinter canvas."""
        with self.frame_lock:
            frame = self.latest_frame

        if frame is None:
            self._show_no_camera()
            return

        self._no_camera_label.place_forget()

        try:
            from PIL import Image, ImageTk
            import cv2
        except ImportError:
            return

        canvas_w = self._canvas.winfo_width()
        canvas_h = self._canvas.winfo_height()
        if canvas_w < 2 or canvas_h < 2:
            return

        # Convert BGR → RGB and resize to fit canvas
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(rgb)
        img.thumbnail((canvas_w, canvas_h), Image.LANCZOS)

        photo = ImageTk.PhotoImage(img)
        self._photo_image = photo  # prevent GC

        # Center on canvas
        x = canvas_w // 2
        y = canvas_h // 2
        self._canvas.delete("preview")
        self._canvas.create_image(x, y, anchor="center", image=photo, tags="preview")

        # Flash border on capture
        if self.capture_flag.is_set():
            self._canvas.delete("flash")
            border = 4
            self._canvas.create_rectangle(
                border, border, canvas_w - border, canvas_h - border,
                outline="red", width=border, tags="flash"
            )
        else:
            self._canvas.delete("flash")

    def _show_no_camera(self) -> None:
        """Display the 'camera not found' message on the canvas."""
        self._canvas.delete("preview")
        self._canvas.delete("flash")
        self._no_camera_label.place(relx=0.5, rely=0.5, anchor="center")

    def _clear_canvas(self) -> None:
        """Clear preview canvas after capture ends."""
        self._canvas.delete("preview")
        self._canvas.delete("flash")
        self._no_camera_label.place_forget()
        self._photo_image = None

    # ------------------------------------------------------------------
    # Video compilation
    # ------------------------------------------------------------------

    def compile_video(self, frames_dir: Path) -> None:
        """Compile captured frames into an .mp4 file (runs in worker thread)."""
        fps = self._safe_int(self.var_fps.get(), DEFAULTS["fps"])
        session_root = frames_dir.parent
        ts = session_root.name.replace("session_", "")
        output_path = session_root / f"timelapse_{ts}.mp4"

        frame_files = sorted(frames_dir.glob("frame_*.jpg"))
        total = len(frame_files)

        if total == 0:
            self.log_event("Nenhum frame para compilar.")
            self.after(0, self._on_compile_done, None)
            return

        self.log_event(f"Compilando {total} frames em vídeo...")

        def _compile():
            try:
                import cv2
            except ImportError:
                self.after(0, lambda: messagebox.showerror(
                    "Erro", "opencv-python não encontrado para compilação."
                ))
                self.after(0, self._on_compile_done, None)
                return

            first = cv2.imread(str(frame_files[0]))
            if first is None:
                self.after(0, self._on_compile_done, None)
                return

            h, w = first.shape[:2]
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            writer = cv2.VideoWriter(str(output_path), fourcc, fps, (w, h))

            for i, fp in enumerate(frame_files):
                img = cv2.imread(str(fp))
                if img is not None:
                    writer.write(img)
                progress = int((i + 1) / total * 100)
                self.after(0, self._set_progress, progress, i + 1, total)

            writer.release()

            keep = self.var_keep_frames.get()
            if not keep:
                shutil.rmtree(frames_dir, ignore_errors=True)

            self.after(0, self._on_compile_done, output_path)

        threading.Thread(target=_compile, daemon=True).start()

    def _set_progress(self, value: int, done: int, total: int) -> None:
        self._progressbar["value"] = value
        self._lbl_progress.config(text=f"Compilando: {done}/{total} frames ({value}%)")

    def _on_compile_done(self, output_path: Path | None) -> None:
        """Called on main thread when compilation finishes."""
        self._progressbar["value"] = 0
        self._lbl_progress.config(text="")
        self._set_controls_state(tk.NORMAL)
        self._btn_start.config(state=tk.NORMAL)
        self._btn_stop.config(state=tk.DISABLED)

        if output_path and output_path.exists():
            self.log_event(f"Vídeo gerado: {output_path}")
            messagebox.showinfo("Concluído", f"Timelapse salvo em:\n{output_path}")
        else:
            self.log_event("Compilação concluída (sem vídeo gerado).")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def setup_output_dir(self, base_path: str) -> Path:
        """Create and return the frames directory for this session."""
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        session_root = Path(base_path) / f"session_{ts}"
        frames_dir = session_root / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        return frames_dir

    def log_event(self, msg: str) -> None:
        """Append a timestamped message to the GUI log widget."""
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}\n"
        self._txt_log.config(state=tk.NORMAL)
        self._txt_log.insert("1.0", line)
        self._txt_log.config(state=tk.DISABLED)

        # Also write to session log file if available
        try:
            if hasattr(self, "_session_log_path") and self._session_log_path:
                with self._session_log_path.open("a", encoding="utf-8") as fh:
                    fh.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
        except OSError:
            pass

    def _update_status(self) -> None:
        """Refresh frame count label (called from main thread via after())."""
        self._lbl_frames.config(text=f"Frames: {self.frame_count}")

    def _update_clock(self) -> None:
        """Periodically update the elapsed time label."""
        if self._running and self.session_start:
            elapsed = datetime.now() - self.session_start
            h, rem = divmod(int(elapsed.total_seconds()), 3600)
            m, s = divmod(rem, 60)
            self._lbl_time.config(text=f"Tempo: {h:02d}:{m:02d}:{s:02d}")
        self._clock_after_id = self.after(1000, self._update_clock)

    def _set_controls_state(self, state: str) -> None:
        """Enable or disable all configuration widgets."""
        for widget in self._all_config_widgets:
            widget.config(state=state)
        self._btn_timer_start.config(state=state)
        self._btn_videos.config(state=state)

    def on_close(self) -> None:
        """Safely shut down threads before destroying the window."""
        if self._running:
            self._running = False
            self.stop_event.set()
            if self.capture_thread:
                self.capture_thread.join(timeout=3)
            if self.preview_thread:
                self.preview_thread.join(timeout=3)
        with self.camera_lock:
            if self.camera:
                self.camera.release()
                self.camera = None
        if self._clock_after_id:
            self.after_cancel(self._clock_after_id)
        self.destroy()

    @staticmethod
    def _safe_int(value: str, default: int) -> int:
        """Parse an integer safely, returning default on failure."""
        try:
            return int(value)
        except (ValueError, TypeError):
            return default


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app = TimelapseApp()
    app.mainloop()
