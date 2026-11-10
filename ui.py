"""Interfaz de J.A.R.V.I.S para Windows, desarrollada por Sukima Labs."""

import os, time, math, random, threading, ctypes, itertools, webbrowser
import tkinter as tk
from tkinter import simpledialog
from collections import deque
from pathlib import Path
import psutil
from PIL import Image, ImageTk, ImageSequence, ImageEnhance

from app_config import (
    has_gemini_api_key,
    load_app_config,
    save_app_config,
    get_backend,
    has_runtime_credentials,
)
from actions.weather import get_current_city, get_location_region, get_weather_summary
from actions.health import get_health_data, get_health_card_lines

BASE_DIR = Path(__file__).resolve().parent

SYSTEM_NAME = "J.A.R.V.I.S"
MODEL_BADGE = "ASISTENTE DE VOZ · Windows"
UI_TEMPLATES = {
    "sukima": "MANDO SUKIMA",
    "visor": "VISOR AZUL",
    "tactico": "MAPA TÁCTICO",
}
SPANISH_MONTHS = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)
SPANISH_DAYS = (
    "lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo",
)

# ── Renk paleti ──────────────────────────────────────────────────────────────
C_BG      = "#11131A"
C_PRI     = "#E7B66B"  # warm champagne accent
C_ORG     = "#CF765B"
C_ORG2    = "#E6A477"
C_MID     = "#836A46"
C_DIM     = "#39343D"
C_DIMMER  = "#1A1B22"
C_TEXT    = "#EFE9DD"
C_PANEL   = "#1B1C24"
C_GREEN   = "#9FB99D"
C_RED     = "#E56E67"
C_MUTED   = "#A15E79"
C_BLUE    = "#A7B9D7"
C_GOLD    = "#E9BC6D"

# Orb durum renkleri
ORB_COLORS = {
    "LISTENING":    (231, 182, 107),
    "SPEAKING":     (167, 185, 215),
    "THINKING":     (233, 188, 109),
    "MUTED":        (161, 94, 121),
    "PAUSED":       (80, 72, 63),
    "ERROR":        (229, 110, 103),
    "INITIALISING": (229, 110, 103),
}

# ── Boyutlar ─────────────────────────────────────────────────────────────────
W_TARGET = 2200
H_TARGET = 1320
LEFT_W_T = 360
RIGHT_W_T = 410
HDR_H    = 72
FOOTER_H = 34
INPUT_H  = 34
CONTROL_H = 146

VOICES = ["Charon", "Algenib", "Puck", "Aoede", "Kore", "Fenrir", "Leda", "Orus", "Zephyr"]

# ── Lokal font yukleyicisi ──────────────────────────────────────────────────
# Fonts/ klasorundeki tum .ttf dosyalarini *private* olarak yukleriz: sistem
# geneline kurulum gerekmez, sadece bu surec icinde gorunur olur. Boylece
# Orbitron gibi futuristic fontlari sadece klasore birakmak yeterli.
def _load_local_fonts() -> None:
    fonts_dir = BASE_DIR / "Fonts"
    if not fonts_dir.is_dir():
        return
    try:
        add_font = ctypes.windll.gdi32.AddFontResourceExW
    except Exception:
        return
    FR_PRIVATE = 0x10
    for ttf in fonts_dir.glob("*.ttf"):
        try:
            add_font(str(ttf), FR_PRIVATE, 0)
        except Exception:
            pass


_load_local_fonts()


# ── Font sistemi ─────────────────────────────────────────────────────────────
# Govde icin Grift okunakli kaliyor; baslik/HUD icin Orbitron sci-fi hissi
# veriyor. Orbitron yoksa Tk otomatik olarak varsayilana duser.
FONT_BODY_FAMILY = "Grift"
FONT_DISPLAY_FAMILY = "Orbitron"


def font_body(size: int):
    return (FONT_BODY_FAMILY, size)


def font_body_bold(size: int):
    return (FONT_BODY_FAMILY, size, "bold")


def font_display(size: int):
    return (FONT_DISPLAY_FAMILY, size, "bold")


def draw_text_glow(canvas, x, y, *, text, fill, font, glow_color, layers: int = 2, **kwargs):
    """create_text + hafif neon hale. glow_color daha sonuk bir tonda olmali."""
    for off in range(layers, 0, -1):
        for dx, dy in ((-off, 0), (off, 0), (0, -off), (0, off)):
            canvas.create_text(x + dx, y + dy, text=text, fill=glow_color, font=font, **kwargs)
    return canvas.create_text(x, y, text=text, fill=fill, font=font, **kwargs)


STATE_HEX_COLORS = {
    "LISTENING": C_GREEN,
    "SPEAKING": C_BLUE,
    "THINKING": C_GOLD,
    "INITIALISING": C_RED,
    "ERROR": C_RED,
}


# ── SoundManager ─────────────────────────────────────────────────────────────

# Windows MCI (winmm) ile MP3 calma — ek bagimlilik gerektirmez.
try:
    _winmm = ctypes.windll.winmm
    _mciSendString = _winmm.mciSendStringW
    _mciSendString.argtypes = [
        ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_void_p,
    ]
    _HAS_WINMM = True
except Exception:
    _HAS_WINMM = False

_alias_counter = itertools.count(1)


class _MciTrack:
    """Tek bir MCI MP3 calma instance'i."""

    def __init__(self, path: Path, volume: float):
        self.alias = f"jarvis_sfx_{next(_alias_counter)}"
        self._opened = False
        self._closed = False
        self.path = str(path)
        self._volume = max(0.0, min(1.0, float(volume)))

    def open(self) -> bool:
        if not _HAS_WINMM:
            return False
        # MCI dosya yolunun tek bir kelimede olmasi icin tirnaklarla sariyoruz.
        cmd = f'open "{self.path}" type mpegvideo alias {self.alias}'
        err = _mciSendString(cmd, None, 0, None)
        if err != 0:
            return False
        self._opened = True
        try:
            vol = int(self._volume * 1000)
            _mciSendString(f"setaudio {self.alias} volume to {vol}", None, 0, None)
        except Exception:
            pass
        return True

    def play(self) -> bool:
        if not self._opened:
            return False
        err = _mciSendString(f"play {self.alias}", None, 0, None)
        return err == 0

    def is_playing(self) -> bool:
        if not self._opened or self._closed:
            return False
        buf = ctypes.create_unicode_buffer(64)
        err = _mciSendString(f"status {self.alias} mode", buf, 64, None)
        if err != 0:
            return False
        return buf.value.strip().lower() == "playing"

    def stop(self) -> None:
        if self._opened and not self._closed:
            try:
                _mciSendString(f"stop {self.alias}", None, 0, None)
            except Exception:
                pass

    def close(self) -> None:
        if self._opened and not self._closed:
            try:
                _mciSendString(f"close {self.alias}", None, 0, None)
            except Exception:
                pass
            self._closed = True

    def set_volume(self, volume: float) -> None:
        if not self._opened or self._closed:
            return
        self._volume = max(0.0, min(1.0, float(volume)))
        try:
            vol = int(self._volume * 1000)
            _mciSendString(f"setaudio {self.alias} volume to {vol}", None, 0, None)
        except Exception:
            pass


def _resolve_sfx_dir() -> Path:
    return BASE_DIR / "SFX"


_SFX_DIR = _resolve_sfx_dir()
_HUD_FILE = _SFX_DIR / "HUD.mp3"
_START_FILE = _SFX_DIR / "Start.mp3"
_THINK_FILE = _SFX_DIR / "Think.mp3"
_DONE_FILE = _SFX_DIR / "Done.mp3"
_ERROR_FILE = _SFX_DIR / "Error.mp3"


class SoundManager:
    def __init__(self):
        self._enabled = True
        self._ambient_proc = None
        self._volume = 0.20
        self._ambient_stop = None
        self._ambient_thread = None
        self._foreground_proc = None
        self._foreground_stop = None
        self._foreground_thread = None
        self._foreground_tag = ""
        self._all_sound_procs = set()
        self._lock = threading.RLock()

    @staticmethod
    def _terminate_process(proc):
        if not proc:
            return
        try:
            proc.stop()
        except Exception:
            pass
        try:
            proc.close()
        except Exception:
            pass

    def _start_afplay(self, path: Path, volume: float):
        if not _HAS_WINMM:
            raise RuntimeError("winmm yuklenemedi")
        track = _MciTrack(path, volume)
        if not track.open():
            raise RuntimeError(f"MCI dosyayi acamadi: {path}")
        if not track.play():
            track.close()
            raise RuntimeError(f"MCI calma baslayamadi: {path}")
        with self._lock:
            self._all_sound_procs.add(track)
        return track

    def _forget_process(self, proc):
        if not proc:
            return
        try:
            proc.close()
        except Exception:
            pass
        with self._lock:
            self._all_sound_procs.discard(proc)

    def start_ambient(self):
        if not _HUD_FILE.exists():
            return
        with self._lock:
            if not self._enabled:
                return
            if self._foreground_proc and self._foreground_proc.poll() is None:
                return
            if self._ambient_thread and self._ambient_thread.is_alive():
                return
            stop_event = threading.Event()
            worker = threading.Thread(
                target=self._loop_ambient,
                args=(stop_event,),
                daemon=True,
            )
            self._ambient_stop = stop_event
            self._ambient_thread = worker
        worker.start()

    def _loop_ambient(self, stop_event: threading.Event):
        while not stop_event.is_set():
            with self._lock:
                if not self._enabled or self._ambient_stop is not stop_event:
                    break
                volume = self._volume
            try:
                proc = self._start_afplay(_HUD_FILE, volume)
            except Exception:
                break

            with self._lock:
                if self._ambient_stop is not stop_event or not self._enabled:
                    self._terminate_process(proc)
                    self._forget_process(proc)
                    break
                self._ambient_proc = proc

            while proc.is_playing() and not stop_event.wait(0.2):
                pass

            if stop_event.is_set():
                self._terminate_process(proc)

            with self._lock:
                if self._ambient_proc is proc:
                    self._ambient_proc = None
            if not proc.is_playing():
                self._forget_process(proc)

            if stop_event.is_set():
                break
            time.sleep(0.2)

        with self._lock:
            if self._ambient_stop is stop_event:
                self._ambient_stop = None
            if self._ambient_thread and self._ambient_thread.ident == threading.get_ident():
                self._ambient_thread = None

    def _stop_ambient(self):
        with self._lock:
            stop_event = self._ambient_stop
            proc = self._ambient_proc
            self._ambient_stop = None
            self._ambient_thread = None
            self._ambient_proc = None
        if stop_event:
            stop_event.set()
        self._terminate_process(proc)
        self._forget_process(proc)

    def _stop_foreground(self):
        with self._lock:
            stop_event = self._foreground_stop
            proc = self._foreground_proc
            self._foreground_stop = None
            self._foreground_thread = None
            self._foreground_proc = None
            self._foreground_tag = ""
        if stop_event:
            stop_event.set()
        self._terminate_process(proc)
        self._forget_process(proc)

    def _play_foreground(
        self,
        path: Path,
        tag: str,
        loop: bool = False,
        volume_factor: float = 1.0,
        pause_ambient: bool = True,
    ):
        if not path.exists():
            return
        with self._lock:
            if not self._enabled:
                return
            if loop and self._foreground_tag == tag and self._foreground_thread and self._foreground_thread.is_alive():
                return
            base_volume = self._volume
        if pause_ambient:
            self._stop_ambient()
        self._stop_foreground()

        stop_event = threading.Event()
        worker = threading.Thread(
            target=self._foreground_worker,
            args=(
                path,
                tag,
                stop_event,
                loop,
                max(0.0, min(1.0, base_volume * volume_factor)),
                pause_ambient,
            ),
            daemon=True,
        )
        with self._lock:
            self._foreground_stop = stop_event
            self._foreground_thread = worker
            self._foreground_tag = tag
        worker.start()

    def _foreground_worker(
        self,
        path: Path,
        tag: str,
        stop_event: threading.Event,
        loop: bool,
        volume: float,
        resume_ambient: bool,
    ):
        while not stop_event.is_set():
            try:
                proc = self._start_afplay(path, volume)
            except Exception:
                break

            with self._lock:
                if self._foreground_stop is not stop_event or not self._enabled:
                    self._terminate_process(proc)
                    self._forget_process(proc)
                    break
                self._foreground_proc = proc

            while proc.is_playing() and not stop_event.wait(0.12):
                pass

            if stop_event.is_set():
                self._terminate_process(proc)

            with self._lock:
                if self._foreground_proc is proc:
                    self._foreground_proc = None
            if not proc.is_playing():
                self._forget_process(proc)

            if not loop or stop_event.is_set():
                break
            time.sleep(0.08)

        with self._lock:
            if self._foreground_stop is stop_event:
                self._foreground_stop = None
                self._foreground_thread = None
                self._foreground_tag = ""
            should_restart = resume_ambient and self._enabled and self._foreground_stop is None
        if should_restart:
            self.start_ambient()

    def play_startup(self):
        self._play_foreground(_START_FILE, tag="start", loop=False, volume_factor=0.95)

    def play_success(self):
        self._play_foreground(
            _DONE_FILE,
            tag="done",
            loop=False,
            volume_factor=0.68,
            pause_ambient=False,
        )

    def play_error(self):
        self._play_foreground(_ERROR_FILE, tag="error", loop=False, volume_factor=0.95)

    def start_thinking(self):
        self._play_foreground(
            _THINK_FILE,
            tag="think",
            loop=True,
            volume_factor=0.82,
            pause_ambient=False,
        )

    def stop_thinking(self):
        with self._lock:
            is_thinking = self._foreground_tag == "think"
        if is_thinking:
            self._stop_foreground()

    def toggle(self) -> bool:
        self.set_enabled(not self._enabled)
        return self._enabled

    def set_enabled(self, enabled: bool):
        enabled = bool(enabled)
        with self._lock:
            self._enabled = enabled
        if enabled:
            self.start_ambient()
        else:
            self._stop_ambient()
            self._stop_foreground()

    def set_volume(self, volume: float):
        with self._lock:
            self._volume = max(0.0, min(1.0, float(volume)))
            fg_tag = self._foreground_tag
            can_restart_ambient = self._enabled and not fg_tag
        if fg_tag == "think":
            self._stop_foreground()
            self.start_thinking()
        elif can_restart_ambient:
            self._stop_ambient()
            self.start_ambient()

    def stop_all(self):
        with self._lock:
            self._enabled = False
            ambient_stop = self._ambient_stop
            foreground_stop = self._foreground_stop
            procs = {
                proc
                for proc in (
                    self._ambient_proc,
                    self._foreground_proc,
                    *self._all_sound_procs,
                )
                if proc
            }
            self._ambient_stop = None
            self._ambient_thread = None
            self._ambient_proc = None
            self._foreground_stop = None
            self._foreground_thread = None
            self._foreground_proc = None
            self._foreground_tag = ""
            self._all_sound_procs.clear()
        if ambient_stop:
            ambient_stop.set()
        if foreground_stop:
            foreground_stop.set()
        for proc in procs:
            self._terminate_process(proc)

    def get_volume(self) -> float:
        return self._volume


# ─────────────────────────────────────────────────────────────────────────────

class JarvisUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("J.A.R.V.I.S")
        assets_dir = BASE_DIR / "assets"
        try:
            icon_path = assets_dir / "sukima_icon.png"
            self._brand_icon_photo = ImageTk.PhotoImage(
                Image.open(icon_path).convert("RGBA").resize((48, 48), Image.Resampling.LANCZOS),
                master=self.root,
            )
            self.root.iconphoto(True, self._brand_icon_photo)
            self.root.iconbitmap(str(assets_dir / "sukima_icon.ico"))
        except Exception:
            self._brand_icon_photo = None
        self.root.update_idletasks()

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        margin_x = max(24, int(sw * 0.025))
        margin_y = max(54, int(sh * 0.055))
        self.W = min(max(640, sw - margin_x), sw, W_TARGET)
        self.H = min(max(520, sh - margin_y), sh, H_TARGET)
        _geo = f"{self.W}x{self.H}+{(sw-self.W)//2}+{max(0, (sh-self.H)//2 - 8)}"
        self.root.geometry(_geo)
        self.root.minsize(min(self.W, sw), min(self.H, sh))
        self.root.resizable(True, True)
        self.root.configure(bg=C_BG)
        self.root.attributes('-topmost', True)
        self.root.lift()
        self.root.focus_force()
        # macOS window manager bazen geometry'yi override eder, tekrar zorla.
        for delay in (80, 220, 600, 1200):
            self.root.after(delay, self._force_startup_size)
        # Birkaç saniye sonra topmost'u kapat (normal davranış)
        self.root.after(3000, lambda: self.root.attributes('-topmost', False))

        self._window_geometry = _geo
        self._normal_size = (self.W, self.H)
        self._fullscreen = True

        self._ui_template = str(load_app_config().get("ui_template", "sukima"))
        if self._ui_template not in UI_TEMPLATES:
            self._ui_template = "sukima"
        self._template_source = {}
        for key, filename in (("visor", "ui_visor.png"), ("tactico", "ui_tactical.png")):
            try:
                self._template_source[key] = Image.open(assets_dir / filename).convert("RGB")
            except (OSError, ValueError):
                pass
        self._template_background_photo = None
        self._set_layout_metrics(self.W, self.H)

        # ── State ────────────────────────────────────────────────────────────
        self.speaking        = False
        self.user_speaking   = False
        self.muted           = False
        self.paused          = False
        self.scale           = 1.0
        self.target_scale    = 1.0
        self.halo_a          = 55.0
        self.target_halo     = 55.0
        self.last_t          = time.time()
        self.tick            = 0
        self.rings_spin      = [0.0, 45.0, 90.0, 200.0]  # 4 ayrı halka
        self.pulse_r         = []
        self.status_blink    = True
        self._jarvis_state   = "INITIALISING"
        self._user_speaking_until = 0.0

        # ── Health overlay ───────────────────────────────────────────────────
        self._health_visible  = False
        self._health_query    = "all"
        self._health_display  = ""
        self._health_hide_job = None
        self._weather_card = {
            "city": "Alcalá de Henares",
            "primary": "--",
            "details": ["Cargando el clima..."],
        }
        self._health_card_lines = ["Vitals yükleniyor..."]
        self._panel_focus = ""
        self._panel_focus_until = 0.0
        self._brief_refresh_busy = False
        self._started_at = time.time()
        self._error_hold_until = 0.0
        self._settings_open = False
        self._settings_tab = "settings"
        self._debug_entries = deque(maxlen=160)
        self._startup_sfx_played = False
        self._startup_song_played = False
        self._startup_song_track = None
        self._flight_cameo_started = 0.0
        self._flight_cameo_duration = 12.0
        self._flight_cameo_next = time.monotonic() + random.uniform(4.0, 6.0)
        self._flight_clips = []
        clip_specs = (
            ("iron_man_flight.gif", "IRON MAN / VUELO", "VIGILANCIA JARVIS / MK III"),
            ("avengers_ironman_source.gif", "AVENGERS / COMBATE", "CLIP DE MARVEL STUDIOS"),
            ("avengers_assemble.gif", "AVENGERS / ENSAMBLE", "CLIP DE MARVEL STUDIOS"),
            ("avengers_infinity_war.gif", "AVENGERS / BATALLA", "CLIP DE MARVEL STUDIOS"),
            ("iron_man_reaction.gif", "AVENGERS / ESCENA MCU", "CLIP DE MARVEL STUDIOS"),
            ("iron_man_reveal.gif", "IRON MAN / VUELO", "ANIMACION / LOTTIEFILES"),
            ("iron_man_core_source.gif", "IRON MAN / NUCLEO", "ANIMACION / LOTTIEFILES"),
        )
        for filename, title, caption in clip_specs:
            try:
                animation = Image.open(assets_dir / filename)
                frame_ms = max(35, int(animation.info.get("duration", 50)))
                frames = []
                for frame in ImageSequence.Iterator(animation):
                    source = frame.convert("RGB")
                    if filename == "iron_man_core_source.gif":
                        w, h = source.size
                        crop_h = min(h, int(w * 9 / 16))
                        top = max(0, min(h - crop_h, int(h * 0.22)))
                        source = source.crop((0, top, w, top + crop_h))
                    source.thumbnail((218, 78), Image.Resampling.LANCZOS)
                    canvas = Image.new("RGB", (218, 78), "#10131A")
                    canvas.paste(source, ((218-source.width)//2, (78-source.height)//2))
                    frames.append(ImageTk.PhotoImage(canvas, master=self.root))
                if frames:
                    self._flight_clips.append({"title": title, "caption": caption, "frames": frames, "frame_ms": frame_ms})
            except Exception:
                continue
        self._flight_clip_index = -1
        self._flight_clip = None
        self._settings_geometry = {
            "btn_x": 14,
            "btn_y": 12,
            "btn_w": 250,
            "btn_h": 46,
            "panel_x": 14,
            "panel_y": HDR_H + 10,
            "panel_w": 320,
            "panel_h": 344,
        }
        self.setup_frame = None
        self.api_entry = None
        self.youtube_api_entry = None
        self.youtube_handle_entry = None

        # ── Callbacks ────────────────────────────────────────────────────────
        self.on_text_command = None
        self.on_pause_toggle = None
        self.on_stop_command = None
        self.on_voice_change = None
        self.on_effects_state_change = None

        # ── Voice ────────────────────────────────────────────────────────────
        self._current_voice = self._load_voice()

        # ── Sound ────────────────────────────────────────────────────────────
        self.sound = SoundManager()

        # ── Stats ────────────────────────────────────────────────────────────
        self._stats      = {'cpu': 0.0, 'ram': 0.0, 'disk': 0.0,
                            'battery': 100.0, 'net_up': 0.0, 'net_down': 0.0,
                            'ram_used': 0.0, 'ram_total': 0.0, 'processes': 0}
        self._cpu_hist   = [0.0] * 24
        self._last_net   = psutil.net_io_counters()
        self._last_net_t = time.time()
        self._wave_jarvis = [random.randint(4, 26) for _ in range(18)]
        self._wave_user   = [random.randint(2, 10) for _ in range(18)]

        # ── Typing ───────────────────────────────────────────────────────────
        self.typing_queue = deque()
        self.is_typing    = False

        # ── Partiküller (arka plan, az sayıda) ───────────────────────────────
        self.particles = [
            {
                'x':  random.uniform(0, self.W),
                'y':  random.uniform(0, self.H),
                'vx': random.uniform(-0.15, 0.15),
                'vy': random.uniform(-0.15, 0.15),
                'r':  random.uniform(0.5, 1.8),
                'a':  random.randint(15, 70),
            }
            for _ in range(24)
        ]

        self.orb_particles = [
            {
                'angle': random.uniform(0, math.tau),
                'orbit': random.uniform(0.06, 0.98),
                'speed': random.uniform(-0.030, 0.030),
                'size': random.uniform(0.8, 2.8),
                'phase': random.uniform(0, math.tau),
                'wobble': random.uniform(0.010, 0.040),
                'depth': random.uniform(0.30, 1.00),
            }
            for _ in range(160)
        ]
        self.orb_shell_particles = [
            {
                'angle': random.uniform(0, math.tau),
                'speed': random.uniform(-0.020, 0.020),
                'size': random.uniform(1.4, 3.8),
                'phase': random.uniform(0, math.tau),
                'glow': random.uniform(0.4, 1.0),
            }
            for _ in range(84)
        ]

        # ── Canvas ───────────────────────────────────────────────────────────
        self.bg = tk.Canvas(self.root, width=self.W, height=self.H,
                            bg=C_BG, highlightthickness=0)
        self.bg.place(x=0, y=0)
        self.bg.tag_bind("weather_city", "<Button-1>", self._edit_weather_location)

        # ── Log ──────────────────────────────────────────────────────────────
        self.log_frame = tk.Frame(self.root, bg=C_PANEL,
                                  highlightbackground=C_MID,
                                  highlightthickness=1)
        self.log_frame.place(x=self.CHAT_X, y=self.CHAT_Y,
                             width=self.CHAT_W, height=self.CHAT_H)
        self.log_text = tk.Text(
            self.log_frame, fg=C_TEXT, bg=C_PANEL,
            insertbackground=C_TEXT, borderwidth=0,
            wrap="word", font=font_body(12), padx=12, pady=8)
        self.log_text.pack(fill="both", expand=True)
        self.log_text.configure(state="disabled")
        self.log_text.tag_config("you", foreground="#E9E0CE")
        self.log_text.tag_config("ai",  foreground=C_PRI)
        self.log_text.tag_config("sys", foreground=C_GOLD)
        self.log_text.tag_config("err", foreground=C_RED)

        self._build_input_bar(self.CHAT_W)
        self._build_mute_button()
        self._build_pause_button()
        self._build_shutdown_button()
        self._build_settings_panel()
        self._build_voice_selector(self._settings_body)
        self._build_template_selector(self._settings_body)
        self._build_sfx_button(self._settings_body)
        self._build_api_button(self._settings_body)
        self._build_fx_slider(self._settings_body)
        self._layout_settings_controls()
        self._place_layout_widgets()

        # Orb tıklama = pause/resume
        self.bg.bind("<Button-1>", self._on_canvas_click)

        self.root.bind("<F4>",        lambda e: self._toggle_mute())
        self.root.bind("<Command-m>", lambda e: self._toggle_mute())
        self.root.bind("<Escape>",    lambda e: self._shutdown())
        self.root.bind("<F5>",        lambda e: self._toggle_pause())
        self.root.bind("<F6>",        lambda e: self._cycle_ui_template())
        self.root.bind("<F11>",       lambda e: self._toggle_fullscreen())
        self.root.bind("<Command-f>", lambda e: self._toggle_fullscreen())

        self._mini_window = None
        self._mini_visible = False
        self._mini_last_log = ""
        self._build_mini_window()
        self.root.bind("<F9>", lambda e: self._toggle_mini_window())

        self._api_key_ready = has_runtime_credentials()
        if not self._api_key_ready:
            self._show_setup_ui()

        self._effects_active = None
        self._sync_sound_state()
        self.root.after(180, self._play_startup_sfx_once)
        self._kick_brief_refresh()
        self._build_social_bar()
        self.root.after(120, self._enter_fullscreen)
        self._animate()
        self.root.protocol("WM_DELETE_WINDOW", self._shutdown)

    def _force_startup_size(self):
        if self._fullscreen:
            self._enter_fullscreen()
            return
        self.root.geometry(self._window_geometry)
        self._resize_surface(*self._normal_size)
        self.root.update_idletasks()

    def _enter_fullscreen(self):
        sw = max(self.root.winfo_screenwidth(), self.root.winfo_width(), self.W)
        sh = max(self.root.winfo_screenheight(), self.root.winfo_height(), self.H)
        self.root.attributes("-fullscreen", True)
        self.root.geometry(f"{sw}x{sh}+0+0")
        self._resize_surface(sw, sh)

    def _set_layout_metrics(self, width: int, height: int):
        self.W = int(width)
        self.H = int(height)
        self.LEFT_W = min(LEFT_W_T, max(280, int(self.W * 0.25)))
        self.RIGHT_W = min(RIGHT_W_T, max(330, int(self.W * 0.27)))
        center_w = self.W - self.LEFT_W - self.RIGHT_W
        orb_area_h = self.H - HDR_H - CONTROL_H - FOOTER_H - 24
        self.FCX = self.LEFT_W + center_w // 2
        self.FCY = HDR_H + orb_area_h // 2 + 6
        self.FACE = min(int(orb_area_h * 0.90), int(center_w * 0.86), 860)

        self.CENTER_X0 = self.LEFT_W
        self.CENTER_X1 = self.W - self.RIGHT_W
        self.CTRL_X = self.LEFT_W + 18
        self.CTRL_Y = HDR_H + orb_area_h + 2
        self.CTRL_W = center_w - 36
        self.CHAT_PANEL_X = self.W - self.RIGHT_W + 8
        self.CHAT_PANEL_Y = HDR_H + 8
        self.CHAT_PANEL_W = self.RIGHT_W - 14
        self.CHAT_PANEL_H = self.H - HDR_H - FOOTER_H - 16
        self.CHAT_X = self.CHAT_PANEL_X + 10
        self.CHAT_Y = self.CHAT_PANEL_Y + 34
        self.CHAT_W = self.CHAT_PANEL_W - 20
        self.CHAT_H = self.CHAT_PANEL_H - 90
        self.CHAT_INPUT_Y = self.CHAT_PANEL_Y + self.CHAT_PANEL_H - INPUT_H - 10

    # ── Social bar ───────────────────────────────────────────────────────────
    def _build_social_bar(self):
        ICON_SIZE = 28
        ICON_DIR  = BASE_DIR / "Icon"

        bar = tk.Frame(self.root, bg=C_BG)
        self._social_bar = bar
        bar.place_forget()

        def _open(url):
            def _handler(_e, _u=url):
                try:
                    os.startfile(_u)
                except OSError:
                    webbrowser.open(_u, new=2)
            return _handler

        def _load_icon(filename: str):
            try:
                img = Image.open(ICON_DIR / filename).convert("RGBA")
                img = img.resize((ICON_SIZE, ICON_SIZE), Image.LANCZOS)
                return ImageTk.PhotoImage(img)
            except Exception:
                return None

        name_lbl = tk.Label(
            bar, text="SUKIMA LABS",
            fg=C_PRI, bg=C_BG,
            font=font_display(11), justify="left",
        )
        name_lbl.pack(side="left", padx=(0, 10))

    # ── Voice ─────────────────────────────────────────────────────────────────
    def _load_voice(self) -> str:
        try:
            return str(load_app_config().get("voice", "Charon") or "Charon")
        except Exception:
            return "Charon"

    # ── Shutdown button (sağ alt, büyük) ────────────────────────────────────
    def _build_shutdown_button(self):
        BW, BH = 140, 36
        self._shutdown_canvas = tk.Canvas(
            self.root, width=BW, height=BH,
            bg=C_BG, highlightthickness=0, cursor="hand2")
        self._shutdown_canvas.bind("<Button-1>", lambda e: self._shutdown())
        self._draw_shutdown_button()

    def _draw_shutdown_button(self):
        c = self._shutdown_canvas
        BW, BH = 140, 36
        c.delete("all")
        # Köşe braket stili
        bl = 8
        for bx, by, sx, sy in [(0, 0, 1, 1), (BW, 0, -1, 1),
                                (0, BH, 1, -1), (BW, BH, -1, -1)]:
            c.create_line(bx, by, bx+sx*bl, by, fill=C_RED, width=2)
            c.create_line(bx, by, bx, by+sy*bl, fill=C_RED, width=2)
        c.create_text(BW//2, BH//2, text="⏻  APAGAR",
                      fill=C_RED, font=font_display(11))

    def _build_settings_panel(self):
        geo = self._settings_geometry
        self._settings_btn_canvas = tk.Canvas(
            self.root,
            width=geo["btn_w"],
            height=geo["btn_h"],
            bg=C_BG,
            highlightthickness=0,
            cursor="hand2",
        )
        self._settings_btn_canvas.place(x=geo["btn_x"], y=geo["btn_y"])
        self._settings_btn_canvas.bind("<Button-1>", lambda e: self._toggle_settings_panel())
        self._draw_settings_button()

        self._settings_panel = tk.Frame(
            self.root,
            bg="#171922",
            highlightbackground=C_MID,
            highlightthickness=1,
        )
        self._settings_panel.place_forget()

        self._settings_title = tk.Label(
            self._settings_panel,
            text="AJUSTES",
            fg=C_PRI,
            bg="#171922",
            font=font_display(11),
        )
        self._settings_tab_settings = tk.Canvas(
            self._settings_panel,
            width=108,
            height=28,
            bg="#171922",
            highlightthickness=0,
            cursor="hand2",
        )
        self._settings_tab_settings.bind("<Button-1>", lambda e: self._set_settings_tab("settings"))
        self._settings_tab_debug = tk.Canvas(
            self._settings_panel,
            width=96,
            height=28,
            bg="#171922",
            highlightthickness=0,
            cursor="hand2",
        )
        self._settings_tab_debug.bind("<Button-1>", lambda e: self._set_settings_tab("debug"))
        self._settings_body = tk.Frame(self._settings_panel, bg="#171922")
        self._debug_body = tk.Frame(self._settings_panel, bg="#171922")
        self._settings_sfx_label = tk.Label(
            self._settings_body,
            text="EFECTOS",
            fg=C_MID,
            bg="#171922",
            font=font_body_bold(8),
        )
        self._settings_status_primary = tk.Label(
            self._settings_body,
            text="",
            fg=C_TEXT,
            bg="#171922",
            font=font_body_bold(9),
            anchor="w",
            justify="left",
        )
        self._settings_status_secondary = tk.Label(
            self._settings_body,
            text="",
            fg=C_MID,
            bg="#171922",
            font=font_body(9),
            anchor="w",
            justify="left",
        )
        self._debug_text = tk.Text(
            self._debug_body,
            fg=C_TEXT,
            bg="#171922",
            insertbackground=C_TEXT,
            borderwidth=0,
            wrap="word",
            font=font_body(10),
            padx=10,
            pady=10,
            highlightthickness=1,
            highlightbackground=C_DIM,
        )
        self._debug_text.tag_config("info", foreground=C_TEXT)
        self._debug_text.tag_config("warn", foreground=C_GOLD)
        self._debug_text.tag_config("err", foreground=C_RED)
        self._debug_text.configure(state="disabled")
        self._draw_settings_tabs()
        self._render_debug_logs()
        self._refresh_settings_status()

    def _draw_settings_button(self):
        c = self._settings_btn_canvas
        bw = int(c["width"])
        bh = int(c["height"])
        c.delete("all")
        accent = C_BLUE if self._settings_open else C_MID
        inner = "#242129" if self._settings_open else "#171922"
        c.create_rectangle(0, 0, bw, bh, fill=inner, outline="")
        bl = 9
        for bx, by, sx, sy in [(0, 0, 1, 1), (bw, 0, -1, 1), (0, bh, 1, -1), (bw, bh, -1, -1)]:
            c.create_line(bx, by, bx + sx * bl, by, fill=accent, width=2)
            c.create_line(bx, by, bx, by + sy * bl, fill=accent, width=2)
        c.create_text(14, 15, text="CONFIGURACIÓN", fill=C_PRI, font=font_display(10), anchor="w")
        c.create_text(14, 33, text=MODEL_BADGE, fill="#A79B87", font=font_body(9), anchor="w")
        c.create_text(bw - 14, bh // 2, text="▾" if self._settings_open else "▸",
                      fill=accent, font=font_display(14), anchor="e")

    def _toggle_settings_panel(self):
        self._settings_open = not self._settings_open
        self._draw_settings_button()
        self._place_layout_widgets()

    def _draw_settings_tabs(self):
        for key, canvas, label in (
            ("settings", self._settings_tab_settings, "AJUSTES"),
            ("debug", self._settings_tab_debug, "REGISTRO"),
        ):
            active = self._settings_tab == key
            bw = int(canvas["width"])
            bh = int(canvas["height"])
            canvas.delete("all")
            outline = C_PRI if active else C_DIM
            fill = "#28232A" if active else "#171922"
            text_col = C_PRI if active else "#B99A64"
            canvas.create_rectangle(0, 0, bw, bh, fill=fill, outline="")
            bl = 7
            for bx, by, sx, sy in [(0, 0, 1, 1), (bw, 0, -1, 1), (0, bh, 1, -1), (bw, bh, -1, -1)]:
                canvas.create_line(bx, by, bx + sx * bl, by, fill=outline, width=1)
                canvas.create_line(bx, by, bx, by + sy * bl, fill=outline, width=1)
            canvas.create_text(bw // 2, bh // 2, text=label, fill=text_col, font=font_body_bold(9))

    def _set_settings_tab(self, tab: str):
        self._settings_tab = "debug" if tab == "debug" else "settings"
        self._draw_settings_tabs()
        self._place_layout_widgets()

    def _layout_settings_controls(self):
        inner_w = self._settings_geometry["panel_w"] - 24
        self._api_canvas.place(x=0, y=2)
        self._sfx_canvas.place(x=inner_w - int(self._sfx_canvas["width"]) - 4, y=0)
        self._settings_status_primary.place(x=0, y=38, width=inner_w)
        self._settings_status_secondary.place(x=0, y=58, width=inner_w)
        self._settings_sfx_label.place(x=0, y=92)
        self._volume_label.place(x=0, y=116)
        self._volume_scale.place(x=0, y=136, width=inner_w, height=26)
        self._voice_label.place(x=0, y=178)
        self._voice_menu.place(x=88, y=172, width=inner_w - 88, height=30)
        self._template_label.place(x=0, y=216)
        self._template_menu.place(x=88, y=210, width=inner_w - 88, height=30)

    def _refresh_settings_status(self):
        if not hasattr(self, "_settings_status_primary"):
            return
        cfg = load_app_config()
        gemini_ready = bool(str(cfg.get("gemini_api_key", "") or "").strip())
        yt_key_ready = bool(str(cfg.get("youtube_api_key", "") or "").strip())
        yt_handle = str(cfg.get("youtube_channel_handle", "") or "").strip()

        primary = [
            "Gemini listo" if gemini_ready else "Falta la clave de Gemini",
            "YouTube listo" if yt_key_ready and yt_handle else "Falta configurar YouTube",
        ]
        if yt_handle:
            handle_text = yt_handle
        else:
            handle_text = "no configurado"
        secondary = f"Canal: {handle_text}"

        self._settings_status_primary.configure(text="  ·  ".join(primary))
        self._settings_status_secondary.configure(text=secondary)

    def write_debug(self, text: str, level: str = "INFO"):
        clean = " ".join(str(text or "").split())
        if not clean:
            return
        self.root.after(0, self._append_debug_entry, clean, level)

    def _append_debug_entry(self, text: str, level: str = "INFO"):
        stamp = time.strftime("%H:%M:%S")
        lvl = (level or "INFO").upper()
        self._debug_entries.append((lvl, f"[{stamp}] {lvl}: {text}"))
        self._render_debug_logs()

    def _render_debug_logs(self):
        if not hasattr(self, "_debug_text"):
            return
        self._debug_text.configure(state="normal")
        self._debug_text.delete("1.0", tk.END)
        if not self._debug_entries:
            self._debug_text.insert(tk.END, "Henüz not edilebilir hata yok.\n", "info")
        else:
            for level, line in self._debug_entries:
                tag = "err" if level == "ERROR" else "warn" if level == "WARN" else "info"
                self._debug_text.insert(tk.END, line + "\n", tag)
        self._debug_text.see(tk.END)
        self._debug_text.configure(state="disabled")

    def _build_api_button(self, parent=None):
        parent = parent or self.root
        bw, bh = 154, 28
        self._api_canvas = tk.Canvas(
            parent, width=bw, height=bh,
            bg=parent.cget("bg"), highlightthickness=0, cursor="hand2")
        self._api_canvas.bind("<Button-1>", lambda e: self._open_api_settings())
        self._draw_api_button()

    def _draw_api_button(self):
        c = self._api_canvas
        bw = int(c["width"])
        bh = int(c["height"])
        c.delete("all")
        bl = 6
        for bx, by, sx, sy in [(0, 0, 1, 1), (bw, 0, -1, 1), (0, bh, 1, -1), (bw, bh, -1, -1)]:
            c.create_line(bx, by, bx + sx * bl, by, fill=C_BLUE, width=1)
            c.create_line(bx, by, bx, by + sy * bl, fill=C_BLUE, width=1)
        c.create_text(bw // 2, bh // 2, text="⌘ CLAVES API",
                      fill=C_BLUE, font=font_body_bold(10))

    def _build_fx_slider(self, parent=None):
        parent = parent or self.root
        slider_w = 280
        self._volume_label = tk.Label(
            parent,
            text=f"EFECTOS  {int(self.sound.get_volume() * 100)}%",
            fg=C_PRI,
            bg=parent.cget("bg"),
            font=font_body_bold(10),
        )
        self._volume_scale = tk.Scale(
            parent,
            from_=0,
            to=100,
            orient="horizontal",
            length=slider_w,
            showvalue=False,
            resolution=1,
            troughcolor="#39343D",
            bg=parent.cget("bg"),
            fg=C_TEXT,
            activebackground=C_PRI,
            highlightthickness=0,
            borderwidth=0,
            sliderlength=18,
            width=10,
            command=self._on_volume_change,
        )
        self._volume_scale.set(int(self.sound.get_volume() * 100))

    def _on_volume_change(self, value):
        try:
            volume = max(0, min(100, int(float(value))))
        except (TypeError, ValueError):
            return
        self._volume_label.configure(text=f"EFECTOS  {volume}%")
        self.sound.set_volume(volume / 100.0)

    def _play_startup_sfx_once(self):
        pass

    def _play_startup_song_once(self):
        """Reproduce el audio adjunto y lo desvanece sin abrir otra aplicación."""
        if self._startup_song_played:
            return
        self._startup_song_played = True
        song_path = BASE_DIR / "assets" / "back_in_black_intro.mpeg"
        if not song_path.is_file():
            self.write_log("ERR: No encuentro el audio de inicio adjunto.")
            return

        track = _MciTrack(song_path, volume=0.36)
        if not track.open() or not track.play():
            track.close()
            self.write_log("ERR: Windows no pudo reproducir el audio de inicio.")
            return

        self._startup_song_track = track
        self.root.after(25000, self._fade_startup_song)

    def start_startup_song_after_greeting(self):
        """Programa la música después de que el saludo de Gemini termine."""
        try:
            self.root.after(650, self._play_startup_song_once)
        except tk.TclError:
            pass

    def _fade_startup_song(self):
        track = self._startup_song_track
        if not track:
            return
        fade_started = time.monotonic()
        fade_seconds = 35.0
        start_volume = 0.36
        quiet_volume = 0.045

        def step():
            current = self._startup_song_track
            if current is not track:
                return
            if not current.is_playing():
                current.close()
                self._startup_song_track = None
                return
            progress = min(1.0, (time.monotonic() - fade_started) / fade_seconds)
            current.set_volume(start_volume + (quiet_volume - start_volume) * progress)
            if progress >= 1.0:
                self.root.after(8000, self._stop_startup_song)
                return
            self.root.after(160, step)

        step()

    def _stop_startup_song(self):
        track = self._startup_song_track
        if track:
            track.stop()
            track.close()
            self._startup_song_track = None

    def _restore_main_window(self):
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
        except tk.TclError:
            pass

    def _sync_sound_state(self):
        enabled = self._sfx_on and not self.paused
        self.sound.set_enabled(enabled)
        if enabled and self._jarvis_state == "THINKING":
            self.sound.start_thinking()
        if enabled != self._effects_active:
            self._effects_active = enabled
            if self.on_effects_state_change:
                threading.Thread(
                    target=self.on_effects_state_change,
                    args=(enabled,),
                    daemon=True,
                ).start()

    def _open_api_settings(self):
        self._show_setup_ui(edit_mode=self._api_key_ready)

    def _close_setup_ui(self):
        if self.setup_frame and self.setup_frame.winfo_exists():
            self.setup_frame.destroy()
        self.setup_frame = None
        self.api_entry = None
        self.youtube_api_entry = None
        self.youtube_handle_entry = None

    # ── SFX toggle ───────────────────────────────────────────────────────────
    def _build_sfx_button(self, parent=None):
        parent = parent or self.root
        BW, BH = 98, 36
        self._sfx_canvas = tk.Canvas(parent, width=BW, height=BH,
                                     bg=parent.cget("bg"), highlightthickness=0, cursor="hand2")
        self._sfx_canvas.bind("<Button-1>", lambda e: self._toggle_sfx())
        self._sfx_on = True
        self._draw_sfx_button()

    def _draw_sfx_button(self):
        c = self._sfx_canvas
        BW = int(c["width"])
        BH = int(c["height"])
        c.delete("all")
        col  = C_PRI if self._sfx_on else C_MID
        text = "♪ EFECTOS ACTIVOS" if self._sfx_on else "♪ EFECTOS INACTIVOS"
        bl = 6
        for bx, by, sx, sy in [(0, 0, 1, 1), (BW, 0, -1, 1),
                                (0, BH, 1, -1), (BW, BH, -1, -1)]:
            c.create_line(bx, by, bx+sx*bl, by, fill=col, width=1)
            c.create_line(bx, by, bx, by+sy*bl, fill=col, width=1)
        c.create_text(BW//2, BH//2, text=text, fill=col, font=font_body_bold(9))

    def _toggle_sfx(self):
        self._sfx_on = not self._sfx_on
        self._draw_sfx_button()
        self._sync_sound_state()

    # ── Voice selector ───────────────────────────────────────────────────────
    def _build_voice_selector(self, parent=None):
        parent = parent or self.root
        self._voice_var = tk.StringVar(value=self._current_voice)
        self._voice_label = tk.Label(parent, text="VOZ", fg=C_MID, bg=parent.cget("bg"),
                                     font=font_body_bold(8))

        self._voice_menu = tk.OptionMenu(parent, self._voice_var, *VOICES,
                                         command=self._on_voice_select)
        self._voice_menu.config(
            fg=C_PRI, bg=C_PANEL, activeforeground=C_BG,
            activebackground=C_PRI, font=font_body(10),
            borderwidth=0, highlightthickness=1,
            highlightbackground=C_MID, width=12)
        self._voice_menu["menu"].config(
            fg=C_PRI, bg=C_PANEL, font=font_body(10),
            activeforeground=C_BG, activebackground=C_PRI)

    def _on_voice_select(self, voice: str):
        self._current_voice = voice
        save_app_config({"voice": voice})
        if self.on_voice_change:
            threading.Thread(target=self.on_voice_change, args=(voice,), daemon=True).start()

    def _build_template_selector(self, parent):
        self._template_var = tk.StringVar(value=UI_TEMPLATES[self._ui_template])
        self._template_label = tk.Label(parent, text="INTERFAZ", fg=C_MID,
                                        bg=parent.cget("bg"), font=font_body_bold(8))
        self._template_menu = tk.OptionMenu(parent, self._template_var,
                                            *UI_TEMPLATES.values(), command=self._on_template_select)
        self._template_menu.config(fg=C_PRI, bg=C_PANEL, activeforeground=C_BG,
                                   activebackground=C_PRI, font=font_body(10),
                                   borderwidth=0, highlightthickness=1,
                                   highlightbackground=C_MID)
        self._template_menu["menu"].config(fg=C_PRI, bg=C_PANEL, font=font_body(10),
                                            activeforeground=C_BG, activebackground=C_PRI)

    def _on_template_select(self, label):
        key = next((name for name, value in UI_TEMPLATES.items() if value == label), "sukima")
        self._set_ui_template(key)

    def _cycle_ui_template(self):
        keys = tuple(UI_TEMPLATES)
        self._set_ui_template(keys[(keys.index(self._ui_template) + 1) % len(keys)])

    def _set_ui_template(self, key):
        if key not in UI_TEMPLATES or key == self._ui_template:
            return
        self._ui_template = key
        self._template_var.set(UI_TEMPLATES[key])
        save_app_config({"ui_template": key})
        self._refresh_template_background()
        self._draw()

    def _refresh_template_background(self):
        source = self._template_source.get(self._ui_template)
        self._template_background_photo = None
        if source is None:
            return
        target = source.resize((self.W, self.H), Image.Resampling.LANCZOS)
        target = ImageEnhance.Brightness(target).enhance(0.52 if self._ui_template == "visor" else 0.60)
        self._template_background_photo = ImageTk.PhotoImage(target, master=self.root)

    # ── Mute button ──────────────────────────────────────────────────────────
    def _build_mute_button(self):
        self._mute_canvas = tk.Canvas(self.root, width=126, height=36,
                                      bg=C_BG, highlightthickness=0, cursor="hand2")
        self._mute_canvas.bind("<Button-1>", lambda e: self._toggle_mute())
        self._draw_mute_button()

    def _draw_mute_button(self):
        c = self._mute_canvas
        bw = int(c["width"])
        bh = int(c["height"])
        c.delete("all")
        if self.muted:
            col, icon, lbl = C_MUTED, "🔇", " SILENCIADO"
        else:
            col, icon, lbl = C_GREEN, "🎙", " ACTIVO"
        bl = 6
        for bx, by, sx, sy in [(0, 0, 1, 1), (bw, 0, -1, 1),
                                (0, bh, 1, -1), (bw, bh, -1, -1)]:
            c.create_line(bx, by, bx+sx*bl, by, fill=col, width=2)
            c.create_line(bx, by, bx, by+sy*bl, fill=col, width=2)
        c.create_text(bw//2, bh//2, text=f"{icon}{lbl}",
                      fill=col, font=font_body_bold(11))

    def _build_pause_button(self):
        self._pause_canvas = tk.Canvas(self.root, width=126, height=36,
                                       bg=C_BG, highlightthickness=0, cursor="hand2")
        self._pause_canvas.bind("<Button-1>", lambda e: self._toggle_pause())
        self._draw_pause_button()

    def _draw_pause_button(self):
        c = self._pause_canvas
        bw = int(c["width"])
        bh = int(c["height"])
        c.delete("all")
        if self.paused:
            col, text = C_GOLD, "▶ REANUDAR"
        else:
            col, text = C_BLUE, "⏸ PAUSAR"
        bl = 6
        for bx, by, sx, sy in [(0, 0, 1, 1), (bw, 0, -1, 1),
                               (0, bh, 1, -1), (bw, bh, -1, -1)]:
            c.create_line(bx, by, bx+sx*bl, by, fill=col, width=2)
            c.create_line(bx, by, bx, by+sy*bl, fill=col, width=2)
        c.create_text(bw//2, bh//2, text=text, fill=col, font=font_body_bold(11))

    def _toggle_mute(self):
        self.muted = not self.muted
        self._draw_mute_button()
        if self.muted:
            self.write_log("SYS: Micrófono silenciado.")
        else:
            self.write_log("SYS: Micrófono activo.")
        self._sync_sound_state()
        if hasattr(self, "_mini_refresh_mute_btn"):
            self._mini_refresh_mute_btn()

    # ── Orb tıklama = pause ──────────────────────────────────────────────────
    def _on_canvas_click(self, event):
        dx = event.x - self.FCX
        dy = event.y - self.FCY
        if dx*dx + dy*dy <= (self.FACE * 0.40)**2:
            self._toggle_pause()

    def _toggle_pause(self):
        self.paused = not self.paused
        self._draw_pause_button()
        if self.paused:
            self.set_state("PAUSED")
            self.write_log("SYS: JARVIS está en pausa.")
        else:
            self.set_state("THINKING")
            self.write_log("SYS: JARVIS reanudado.")
        self._sync_sound_state()
        if self.on_pause_toggle:
            threading.Thread(target=self.on_pause_toggle, args=(self.paused,), daemon=True).start()

    def _shutdown(self):
        if self._startup_song_track:
            self._startup_song_track.stop()
            self._startup_song_track.close()
            self._startup_song_track = None
        self.sound.stop_all()
        self.write_log("SYS: Cerrando JARVIS...")
        self.root.after(380, os._exit, 0)

    def _toggle_fullscreen(self):
        self._fullscreen = not self._fullscreen
        if self._fullscreen:
            self._enter_fullscreen()
        else:
            self.root.attributes("-fullscreen", False)
            self.root.geometry(self._window_geometry)
            self._resize_surface(*self._normal_size)

    def _resize_surface(self, width: int, height: int):
        self._set_layout_metrics(width, height)
        self._refresh_template_background()
        self.bg.configure(width=self.W, height=self.H)
        self.bg.place(x=0, y=0)
        self._place_layout_widgets()
        if hasattr(self, "_social_bar"):
            self._social_bar.place_forget()
        for p in self.particles:
            p["x"] %= self.W
            p["y"] %= self.H

    # ── Mini floating window ─────────────────────────────────────────────────
    MINI_W = 340
    MINI_H_COMPACT = 168
    MINI_H_EXPANDED = 450

    def _build_mini_window(self):
        win = tk.Toplevel(self.root)
        win.withdraw()
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        try:
            win.attributes("-alpha", 0.97)
        except tk.TclError:
            pass

        MINI_BG = "#171922"
        MINI_ACCENT = C_DIM
        MINI_MUTED = "#836A46"
        MINI_SOFT = "#242129"
        # Glyph-safe fontlar (Windows'ta her zaman var)
        ICON_FONT = "Segoe UI Symbol"
        EMOJI_FONT = "Segoe UI Emoji"

        MW, MH = self.MINI_W, self.MINI_H_COMPACT
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        win.geometry(f"{MW}x{MH}+{sw - MW - 28}+{sh - MH - 72}")
        win.configure(bg=MINI_BG)

        # ── State containers ─────────────────────────────────────────────
        self._mini_history = deque(maxlen=80)
        self._mini_chat_open = False
        self._mini_topmost = True
        self._mini_anim_phase = 0.0
        self._mini_orb_phase = 0.0
        self._mini_pulse_job = None
        self._mini_anim_job = None

        outer = tk.Frame(win, bg=MINI_BG,
                         highlightbackground=MINI_ACCENT,
                         highlightthickness=1)
        outer.pack(fill="both", expand=True)

        # ── Top bar: orb + state + pin + expand + drag + close ───────────
        top = tk.Frame(outer, bg=MINI_BG, height=40)
        top.pack(fill="x", side="top", padx=10, pady=(8, 0))
        top.pack_propagate(False)

        orb = tk.Canvas(top, width=32, height=32, bg=MINI_BG,
                        highlightthickness=0)
        orb.pack(side="left", padx=(2, 8))

        orb_ring1 = orb.create_arc(2, 2, 30, 30, start=20, extent=140,
                                   style="arc", outline=C_PRI, width=2)
        orb_ring2 = orb.create_arc(6, 6, 26, 26, start=200, extent=110,
                                   style="arc", outline=C_MID, width=1)
        orb_core = orb.create_oval(12, 12, 20, 20, fill=C_GREEN, outline="")

        state_lbl = tk.Label(
            top, text=self._spaced_caps("ESCUCHANDO"),
            fg=C_GREEN, bg=MINI_BG,
            font=(FONT_BODY_FAMILY, 8, "bold"))
        state_lbl.pack(side="left", anchor="w")

        # Right-side icon factory
        def _icon_btn(parent, glyph, cmd, color=MINI_MUTED,
                      size=12, hover=C_PRI, font_family=ICON_FONT,
                      side="right"):
            b = tk.Label(parent, text=glyph, fg=color, bg=MINI_BG,
                         font=(font_family, size, "bold"),
                         cursor="hand2", padx=4)
            b.pack(side=side)
            b.bind("<Button-1>", lambda e: cmd())
            b.bind("<Enter>", lambda e: b.configure(fg=hover))
            b.bind("<Leave>", lambda e: b.configure(fg=color))
            return b

        close_btn = _icon_btn(top, "×", self._toggle_mini_window,
                              size=15, hover=C_RED,
                              font_family=FONT_BODY_FAMILY)
        pin_btn = _icon_btn(top, "📌", self._mini_toggle_pin,
                            color=C_PRI, size=11,
                            font_family=EMOJI_FONT)
        expand_btn = _icon_btn(top, "▼", self._mini_toggle_chat,
                               size=11)
        drag_handle = tk.Label(top, text="⋮⋮", fg=MINI_MUTED, bg=MINI_BG,
                               font=(ICON_FONT, 10), cursor="fleur")
        drag_handle.pack(side="right", padx=(2, 6))

        # ── Middle: state-aware animation strip ──────────────────────────
        mid = tk.Frame(outer, bg=MINI_BG, height=26)
        mid.pack(fill="x", side="top", padx=12, pady=(4, 0))
        mid.pack_propagate(False)

        anim = tk.Canvas(mid, height=22, bg=MINI_BG, highlightthickness=0)
        anim.pack(fill="x", expand=True)

        # ── Last message line ────────────────────────────────────────────
        log_lbl = tk.Label(
            outer, text="JARVIS listo. Te escucho.",
            fg=MINI_MUTED, bg=MINI_BG,
            font=font_body(9),
            anchor="w", justify="left", wraplength=MW - 28)
        log_lbl.pack(fill="x", side="top", padx=12, pady=(2, 0))

        # ── Chat history (hidden until expanded) ─────────────────────────
        chat_frame = tk.Frame(outer, bg=MINI_BG)

        chat_text = tk.Text(
            chat_frame, bg=MINI_SOFT, fg=C_TEXT,
            font=font_body(9), relief="flat", borderwidth=0,
            highlightthickness=1, highlightbackground=MINI_ACCENT,
            highlightcolor=C_PRI, wrap="word",
            padx=8, pady=6, height=12)
        chat_scroll = tk.Scrollbar(chat_frame, command=chat_text.yview,
                                   width=8, bg=MINI_BG,
                                   troughcolor=MINI_BG,
                                   activebackground=C_PRI,
                                   borderwidth=0, highlightthickness=0)
        chat_text.configure(yscrollcommand=chat_scroll.set, state="disabled")
        chat_text.tag_configure("you", foreground="#E9E0CE")
        chat_text.tag_configure("ai", foreground=C_PRI)
        chat_text.tag_configure("sys", foreground=MINI_MUTED)
        chat_text.tag_configure("err", foreground=C_RED)
        chat_scroll.pack(side="right", fill="y")
        chat_text.pack(side="left", fill="both", expand=True)

        # ── Quick actions row ────────────────────────────────────────────
        actions = tk.Frame(outer, bg=MINI_BG, height=24)
        actions.pack(fill="x", side="top", padx=12, pady=(6, 0))
        actions.pack_propagate(False)

        def _q(glyph, cmd, color=MINI_MUTED, font_family=ICON_FONT, size=12):
            b = tk.Label(actions, text=glyph, fg=color, bg=MINI_BG,
                         font=(font_family, size, "bold"),
                         cursor="hand2", padx=6)
            b.pack(side="left", padx=(0, 6))
            b.bind("<Button-1>", lambda e: cmd())
            b.bind("<Enter>", lambda e: b.configure(fg=C_PRI))
            b.bind("<Leave>", lambda e: b.configure(fg=color))
            return b

        # 🎤 mic toggle (mute), ⏸ pause, ⏹ stop voice, ⌫ clear chat
        mute_btn = _q("🎤", self._toggle_mute,
                      font_family=EMOJI_FONT, size=11)
        pause_btn = _q("⏸", self._toggle_pause)
        stop_btn = _q("⏹", self._mini_stop_voice)
        clear_btn = _q("⌫", self._mini_clear_chat)

        main_btn = tk.Label(actions, text="⛶", fg=MINI_MUTED, bg=MINI_BG,
                            font=(ICON_FONT, 12, "bold"),
                            cursor="hand2", padx=6)
        main_btn.pack(side="right")
        main_btn.bind("<Button-1>",
                      lambda e: self._toggle_mini_window())
        main_btn.bind("<Enter>", lambda e: main_btn.configure(fg=C_PRI))
        main_btn.bind("<Leave>", lambda e: main_btn.configure(fg=MINI_MUTED))

        # ── Input row ────────────────────────────────────────────────────
        bot = tk.Frame(outer, bg=MINI_BG)
        bot.pack(fill="x", side="bottom", padx=12, pady=(6, 10))

        prompt_lbl = tk.Label(bot, text="›", fg=C_PRI, bg=MINI_BG,
                              font=(FONT_BODY_FAMILY, 13, "bold"))
        prompt_lbl.pack(side="left", padx=(0, 6))

        entry_var = tk.StringVar()
        entry = tk.Entry(
            bot, textvariable=entry_var,
            fg=C_TEXT, bg=MINI_SOFT, insertbackground=C_PRI,
            relief="flat", borderwidth=0, font=font_body(10),
            highlightthickness=1, highlightbackground=MINI_ACCENT,
            highlightcolor=C_PRI)
        entry.pack(fill="x", side="left", expand=True, ipady=3)

        send_lbl = tk.Label(bot, text="↵", fg=C_PRI, bg=MINI_BG,
                            font=(ICON_FONT, 12, "bold"),
                            cursor="hand2", padx=6)
        send_lbl.pack(side="left", padx=(6, 0))

        # ── Dragging ─────────────────────────────────────────────────────
        def _start_drag(event):
            win._drag_x = event.x_root - win.winfo_x()
            win._drag_y = event.y_root - win.winfo_y()
            try:
                win.attributes("-alpha", 0.85)
            except tk.TclError:
                pass

        def _do_drag(event):
            x = event.x_root - getattr(win, "_drag_x", 0)
            y = event.y_root - getattr(win, "_drag_y", 0)
            win.geometry(f"+{x}+{y}")

        def _end_drag(event):
            try:
                win.attributes("-alpha", 0.97)
            except tk.TclError:
                pass

        for w in (outer, top, mid, drag_handle, state_lbl, log_lbl, orb):
            w.bind("<Button-1>", _start_drag)
            w.bind("<B1-Motion>", _do_drag)
            w.bind("<ButtonRelease-1>", _end_drag)

        # ── Submit ───────────────────────────────────────────────────────
        def _submit(event=None):
            text = entry_var.get().strip()
            if not text:
                return
            entry_var.set("")
            if self.paused:
                self.write_log("SYS: JARVIS está en pausa.")
                return
            if text.lower() in ("sus", "dur", "stop", "sessiz", "kes"):
                self._mini_stop_voice()
                return
            if self.on_text_command:
                threading.Thread(
                    target=self.on_text_command, args=(text,),
                    daemon=True).start()

        entry.bind("<Return>", _submit)
        entry.bind("<KP_Enter>", _submit)
        entry.bind("<Escape>", lambda e: self._mini_escape())
        send_lbl.bind("<Button-1>", lambda e: _submit())

        # ── Stash refs ───────────────────────────────────────────────────
        self._mini_window = win
        self._mini_bg = MINI_BG
        self._mini_muted = MINI_MUTED
        self._mini_orb = orb
        self._mini_orb_core = orb_core
        self._mini_orb_ring1 = orb_ring1
        self._mini_orb_ring2 = orb_ring2
        self._mini_state_lbl = state_lbl
        self._mini_log_lbl = log_lbl
        self._mini_anim = anim
        self._mini_entry = entry
        self._mini_actions_frame = actions
        self._mini_input_frame = bot
        self._mini_pin_btn = pin_btn
        self._mini_expand_btn = expand_btn
        self._mini_mute_btn = mute_btn
        self._mini_chat_frame = chat_frame
        self._mini_chat_text = chat_text

    def _mini_escape(self):
        if self._mini_chat_open:
            self._mini_toggle_chat()
        else:
            self._toggle_mini_window()

    def _mini_stop_voice(self):
        self.write_log("SYS: ⏹ Audio detenido.")
        if self.on_stop_command:
            threading.Thread(target=self.on_stop_command,
                             daemon=True).start()

    def _mini_clear_chat(self):
        self._mini_history.clear()
        try:
            self._mini_chat_text.configure(state="normal")
            self._mini_chat_text.delete("1.0", tk.END)
            self._mini_chat_text.configure(state="disabled")
        except tk.TclError:
            pass

    def _mini_toggle_pin(self):
        if not self._mini_window:
            return
        self._mini_topmost = not self._mini_topmost
        try:
            self._mini_window.attributes("-topmost", self._mini_topmost)
            self._mini_pin_btn.configure(
                fg=C_PRI if self._mini_topmost else self._mini_muted)
        except tk.TclError:
            pass

    def _mini_refresh_mute_btn(self):
        """Mic ikonunu mute durumuna göre günceller."""
        if not getattr(self, "_mini_mute_btn", None):
            return
        try:
            self._mini_mute_btn.configure(
                text="🔇" if self.muted else "🎤",
                fg=C_RED if self.muted else self._mini_muted)
        except tk.TclError:
            pass

    def _mini_toggle_chat(self):
        if not self._mini_window:
            return
        self._mini_chat_open = not self._mini_chat_open
        try:
            if self._mini_chat_open:
                self._mini_chat_frame.pack(
                    fill="both", expand=True,
                    side="top", padx=12, pady=(6, 0),
                    before=self._mini_actions_frame)
                self._mini_expand_btn.configure(text="▲")
                self._mini_render_chat()
            else:
                self._mini_chat_frame.pack_forget()
                self._mini_expand_btn.configure(text="▼")
            self._mini_animate_resize(
                self.MINI_H_EXPANDED if self._mini_chat_open
                else self.MINI_H_COMPACT)
        except tk.TclError:
            pass

    def _mini_animate_resize(self, target_h: int):
        if not self._mini_window:
            return
        try:
            geom = self._mini_window.geometry()
            # geom like "WxH+X+Y"
            size_part, _, pos = geom.partition("+")
            cur_w, _, cur_h = size_part.partition("x")
            cur_h = int(cur_h)
            x_str, _, y_str = pos.partition("+")
            x = int(x_str); y = int(y_str)
        except Exception:
            return
        steps = 8
        delta = (target_h - cur_h) / steps

        def _step(i, h):
            if i >= steps:
                self._mini_window.geometry(
                    f"{self.MINI_W}x{target_h}+{x}+{y}")
                return
            new_h = int(round(h + delta))
            try:
                self._mini_window.geometry(
                    f"{self.MINI_W}x{new_h}+{x}+{y}")
            except tk.TclError:
                return
            self.root.after(14, _step, i + 1, new_h)

        _step(0, cur_h)

    def _mini_render_chat(self):
        try:
            self._mini_chat_text.configure(state="normal")
            self._mini_chat_text.delete("1.0", tk.END)
            for entry in self._mini_history:
                tag, line = entry
                self._mini_chat_text.insert(tk.END, line + "\n", tag)
            self._mini_chat_text.see(tk.END)
            self._mini_chat_text.configure(state="disabled")
        except tk.TclError:
            pass

    def _mini_classify(self, text: str):
        tl = text.lower()
        if tl.startswith("tú:") or tl.startswith("you:"):
            return "you"
        if tl.startswith("jarvis:") or tl.startswith("ai:"):
            return "ai"
        if tl.startswith("err:") or "error" in tl:
            return "err"
        return "sys"

    @staticmethod
    def _spaced_caps(text: str) -> str:
        return " ".join(list(text.upper()))

    def _toggle_mini_window(self):
        if not self._mini_window:
            return
        if self._mini_visible:
            self._mini_window.withdraw()
            self._mini_visible = False
            for attr in ("_mini_pulse_job", "_mini_anim_job"):
                job = getattr(self, attr, None)
                if job:
                    try:
                        self.root.after_cancel(job)
                    except Exception:
                        pass
                    setattr(self, attr, None)
            try:
                self.root.deiconify()
                self.root.lift()
                self.root.focus_force()
            except tk.TclError:
                pass
        else:
            try:
                self.root.withdraw()
            except tk.TclError:
                pass
            self._mini_window.deiconify()
            self._mini_window.lift()
            self._mini_window.attributes("-topmost", self._mini_topmost)
            self._mini_visible = True
            self._update_mini_state(self._jarvis_state)
            if self._mini_last_log:
                self._update_mini_log(self._mini_last_log)
            if self._mini_chat_open:
                self._mini_render_chat()
            try:
                self._mini_entry.focus_set()
            except tk.TclError:
                pass
            self._pulse_mini_dot()
            self._animate_mini_strip()

    def _pulse_mini_dot(self):
        """Animate the mini orb — rotating rings + pulsing core."""
        if not self._mini_visible or not self._mini_window:
            return
        try:
            self._mini_orb_phase = (self._mini_orb_phase + 0.12) % 360.0
            state = "PAUSED" if self.paused else self._jarvis_state
            base = self._state_color(state)

            # Rotate the two arc rings in opposite directions
            r1_start = int(self._mini_orb_phase) % 360
            r2_start = int(360 - self._mini_orb_phase * 1.4) % 360
            self._mini_orb.itemconfig(self._mini_orb_ring1,
                                      start=r1_start, outline=base)
            self._mini_orb.itemconfig(self._mini_orb_ring2,
                                      start=r2_start,
                                      outline=C_MID if state != "ERROR" else C_RED)

            # Pulse the inner core
            phase = math.radians(self._mini_orb_phase * 3.0)
            r = 3.6 + math.sin(phase) * 1.2
            cx, cy = 16, 16
            self._mini_orb.coords(self._mini_orb_core,
                                  cx - r, cy - r, cx + r, cy + r)
            self._mini_orb.itemconfig(self._mini_orb_core, fill=base)
        except tk.TclError:
            return
        self._mini_pulse_job = self.root.after(60, self._pulse_mini_dot)

    def _animate_mini_strip(self):
        """Render state-specific micro animation in the middle strip."""
        if not self._mini_visible or not self._mini_window:
            return
        try:
            self._mini_anim_phase = (self._mini_anim_phase + 0.22) % math.tau
            state = "PAUSED" if self.paused else self._jarvis_state
            color = self._state_color(state)
            cv = self._mini_anim
            cv.delete("all")
            w = cv.winfo_width() or (self.MINI_W - 24)
            h = cv.winfo_height() or 22
            cy = h // 2

            if state == "LISTENING":
                # 5-bar mini waveform, idle gentle sway
                bars = 5
                gap = 6
                bw = 3
                total = bars * bw + (bars - 1) * gap
                x0 = (w - total) // 2
                for i in range(bars):
                    amp = 3 + abs(math.sin(self._mini_anim_phase + i * 0.7)) * 6
                    x = x0 + i * (bw + gap)
                    cv.create_rectangle(x, cy - amp, x + bw, cy + amp,
                                        fill=color, outline="")
            elif state == "SPEAKING":
                # 7-bar tall equalizer
                bars = 7
                gap = 4
                bw = 3
                total = bars * bw + (bars - 1) * gap
                x0 = (w - total) // 2
                for i in range(bars):
                    amp = 4 + abs(math.sin(
                        self._mini_anim_phase * 1.8 + i * 1.1)) * 8
                    x = x0 + i * (bw + gap)
                    cv.create_rectangle(x, cy - amp, x + bw, cy + amp,
                                        fill=color, outline="")
            elif state == "THINKING" or state == "INITIALISING":
                # Three dots wave
                dots = 3
                gap = 14
                total = (dots - 1) * gap
                x0 = (w - total) // 2
                for i in range(dots):
                    off = math.sin(self._mini_anim_phase * 1.5 - i * 0.9) * 4
                    x = x0 + i * gap
                    cv.create_oval(x - 3, cy - 3 + off, x + 3, cy + 3 + off,
                                   fill=color, outline="")
                # Indeterminate bar at the bottom
                bar_w = w * 0.4
                pos = (math.sin(self._mini_anim_phase) * 0.5 + 0.5) * (w - bar_w)
                cv.create_line(0, h - 1, w, h - 1, fill=C_DIM, width=1)
                cv.create_line(pos, h - 1, pos + bar_w, h - 1,
                               fill=color, width=2)
            elif state == "ERROR":
                # Warning triangle + steady glow
                cx = w // 2
                cv.create_polygon(cx - 8, cy + 6, cx + 8, cy + 6, cx, cy - 8,
                                  outline=C_RED, fill="", width=2)
                cv.create_text(cx, cy + 1, text="!", fill=C_RED,
                               font=(FONT_BODY_FAMILY, 10, "bold"))
            elif state == "MUTED" or state == "PAUSED":
                # Static dim line
                cv.create_line(w // 2 - 24, cy, w // 2 + 24, cy,
                               fill=self._mini_muted, width=2)
                glyph = "⏸" if state == "PAUSED" else "⏻"
                cv.create_text(w // 2 - 36, cy, text=glyph,
                               fill=self._mini_muted,
                               font=("Segoe UI Symbol", 10, "bold"))
            else:
                cv.create_text(w // 2, cy, text="●",
                               fill=color,
                               font=(FONT_BODY_FAMILY, 10, "bold"))
        except tk.TclError:
            return
        self._mini_anim_job = self.root.after(55, self._animate_mini_strip)

    def _update_mini_state(self, state: str):
        if not self._mini_window:
            return
        try:
            color = self._state_color(state)
            label_map = {
                "LISTENING": "ESCUCHANDO",
                "SPEAKING":  "HABLANDO",
                "THINKING":  "PENSANDO",
                "MUTED":     "SILENCIADO",
                "PAUSED":    "EN PAUSA",
                "ERROR":     "ERROR",
                "INITIALISING": "CONECTANDO",
            }
            label = label_map.get(state, state)
            self._mini_state_lbl.configure(
                text=self._spaced_caps(label), fg=color)
        except tk.TclError:
            pass

    def _update_mini_log(self, text: str):
        self._mini_last_log = text
        # Always keep history fresh, even when panel is hidden
        try:
            tag = self._mini_classify(text)
            stripped = text
            for prefix in ("SYS:", "ERR:", "JARVIS:", "Tú:", "You:"):
                if stripped.startswith(prefix):
                    stripped = stripped[len(prefix):].strip()
                    break
            self._mini_history.append((tag, stripped))
        except Exception:
            return
        if not self._mini_window or not self._mini_visible:
            return
        try:
            display = stripped if len(stripped) <= 60 else stripped[:57] + "…"
            color_map = {
                "you": "#E9E0CE",
                "ai":  C_PRI,
                "err": C_RED,
                "sys": self._mini_muted,
            }
            self._mini_log_lbl.configure(
                text=display, fg=color_map.get(tag, self._mini_muted))
            # If chat panel is open, append the new line live
            if self._mini_chat_open:
                self._mini_chat_text.configure(state="normal")
                self._mini_chat_text.insert(tk.END, stripped + "\n", tag)
                self._mini_chat_text.see(tk.END)
                self._mini_chat_text.configure(state="disabled")
        except tk.TclError:
            pass

    # ── Input bar ────────────────────────────────────────────────────────────
    def _build_input_bar(self, lw: int):
        x0 = self.CHAT_X
        btn_w = 76
        gap = 8
        inp_w = lw - btn_w - gap

        self._input_var   = tk.StringVar()
        self._input_entry = tk.Entry(
            self.root, textvariable=self._input_var,
            fg=C_TEXT, bg="#171922", insertbackground=C_TEXT,
            borderwidth=0, font=font_body(11),
            highlightthickness=1, highlightbackground=C_DIM,
            highlightcolor=C_PRI)
        self._input_entry.place(
            x=x0, y=self.CHAT_INPUT_Y, width=inp_w, height=INPUT_H)
        self._input_entry.bind("<Return>",   self._on_input_submit)
        self._input_entry.bind("<KP_Enter>", self._on_input_submit)

        self._send_btn = tk.Button(
            self.root, text="ENVIAR ▸",
            command=self._on_input_submit,
            fg=C_ORG, bg=C_PANEL,
            activeforeground=C_BG, activebackground=C_ORG,
            font=font_body_bold(10),
            borderwidth=0, cursor="hand2",
            highlightthickness=1, highlightbackground=C_ORG)
        self._send_btn.place(
            x=x0+inp_w+gap, y=self.CHAT_INPUT_Y,
            width=btn_w, height=INPUT_H)

    def _place_layout_widgets(self):
        self.log_frame.place(x=self.CHAT_X, y=self.CHAT_Y, width=self.CHAT_W, height=self.CHAT_H)
        gap = 12
        mute_w = 126
        pause_w = 126
        shutdown_w = int(self._shutdown_canvas["width"])
        total = mute_w + pause_w + shutdown_w + gap * 2
        start_x = self.FCX - total // 2
        row1_y = self.CTRL_Y + 8

        self._mute_canvas.place(x=start_x, y=row1_y)
        self._pause_canvas.place(x=start_x + mute_w + gap, y=row1_y)
        self._shutdown_canvas.place(x=start_x + mute_w + pause_w + gap * 2, y=row1_y)

        geo = self._settings_geometry
        panel_x = geo["panel_x"]
        panel_y = geo["panel_y"]
        panel_w = geo["panel_w"]
        panel_h = geo["panel_h"]
        if self._settings_open:
            self._settings_panel.place(x=panel_x, y=panel_y, width=panel_w, height=panel_h)
            self._settings_panel.lift()
            self._settings_title.place(x=14, y=12)
            self._settings_tab_settings.place(x=14, y=40)
            self._settings_tab_debug.place(x=130, y=40)
            if self._settings_tab == "debug":
                self._settings_body.place_forget()
                self._debug_body.place(x=12, y=76, width=panel_w - 24, height=panel_h - 88)
                self._debug_text.place(x=0, y=0, width=panel_w - 24, height=panel_h - 88)
                self._debug_body.lift()
            else:
                self._debug_body.place_forget()
                self._settings_body.place(x=12, y=76, width=panel_w - 24, height=panel_h - 88)
                self._settings_body.lift()
        else:
            self._settings_panel.place_forget()
            self._settings_title.place_forget()
            self._settings_tab_settings.place_forget()
            self._settings_tab_debug.place_forget()
            self._settings_body.place_forget()
            self._debug_body.place_forget()

        inp_w = self.CHAT_W - 84
        self._input_entry.place(x=self.CHAT_X, y=self.CHAT_INPUT_Y, width=inp_w, height=INPUT_H)
        self._send_btn.place(x=self.CHAT_X + inp_w + 8, y=self.CHAT_INPUT_Y, width=76, height=INPUT_H)

    def _on_input_submit(self, event=None):
        text = self._input_var.get().strip()
        if not text:
            return
        if self.paused:
            self.write_log("SYS: JARVIS está en pausa. Reanúdalo para continuar.")
            return
        self._input_var.set("")
        if text.lower() in ("sus", "dur", "stop", "sessiz", "kes"):
            self.write_log("SYS: ⏹ Audio detenido.")
            if self.on_stop_command:
                threading.Thread(target=self.on_stop_command, daemon=True).start()
            return
        if self.on_text_command:
            threading.Thread(target=self.on_text_command, args=(text,), daemon=True).start()

    # ── State & callbacks ────────────────────────────────────────────────────
    def set_state(self, state: str):
        previous = getattr(self, "_jarvis_state", "")
        self._jarvis_state = state
        self.speaking = (state == "SPEAKING")
        if state == "THINKING":
            self.sound.start_thinking()
        elif previous == "THINKING":
            self.sound.stop_thinking()
        if state == "ERROR" and previous != "ERROR":
            self.sound.play_error()
        if hasattr(self, "_mini_window"):
            self._update_mini_state(state)

    def set_user_speaking(self, value: bool):
        self.mark_user_activity(value)

    def mark_user_activity(self, active: bool = True):
        self.user_speaking = active
        self._user_speaking_until = time.time() + (0.9 if active else 0.0)

    def get_effects_volume(self) -> float:
        return self.sound.get_volume()

    def effects_enabled(self) -> bool:
        return bool(self._effects_active)

    def play_success_sfx(self):
        self.root.after(0, self.sound.play_success)

    def play_error_sfx(self):
        self.root.after(0, self.sound.play_error)

    def focus_panel(self, section: str, duration_ms: int = 4200):
        section = (section or "").strip().lower()
        if not section:
            return

        def _apply():
            self._panel_focus = section
            self._panel_focus_until = time.time() + max(0.8, duration_ms / 1000.0)

        self.root.after(0, _apply)

    def _state_color(self, state: str | None = None) -> str:
        effective = state or self._jarvis_state
        if effective == "PAUSED":
            return C_MID
        return STATE_HEX_COLORS.get(effective, C_PRI)

    @staticmethod
    def _state_badge_text(state: str) -> str:
        if state == "INITIALISING":
            return "CONECTANDO"
        if state == "ERROR":
            return "ERROR"
        if state == "PAUSED":
            return "EN PAUSA"
        if state == "LISTENING":
            return "ESCUCHANDO"
        if state == "SPEAKING":
            return "HABLANDO"
        if state == "THINKING":
            return "PENSANDO"
        return "EN LÍNEA"

    # ── Log ──────────────────────────────────────────────────────────────────
    def write_log(self, text: str):
        self.typing_queue.append(text)
        if hasattr(self, "_mini_window"):
            self._update_mini_log(text)
        tl = text.lower()
        if tl.startswith("tú:") or tl.startswith("you:"):
            self.mark_user_activity(True)
            self.set_state("THINKING")
        elif tl.startswith("err:") or "error" in tl:
            self._error_hold_until = time.time() + 8.0
            self.set_state("ERROR")
            self.write_debug(text, level="ERROR")
        if not self.is_typing:
            self._start_typing()

    def _start_typing(self):
        if not self.typing_queue:
            self.is_typing = False
            if self._jarvis_state == "ERROR" and time.time() < self._error_hold_until:
                return
            if not self.speaking:
                self.set_state("LISTENING")
            return
        self.is_typing = True
        text = self.typing_queue.popleft()
        tl   = text.lower()
        if   tl.startswith("tú:") or tl.startswith("you:"):   tag = "you"
        elif tl.startswith("jarvis:") or tl.startswith("ai:"): tag = "ai"
        elif tl.startswith("err:") or "error" in tl:           tag = "err"
        else:                                                    tag = "sys"
        self.log_text.configure(state="normal")
        self._type_char(text, 0, tag)

    def _type_char(self, text, i, tag):
        if i < len(text):
            self.log_text.insert(tk.END, text[i], tag)
            self.log_text.see(tk.END)
            self.root.after(7, self._type_char, text, i+1, tag)
        else:
            self.log_text.insert(tk.END, "\n")
            self.log_text.configure(state="disabled")
            self.root.after(20, self._start_typing)

    # ── Stats ────────────────────────────────────────────────────────────────
    def _update_stats(self):
        try:
            self._stats['cpu']  = psutil.cpu_percent()
            virtual_memory = psutil.virtual_memory()
            self._stats['ram'] = virtual_memory.percent
            self._stats['ram_used'] = virtual_memory.used / (1024 ** 3)
            self._stats['ram_total'] = virtual_memory.total / (1024 ** 3)
            self._stats['processes'] = len(psutil.pids())
            _drive = os.environ.get("SystemDrive", "C:") + "\\"
            self._stats['disk'] = psutil.disk_usage(_drive).percent
            batt = psutil.sensors_battery()
            self._stats['battery'] = batt.percent if batt else 100.0
            now = time.time()
            net = psutil.net_io_counters()
            dt  = now - self._last_net_t
            if dt > 0:
                self._stats['net_up']   = max(0, (net.bytes_sent - self._last_net.bytes_sent) / dt / 1024)
                self._stats['net_down'] = max(0, (net.bytes_recv - self._last_net.bytes_recv) / dt / 1024)
            self._last_net   = net
            self._last_net_t = now
            self._cpu_hist.pop(0)
            self._cpu_hist.append(self._stats['cpu'])
        except Exception:
            pass

    # ── Animation loop ───────────────────────────────────────────────────────
    def _animate(self):
        self.tick += 1
        t   = self.tick
        now = time.time()

        if self.user_speaking and now > self._user_speaking_until:
            self.user_speaking = False

        if t % 90 == 0:
            threading.Thread(target=self._update_stats, daemon=True).start()
        if t % 27000 == 1:
            self._kick_brief_refresh()

        if self.speaking and t % 3 == 0:
            self._wave_jarvis = [random.randint(6, 30) for _ in range(18)]
        if self.user_speaking and t % 3 == 0:
            self._wave_user = [random.randint(5, 24) for _ in range(18)]

        if now - self.last_t > (0.12 if self.speaking else 0.50):
            if self.paused:
                self.target_scale = random.uniform(0.58, 0.64)
                self.target_halo  = random.uniform(5, 10)
            elif self.speaking:
                self.target_scale = random.uniform(0.98, 1.10)
                self.target_halo  = random.uniform(180, 250)
            elif self.user_speaking:
                self.target_scale = random.uniform(0.88, 0.98)
                self.target_halo  = random.uniform(120, 175)
            elif self._jarvis_state in ("THINKING", "INITIALISING"):
                self.target_scale = random.uniform(0.80, 0.88)
                self.target_halo  = random.uniform(95, 145)
            else:
                self.target_scale = random.uniform(0.72, 0.80)
                self.target_halo  = random.uniform(34, 58)
            self.last_t = now

        sp          = 0.34 if self.speaking else 0.18
        self.scale  += (self.target_scale - self.scale) * sp
        self.halo_a += (self.target_halo   - self.halo_a) * sp

        if self.paused:
            spds = [0.0, 0.0, 0.0, 0.0]
        elif self.speaking:
            spds = [1.6, -1.1, 2.4, -0.7]
        else:
            spds = [0.55, -0.35, 0.90, -0.28]
        for i, spd in enumerate(spds):
            self.rings_spin[i] = (self.rings_spin[i] + spd) % 360

        # Pulse rings
        pspd  = 4.2 if self.speaking else 1.8
        limit = self.FACE * 0.68
        self.pulse_r = [r + pspd for r in self.pulse_r if r + pspd < limit]
        if len(self.pulse_r) < 3 and random.random() < (0.07 if self.speaking else 0.02):
            self.pulse_r.append(0.0)

        for p in self.particles:
            p['x'] = (p['x'] + p['vx']) % self.W
            p['y'] = (p['y'] + p['vy']) % self.H

        if t % 38 == 0:
            self.status_blink = not self.status_blink

        if self._flight_clips and now >= self._flight_cameo_next:
            self._flight_clip_index = (self._flight_clip_index + 1) % len(self._flight_clips)
            self._flight_clip = self._flight_clips[self._flight_clip_index]
            self._flight_cameo_started = time.monotonic()
            self._flight_cameo_next = now + random.uniform(22.0, 30.0)

        self._draw()
        self.root.after(33, self._animate)

    # ── Yardımcı ─────────────────────────────────────────────────────────────
    @staticmethod
    def _ac(r, g, b, a):
        f = max(0, min(255, int(a))) / 255.0
        return f"#{int(r*f):02x}{int(g*f):02x}{int(b*f):02x}"

    def _orb_rgb(self):
        state = "PAUSED" if self.paused else self._jarvis_state
        return ORB_COLORS.get(state, ORB_COLORS["LISTENING"])

    @staticmethod
    def _split_summary_lines(text: str, limit: int = 4) -> list[str]:
        raw = (text or "").strip()
        if not raw:
            return []
        raw = raw.replace(" ve ", ", ")
        parts = [part.strip(" .") for part in raw.split(",") if part.strip()]
        return parts[:limit]

    def _parse_weather_card(self, text: str) -> dict:
        if not text or "no se pudo consultar" in text.lower() or "no hay datos" in text.lower():
            return {
                "city": get_current_city(),
                "primary": "--",
                "details": ["No se pudo consultar el clima."],
            }

        prefix, _, body = text.partition(":")
        city = get_current_city()
        if prefix.strip():
            city = prefix.strip()

        details = [part.strip(" .") for part in body.split(",") if part.strip()]
        primary = "--"
        if details:
            primary = details[0].replace(" derece", "°C")
        return {
            "city": city,
            "primary": primary,
            "details": details[1:4] or ["Datos en tiempo real disponibles."],
        }

    def _edit_weather_location(self, _event=None):
        current = str(load_app_config().get("weather_location", "") or "")
        value = simpledialog.askstring(
            "Ubicación del clima",
            "Ciudad para el clima. Deja el campo vacío para detectar la ubicación automáticamente:",
            initialvalue=current,
            parent=self.root,
        )
        if value is None:
            return
        save_app_config({
            "weather_location": value.strip(),
            "weather_location_region": get_location_region() if value.strip() else "",
        })
        self._brief_refresh_busy = False
        self._kick_brief_refresh()

    def _parse_health_card(self, text: str) -> list[str]:
        if not text or "alınamadı" in text.lower() or "alınamadi" in text.lower():
            return ["Sağlık verisi alınamadı."]
        lines = self._split_summary_lines(text, limit=4)
        return lines or ["Sağlık özeti hazır değil."]

    def _kick_brief_refresh(self):
        if self._brief_refresh_busy:
            return
        self._brief_refresh_busy = True
        threading.Thread(target=self._refresh_brief_cards, daemon=True).start()

    def _refresh_brief_cards(self):
        try:
            try:
                weather = get_weather_summary()
                self._weather_card = self._parse_weather_card(weather)
            except Exception:
                self._weather_card = {
                    "city": get_current_city(),
                    "primary": "--",
                    "details": ["No se pudo consultar el clima."],
                }
            try:
                self._health_card_lines = get_health_card_lines()
            except Exception:
                self._health_card_lines = ["Sağlık verisi alınamadı."]
        finally:
            self._brief_refresh_busy = False

    def _bar(self, c, x, y, w, h, pct, color):
        c.create_rectangle(x, y, x+w, y+h, fill="#171922", outline=C_DIM, width=1)
        fw = max(1, int(w * pct / 100))
        c.create_rectangle(x+1, y+1, x+fw, y+h-1, fill=color, outline="")

    def _sparkline(self, c, x, y, w, h, data):
        c.create_rectangle(x, y, x+w, y+h, fill="#171922", outline=C_DIM, width=1)
        n = len(data)
        if n < 2:
            return
        step = (w - 2) / (n - 1)
        h2   = h - 2
        coords = []
        for i, v in enumerate(data):
            coords.append(x + 1 + i * step)
            coords.append(y + h - 1 - int(h2 * v / 100))
        c.create_line(*coords, fill=C_PRI, width=1, smooth=True)

    def _bracket(self, c, x0, y0, pw, ph, col=None, bl=12):
        col = col or C_PRI
        for bx, by, sx, sy in [(x0, y0, 1, 1), (x0+pw, y0, -1, 1),
                                (x0, y0+ph, 1, -1), (x0+pw, y0+ph, -1, -1)]:
            c.create_line(bx, by, bx+sx*bl, by, fill=col, width=2)
            c.create_line(bx, by, bx, by+sy*bl, fill=col, width=2)

    def _draw_info_card(self, c, x0, y0, pw, ph, title, accent=C_PRI):
        focus = max(0.0, min(1.0, getattr(self, "_card_focus_boost", 0.0)))
        dimmed = bool(getattr(self, "_card_dimmed", False))
        glow = int(55 + 120 * focus)
        border = accent if focus > 0.08 else ("#51483F" if dimmed else self._ac(231, 182, 107, 190))
        fill = "#171922" if dimmed else C_PANEL
        c.create_rectangle(x0, y0, x0+pw, y0+ph, fill=fill, outline="")
        if focus > 0.08:
            for inset in range(3):
                c.create_rectangle(
                    x0-inset, y0-inset, x0+pw+inset, y0+ph+inset,
                    outline=self._ac(*ORB_COLORS["LISTENING"], max(12, glow - inset * 28)),
                    width=1,
                )
        self._bracket(c, x0, y0, pw, ph, col=border, bl=10)
        title_fill = "#A79B87" if dimmed else accent
        line_fill = "#39343D" if dimmed else C_DIM
        c.create_text(x0+14, y0+14, text=title, fill=title_fill,
                      font=font_display(10), anchor="w")
        c.create_line(x0+12, y0+28, x0+pw-12, y0+28, fill=line_fill)

    def _focus_boost_for(self, section: str) -> float:
        if self._panel_focus != section:
            return 0.0
        remaining = self._panel_focus_until - time.time()
        if remaining <= 0:
            return 0.0
        pulse = 0.65 + 0.35 * math.sin(self.tick * 0.12)
        return min(1.0, remaining / 4.0) * pulse

    # ── Health overlay (sol panel) ────────────────────────────────────────────
    def show_health_hologram(self, query: str, data_str: str):
        def _show():
            self._health_visible = True
            self._health_query   = query.lower()
            self._health_display = data_str
            self._panel_focus = "health"
            self._panel_focus_until = time.time() + 5.0
            if self._health_hide_job:
                self.root.after_cancel(self._health_hide_job)
            self._health_hide_job = self.root.after(14000, self._hide_health_hologram)
        self.root.after(0, _show)

    def _hide_health_hologram(self):
        self._health_visible  = False
        self._health_hide_job = None

    def _draw_health_overlay(self, c):
        x0, y0 = 4, HDR_H + 4
        pw = self.LEFT_W - 8
        ph = self.H - HDR_H - FOOTER_H - 90
        pulse = 0.5 + 0.5 * math.sin(self.tick * 0.08)

        c.create_rectangle(x0, y0, x0+pw, y0+ph,
                           fill="#171922", outline=C_PRI, width=1)
        self._bracket(c, x0, y0, pw, ph, col=C_ORG, bl=10)

        title_col = self._ac(0, 212, 192, int(200 + 55*pulse))
        c.create_text(x0+pw//2, y0+18, text="◈ SALUD ◈",
                      fill=title_col, font=font_display(11))
        c.create_line(x0+8, y0+30, x0+pw-8, y0+30, fill=C_MID)

        lines = [l for l in self._health_display.split('\n') if l.strip()]
        ly = y0 + 44
        for line in lines:
            if ly > y0 + ph - 14:
                break
            if line.startswith("──"):
                c.create_line(x0+8, ly, x0+pw-8, ly, fill=C_DIM)
                ly += 10
            elif ":" in line:
                parts = line.split(":", 1)
                lbl   = parts[0].strip()
                val   = parts[1].strip() if len(parts) > 1 else ""
                c.create_text(x0+10, ly, text=lbl+":", fill=C_MID,
                              font=font_body(10), anchor="w")
                c.create_text(x0+pw-10, ly, text=val, fill=C_ORG,
                              font=font_body_bold(10), anchor="e")
                ly += 20
            else:
                c.create_text(x0+10, ly, text=line, fill=C_TEXT,
                              font=font_body(9), anchor="w")
                ly += 17

    # ── Sol panel ─────────────────────────────────────────────────────────────
    def _draw_left_panel(self, c):
        if self._health_visible:
            self._draw_health_overlay(c)
            return

        x0 = 10
        y0 = HDR_H + 10
        pw = self.LEFT_W - 18
        gap = 14
        total_h = self.H - HDR_H - FOOTER_H - 20
        card_area_h = total_h - gap * 3
        pad = 14
        bw = pw - 2 * pad

        cards = [
            ("time", 0.17, "HORA LOCAL", C_GOLD),
            ("weather", 0.20, f"CLIMA / {self._weather_card['city']}", C_BLUE),
            ("system", 0.43, "TELEMETRIA DEL EQUIPO", C_PRI),
            ("health", 0.20, "ESTADO DEL SISTEMA", C_GREEN),
        ]
        any_focus_active = bool(self._panel_focus) and (self._panel_focus_until > time.time())
        weights = []
        for section, weight, _, _ in cards:
            weights.append(weight + (0.12 if self._focus_boost_for(section) > 0.08 else 0.0))
        total_weight = sum(weights)
        heights = [int(card_area_h * (weight / total_weight)) for weight in weights]
        heights[-1] += card_area_h - sum(heights)

        current_y = y0
        for (section, _, title, accent), ph in zip(cards, heights):
            focus_boost = self._focus_boost_for(section)
            dimmed = any_focus_active and focus_boost <= 0.08
            shift_x = int(14 * focus_boost)
            extra_w = int(22 * focus_boost)
            section_x = x0 + shift_x
            section_pw = pw + extra_w
            section_pad = pad + int(2 * focus_boost)
            section_bw = section_pw - 2 * section_pad
            muted_label = "#968B7A" if dimmed else C_MID
            muted_text = "#B3A68F" if dimmed else C_TEXT
            muted_primary = "#C7B99F" if dimmed else C_PRI
            muted_blue = "#A7B9D7" if dimmed else C_BLUE
            muted_green = "#9FB99D" if dimmed else C_GREEN
            muted_gold = "#E9BC6D" if dimmed else C_GOLD
            muted_warn = "#E6A477" if dimmed else C_ORG2
            muted_red = "#E56E67" if dimmed else C_RED
            self._card_focus_boost = focus_boost
            self._card_dimmed = dimmed
            self._draw_info_card(c, section_x, current_y, section_pw, ph, title, accent=accent if not dimmed else "#72807f")

            if section == "time":
                c.create_text(section_x+section_pad, current_y+57, text=time.strftime("%H:%M"),
                              fill=muted_primary, font=font_display(31), anchor="w")
                now = time.localtime()
                date_label = f"{SPANISH_DAYS[now.tm_wday].upper()}  \u00b7  {now.tm_mday:02d} {SPANISH_MONTHS[now.tm_mon - 1].upper()} {now.tm_year}"
                c.create_text(section_x+section_pad, current_y+85, text=date_label,
                              fill=muted_gold, font=font_body_bold(8), anchor="w")

            elif section == "weather":
                c.create_text(section_x+section_pad, current_y+52, text=self._weather_card["primary"],
                              fill=muted_primary, font=font_display(28), anchor="w")
                c.create_text(section_x+section_pad, current_y+78,
                              text=f"{self._weather_card['city'].upper()} / CAMBIAR",
                              fill=muted_label, font=font_body_bold(8), anchor="w",
                              tags=("weather_city",))
                details = self._weather_card["details"][:2]
                for offset, line in zip((95, 109), details):
                    c.create_text(section_x+section_pad, current_y+offset,
                                  text=f"- {line}", fill=muted_text,
                                  font=font_body(8), anchor="w")

            elif section == "system":
                cy = current_y + 39
                uptime = max(0, int(time.time() - self._started_at))
                up_min, up_sec = divmod(uptime, 60)
                up_hr, up_min = divmod(up_min, 60)
                c.create_text(section_x+section_pad, cy,
                              text=f"JARVIS ACTIVO  {up_hr:02d}:{up_min:02d}:{up_sec:02d}",
                              fill=muted_label, font=font_body_bold(9), anchor="w")
                col_gap = 9
                tile_w = max(48, (section_bw-col_gap)/2)
                metrics = [("CPU", "cpu"), ("RAM", "ram"),
                           ("DISCO", "disk"), ("BATERIA", "battery")]
                for index, (label, key) in enumerate(metrics):
                    val = max(0.0, min(100.0, self._stats[key]))
                    col = C_RED if val > 80 and key != "battery" else C_ORG if val > 55 and key != "battery" else (C_RED if key == "battery" and val < 20 else C_GREEN if key == "battery" else C_PRI)
                    if dimmed:
                        col = muted_red if col == C_RED else muted_warn if col == C_ORG else muted_green if col == C_GREEN else muted_primary
                    row, column = divmod(index, 2)
                    tile_x = section_x+section_pad + column*(tile_w+col_gap)
                    tile_y = cy+16+row*40
                    c.create_rectangle(tile_x, tile_y, tile_x+tile_w, tile_y+35,
                                       fill="#27242B" if not dimmed else "#201F27",
                                       outline="#39343D" if not dimmed else "#39343D")
                    c.create_text(tile_x+7, tile_y+9, text=label, fill=muted_label,
                                  font=font_body_bold(8), anchor="w")
                    c.create_text(tile_x+tile_w-7, tile_y+9, text=f"{val:.0f}%", fill=col,
                                  font=font_body_bold(10), anchor="e")
                    self._bar(c, tile_x+7, tile_y+21, max(18, tile_w-14), 6, val, col)
                net_y = cy+101
                c.create_line(section_x+section_pad, net_y,
                              section_x+section_pw-section_pad, net_y,
                              fill="#39343D" if not dimmed else "#28252D")
                up = self._stats["net_up"]
                down = self._stats["net_down"]
                up_s = f"{up:.0f} KB/s" if up < 1000 else f"{up/1024:.1f} MB/s"
                down_s = f"{down:.0f} KB/s" if down < 1000 else f"{down/1024:.1f} MB/s"
                c.create_text(section_x+section_pad, net_y+10, text=f"ENVIO  {up_s}",
                              fill=muted_warn, font=font_body(8), anchor="w")
                c.create_text(section_x+section_pw-section_pad, net_y+10, text=f"RECIBE  {down_s}",
                              fill=muted_green, font=font_body(8), anchor="e")
                ram_used = self._stats.get("ram_used", 0.0)
                ram_total = self._stats.get("ram_total", 0.0)
                ram_text = f"{ram_used:.1f}/{ram_total:.1f} GB" if ram_total else "--"
                process_count = self._stats.get("processes", 0)
                c.create_text(section_x+section_pad, net_y+25,
                              text=f"MEMORIA {ram_text} / PROCESOS {process_count}",
                              fill=muted_text, font=font_body(8), anchor="w")
                graph_label_y = net_y+40
                c.create_text(section_x+section_pad, graph_label_y,
                              text="CPU / ULTIMOS 72 S", fill=muted_label,
                              font=font_body_bold(8), anchor="w")
                graph_y = graph_label_y+8
                graph_h = max(8, min(28, current_y+ph-graph_y-7))
                self._sparkline(c, section_x+section_pad, graph_y,
                                section_bw, graph_h, self._cpu_hist)

            elif section == "health":
                items = (("CPU", "cpu"), ("MEMORIA", "ram"),
                         ("DISCO", "disk"), ("BATERIA", "battery"))
                gap_x, gap_y = 8, 6
                tile_w = (section_bw-gap_x)/2
                tile_h = 31
                base_y = current_y + 39
                for index, (label, key) in enumerate(items):
                    val = max(0.0, min(100.0, float(self._stats.get(key, 0.0))))
                    if key == "battery":
                        color = C_RED if val < 20 else C_GREEN
                    else:
                        color = C_RED if val >= 85 else C_ORG2 if val >= 65 else C_GREEN
                    row, column = divmod(index, 2)
                    tile_x = section_x+section_pad+column*(tile_w+gap_x)
                    tile_y = base_y+row*(tile_h+gap_y)
                    c.create_rectangle(tile_x, tile_y, tile_x+tile_w, tile_y+tile_h,
                                       fill="#201F27", outline="#39343D", width=1)
                    c.create_text(tile_x+7, tile_y+9, text=label, fill=muted_label,
                                  font=font_display(7), anchor="w")
                    c.create_text(tile_x+tile_w-7, tile_y+9, text=f"{val:.0f}%", fill=color,
                                  font=font_body_bold(9), anchor="e")
                    self._bar(c, tile_x+7, tile_y+19, tile_w-14, 5, val, color)
                uptime = max(0, int(time.time()-self._started_at))
                mins, secs = divmod(uptime, 60)
                c.create_text(section_x+section_pad, current_y+116,
                              text=f"JARVIS ACTIVO  {mins:02d}:{secs:02d}  /  {self._stats.get('processes', 0)} PROCESOS",
                              fill=muted_text, font=font_body(7), anchor="w")

            current_y += ph + gap

        self._card_focus_boost = 0.0
        self._card_dimmed = False

    # ── Sağ panel ─────────────────────────────────────────────────────────────
    def _draw_right_panel(self, c):
        x0  = self.CHAT_PANEL_X
        y0  = self.CHAT_PANEL_Y
        pw  = self.CHAT_PANEL_W
        ph  = self.CHAT_PANEL_H
        pad = 10

        c.create_rectangle(x0, y0, x0+pw, y0+ph, fill=C_PANEL, outline="")
        self._bracket(c, x0, y0, pw, ph, col=C_MID)

        if self.paused:
            sc, st = C_MID, "EN PAUSA"
        else:
            sc = self._state_color(self._jarvis_state)
            st = self._state_badge_text(self._jarvis_state)

        c.create_text(x0+14, y0+16, text="CONVERSACIÓN", fill=C_PRI,
                      font=font_display(11), anchor="w")
        c.create_text(x0+pw-pad, y0+16, text=st, fill=sc,
                      font=font_body_bold(10), anchor="e")
        c.create_line(x0+pad, y0+28, x0+pw-pad, y0+28, fill=C_DIM)

    # ── ORB (ana çizim) ───────────────────────────────────────────────────────
    def _draw_orb_legacy(self, c):
        state = "PAUSED" if self.paused else self._jarvis_state
        t    = self.tick
        speak_pulse = 1.0
        if self.speaking:
            speak_pulse = 1.0 + 0.12 * math.sin(t * 0.23) + 0.05 * math.sin(t * 0.11 + 1.2)
        elif self.user_speaking:
            speak_pulse = 1.0 + 0.06 * math.sin(t * 0.18 + 0.7)
        elif state in ("THINKING", "INITIALISING"):
            speak_pulse = 1.0 + 0.03 * math.sin(t * 0.10)
        else:
            speak_pulse = 1.0 + 0.01 * math.sin(t * 0.07)

        move_x = 0
        move_y = 0
        if self.user_speaking:
            move_x = int(6 * math.sin(t * 0.06))
            move_y = int(4 * math.cos(t * 0.09 + 0.5))
        elif state in ("THINKING", "INITIALISING"):
            move_x = int(3 * math.sin(t * 0.045))
            move_y = int(2 * math.cos(t * 0.05 + 0.4))

        FCX  = self.FCX + move_x
        FCY  = self.FCY + move_y
        FW   = int(self.FACE * self.scale * speak_pulse)
        if state == "ERROR":
            R, G, B = ORB_COLORS["ERROR"]
        elif state == "PAUSED":
            R, G, B = ORB_COLORS["PAUSED"]
        else:
            # Cian constante para el HUD; el estado se distingue con los acentos.
            R, G, B = (0, 205, 224)
        ha   = self.halo_a
        field_r = int(FW * 0.49)
        inner_r = int(FW * 0.34)
        activity = (
            0.10 if self.paused else
            1.00 if self.speaking else
            0.78 if self.user_speaking else
            0.62 if state in ("THINKING", "INITIALISING") else
            0.26
        )
        if state in ("THINKING", "INITIALISING"):
            accent_rgb = (255, 210, 72)
        elif self.speaking:
            accent_rgb = (170, 220, 255)
        elif self.user_speaking:
            accent_rgb = (118, 200, 255)
        else:
            accent_rgb = (82, 231, 255)

        # Halo rojo amplio alrededor del reactor, inspirado en el resplandor de
        # la referencia. Se pulsa con la voz y deja visible el núcleo en espera.
        reactor_r = max(12, int(inner_r * 0.53))
        aura_pulse = 0.78 + 0.22 * math.sin(t * (0.17 if self.speaking else 0.075))
        aura_strength = (0.28 + activity * 0.60) * aura_pulse
        for layer in range(7, 0, -1):
            aura_r = int(reactor_r * (1.0 + layer * 0.16))
            aura_alpha = int(aura_strength * (8 + layer * 3))
            c.create_oval(
                FCX-aura_r, FCY-aura_r, FCX+aura_r, FCY+aura_r,
                fill=self._ac(255, 39, 34, aura_alpha), outline="",
            )

        # Pulse rings
        for pr in self.pulse_r:
            alpha = max(0, int(160 * (1.0 - pr / (FW * 0.70))))
            rr = int(pr + field_r * 0.96)
            c.create_oval(
                FCX-rr, FCY-rr, FCX+rr, FCY+rr,
                outline=self._ac(R, G, B, alpha),
                width=1,
            )

        # Large outer glow
        if not self.paused:
            for i in range(10, 0, -1):
                frac = i / 10
                rr = int(field_r * (1.02 + 0.045 * frac))
                alpha = int(ha * 0.10 * frac)
                if self.speaking:
                    ox = 0
                    oy = 0
                else:
                    ox = int(3 * math.sin(t * 0.010 + i))
                    oy = int(3 * math.cos(t * 0.009 + i * 1.3))
                c.create_oval(
                    FCX-rr+ox, FCY-rr+oy, FCX+rr+ox, FCY+rr+oy,
                    outline=self._ac(R, G, B, alpha),
                    width=3,
                )

        # Structural circles
        for frac, width, alpha_mult in (
            (1.00, 2, 0.34),
            (0.90, 2, 0.24),
            (0.76, 1, 0.18),
            (0.62, 1, 0.12),
        ):
            rr = int(field_r * frac)
            c.create_oval(
                FCX-rr, FCY-rr, FCX+rr, FCY+rr,
                outline=self._ac(R, G, B, int(ha * alpha_mult * (0.4 if self.paused else 1.0))),
                width=width,
            )

        speak_shell_push = 1.16 if self.speaking else 1.07 if self.user_speaking else 1.0
        # Orb shell particles
        shell_r = field_r * 0.93 * speak_shell_push
        for idx, sp in enumerate(self.orb_shell_particles):
            angle = sp['angle'] + t * sp['speed'] * (2.8 if self.speaking else 1.6 if self.user_speaking else 1.1)
            wobble = 1.0 + (0.07 if self.speaking else 0.035) * math.sin(t * 0.08 + sp['phase'])
            x = FCX + math.cos(angle) * shell_r * wobble
            y = FCY + math.sin(angle) * shell_r * wobble
            alpha = int((70 + 120 * sp['glow']) * (0.26 if self.paused else 0.52 + activity * 0.45))
            if idx % 9 == 0 and not self.paused:
                col = self._ac(accent_rgb[0], accent_rgb[1], accent_rgb[2], min(255, alpha + 30))
            else:
                col = self._ac(R, G, B, alpha)
            pr = sp['size'] * (1.0 + 0.24 * math.sin(t * 0.05 + sp['phase']))
            c.create_oval(x-pr, y-pr, x+pr, y+pr, fill=col, outline="")

        # Rotating segmented arcs
        arc_r1 = int(field_r * 0.96)
        arc_r2 = int(field_r * 0.78)
        for start, extent, width, accent in (
            (self.rings_spin[0], 52 if self.speaking else 34, 3, False),
            ((self.rings_spin[0] + 148) % 360, 26, 2, True),
            ((self.rings_spin[2] + 28) % 360, 64 if self.user_speaking else 40, 3, False),
            ((self.rings_spin[2] + 212) % 360, 18, 2, True),
        ):
            rr = arc_r1 if width == 3 else arc_r2
            if accent and not self.paused:
                col = self._ac(accent_rgb[0], accent_rgb[1], accent_rgb[2], int(120 + 80 * activity))
            else:
                col = self._ac(R, G, B, int(ha * (1.2 if width == 3 else 0.7)))
            c.create_arc(
                FCX-rr, FCY-rr, FCX+rr, FCY+rr,
                start=start, extent=extent,
                outline=col, width=width, style="arc",
            )

        # Particle orb field
        field_limit = inner_r * (
            0.82 if self.paused else
            1.36 if self.speaking else
            1.16 if self.user_speaking else
            1.0
        )
        for idx, p in enumerate(self.orb_particles):
            if p['orbit'] < 0.54:
                continue
            speed_mult = (
                0.10 if self.paused else
                3.10 if self.speaking else
                2.00 if self.user_speaking else
                1.10
            )
            angle = p['angle'] + t * p['speed'] * speed_mult
            wobble = 1.0 + (0.30 if self.speaking else 0.18) * math.sin(t * p['wobble'] + p['phase'])
            orbit = field_limit * p['orbit'] * wobble
            depth = 0.5 + 0.5 * math.sin(angle * 2.0 + t * 0.013 + p['phase'])
            y_squash = 0.62 + depth * 0.38
            drift = (8.0 if self.speaking else 5.0 if self.user_speaking else 4.0) * p['depth']
            x = FCX + math.cos(angle) * orbit + math.sin(t * 0.011 + p['phase']) * drift
            y = FCY + math.sin(angle) * orbit * y_squash + math.cos(t * 0.010 + p['phase']) * drift
            base_alpha = int((18 + 155 * p['depth']) * (0.24 + activity * 0.86) * (0.45 + depth * 0.75))
            if self.paused:
                base_alpha = int(base_alpha * 0.40)
            if idx % 11 == 0 and not self.paused:
                col = self._ac(accent_rgb[0], accent_rgb[1], accent_rgb[2], min(255, base_alpha + 25))
            elif self.user_speaking and idx % 7 == 0:
                col = self._ac(167, 185, 215, min(255, base_alpha + 20))
            else:
                col = self._ac(R, G, B, base_alpha)
            pr = p['size'] * (0.70 if self.paused else 0.90 + depth * 0.65 + 0.30 * activity * p['depth'])
            c.create_oval(x-pr, y-pr, x+pr, y+pr, fill=col, outline="")
            if idx % 18 == 0 and not self.paused:
                c.create_line(
                    FCX + (x-FCX) * 0.18,
                    FCY + (y-FCY) * 0.18,
                    x, y,
                    fill=self._ac(R, G, B, int(18 + 35 * p['depth'] * activity)),
                    width=1,
                )

        # Center void keeps the orb airy instead of lens-like.
        void_r = int(inner_r * (0.18 if self.paused else 0.12))
        if void_r > 0:
            c.create_oval(
                FCX-void_r, FCY-void_r, FCX+void_r, FCY+void_r,
                fill=C_BG,
                outline="",
            )

        # Núcleo rojo inspirado en el reactor de arco de la referencia.
        core_r = max(10, int(inner_r * 0.62))
        core_pulse = 0.72 + 0.28 * math.sin(t * (0.20 if self.speaking else 0.10))
        core_alpha = int((95 if self.paused else 150 + 85 * core_pulse) * activity)
        c.create_oval(
            FCX-core_r, FCY-core_r, FCX+core_r, FCY+core_r,
            fill=self._ac(3, 18, 24, int(190 * activity)),
            outline=self._ac(255, 70, 52, min(255, int(core_alpha * 0.9))), width=3,
        )
        for scale, width, color, alpha in (
            (0.86, 4, (231, 182, 107), core_alpha + 35),
            (0.63, 2, (255, 225, 163), core_alpha + 55),
            (0.40, 2, (255, 92, 70), core_alpha + 20),
        ):
            rr = int(core_r * scale)
            c.create_oval(
                FCX-rr, FCY-rr, FCX+rr, FCY+rr,
                outline=self._ac(*color, min(255, alpha)), width=width,
            )
        c.create_oval(
            FCX-int(core_r*0.19), FCY-int(core_r*0.19),
            FCX+int(core_r*0.19), FCY+int(core_r*0.19),
            fill=self._ac(255, 239, 203, min(255, int(210 * core_pulse * activity))),
            outline="",
        )
        for angle in range(0, 360, 30):
            rad = math.radians(angle + t * 0.34)
            inner = core_r * 0.90
            outer = core_r * (1.13 if self.speaking else 1.05)
            c.create_line(
                FCX + math.cos(rad) * inner, FCY + math.sin(rad) * inner,
                FCX + math.cos(rad) * outer, FCY + math.sin(rad) * outer,
                fill=self._ac(207, 118, 91, min(255, core_alpha)), width=2,
            )

    def _draw_orb(self, c):
        """Dibuja un reactor mecánico por capas, con respuesta al estado de voz."""
        state = "PAUSED" if self.paused else self._jarvis_state
        t = self.tick
        center_x = self.FCX - min(88, max(54, int((self.CENTER_X1-self.CENTER_X0)*0.13)))
        center_y = self.FCY - 4
        pulse = (
            1.0 + 0.045 * math.sin(t * 0.21)
            if self.speaking else
            1.0 + 0.025 * math.sin(t * 0.11)
        )
        radius = max(104, int(min(self.FACE * 0.31, (self.H - HDR_H - CONTROL_H) * 0.37, 158) * pulse))
        rotation = 0.0 if self.paused else t * (0.72 if self.speaking else 0.32)
        energy = 0.18 if self.paused else 0.38 if state == "LISTENING" else 0.76 if self.user_speaking else 0.92

        # Sombra, carcasa y reflejo rojo alrededor del reactor.
        c.create_oval(center_x-radius*1.18, center_y-radius*1.18,
                      center_x+radius*1.18, center_y+radius*1.18,
                      fill="#0D1017", outline="#443A3B", width=2)
        aura = 0.72 + 0.28 * math.sin(t * (0.18 if self.speaking else 0.075))
        for layer in range(8, 0, -1):
            glow_r = radius * (0.55 + layer * 0.075)
            glow_alpha = int((7 + layer * 3) * energy * aura)
            c.create_oval(center_x-glow_r, center_y-glow_r,
                          center_x+glow_r, center_y+glow_r,
                          fill=self._ac(255, 43, 33, glow_alpha), outline="")

        c.create_oval(center_x-radius, center_y-radius,
                      center_x+radius, center_y+radius,
                      fill="#171922", outline="#836A46", width=3)
        for ring_r, color, width in (
            (radius*0.93, "#E7B66B", 2),
            (radius*0.86, "#39343D", 7),
            (radius*0.68, "#CF765B", 3),
            (radius*0.48, "#836A46", 3),
        ):
            c.create_oval(center_x-ring_r, center_y-ring_r,
                          center_x+ring_r, center_y+ring_r,
                          outline=color, width=width)

        # Doce placas radiales forman la carcasa del reactor, en lugar de un
        # campo de partículas genérico.
        for index in range(12):
            angle = math.radians(rotation + index * 30)
            half = math.radians(7.0)
            points = []
            for r, a in (
                (radius*0.57, angle-half),
                (radius*0.84, angle-half*0.62),
                (radius*0.84, angle+half*0.62),
                (radius*0.57, angle+half),
            ):
                points.extend((center_x + math.cos(a)*r, center_y + math.sin(a)*r))
            c.create_polygon(
                *points,
                fill="#28232A",
                outline="#836A46",
                width=1,
            )

        # Segmentos brillantes giran en sentidos opuestos en las tres pistas.
        for ring_r, count, extent, width, phase, color in (
            (radius*0.92, 8, 22, 6, rotation, "#FFE1A3"),
            (radius*0.75, 6, 31, 5, -rotation*1.45, "#E7B66B"),
            (radius*0.56, 4, 40, 4, rotation*2.1, "#FFF1D1"),
        ):
            for index in range(count):
                start = phase + index * (360 / count)
                alpha = int(120 + 110*energy)
                c.create_arc(
                    center_x-ring_r, center_y-ring_r,
                    center_x+ring_r, center_y+ring_r,
                    start=start, extent=extent,
                    style="arc", outline=self._ac(231, 182, 107, alpha), width=width,
                )

        # Centro metálico, ocho bobinas y un núcleo blanco-cian pulsante.
        housing_r = radius*0.46
        c.create_oval(center_x-housing_r, center_y-housing_r,
                      center_x+housing_r, center_y+housing_r,
                      fill="#171922", outline="#E7B66B", width=4)
        coil_r = radius*0.34
        c.create_oval(center_x-coil_r, center_y-coil_r,
                      center_x+coil_r, center_y+coil_r,
                      fill="#28232A", outline="#FFF1D1", width=7)
        inner_r = radius*0.24
        c.create_oval(center_x-inner_r, center_y-inner_r,
                      center_x+inner_r, center_y+inner_r,
                      fill="#33272A", outline="#CF765B", width=3)
        for index in range(8):
            angle = math.radians(-rotation*1.7 + index*45)
            x1 = center_x + math.cos(angle)*radius*0.25
            y1 = center_y + math.sin(angle)*radius*0.25
            x2 = center_x + math.cos(angle)*radius*0.37
            y2 = center_y + math.sin(angle)*radius*0.37
            c.create_line(x1, y1, x2, y2, fill="#FFF1D1", width=4)
        core_r = radius*0.145
        c.create_oval(center_x-core_r, center_y-core_r,
                      center_x+core_r, center_y+core_r,
                      fill="#FFF1D1", outline="#ffffff", width=3)
        c.create_oval(center_x-core_r*0.46, center_y-core_r*0.46,
                      center_x+core_r*0.46, center_y+core_r*0.46,
                      fill="#ffffff", outline="")

        # Pernos y barras de energía hacen visible el movimiento y el nivel de voz.
        for index in range(16):
            angle = math.radians(rotation*0.6 + index*22.5)
            bolt_r = radius*0.965
            bx = center_x + math.cos(angle)*bolt_r
            by = center_y + math.sin(angle)*bolt_r
            c.create_oval(bx-3, by-3, bx+3, by+3, fill="#FFE1A3", outline="")
        waveform = self._wave_jarvis if self.speaking else self._wave_user
        for index, value in enumerate(waveform):
            angle = math.radians(index * (360 / len(waveform)) + rotation)
            inner = radius*1.04
            outer = inner + max(3, value*0.55*energy)
            c.create_line(
                center_x+math.cos(angle)*inner, center_y+math.sin(angle)*inner,
                center_x+math.cos(angle)*outer, center_y+math.sin(angle)*outer,
                fill="#CF765B" if index % 6 == 0 else "#E7B66B", width=2,
            )

        # Lecturas compactas alrededor del reactor: enlace, voz, micrófono y carga.
    def _draw_radar_frame(self, c):
        """Dibuja una reticula t?ctica tenue para dar profundidad al n?cleo."""
        cx = self.FCX - min(88, max(54, int((self.CENTER_X1-self.CENTER_X0)*0.13)))
        cy = self.FCY - 4
        core_radius = max(104, int(min(self.FACE * 0.31, (self.H - HDR_H - CONTROL_H) * 0.37, 158)))
        radius = core_radius * 1.10
        rotation = (self.tick * 0.52) % 360
        for scale, color, width in ((1.0, "#51483F", 1), (0.82, "#302B31", 1)):
            rr = radius * scale
            c.create_oval(cx-rr, cy-rr, cx+rr, cy+rr, outline=color, width=width)
        for index in range(36):
            angle = math.radians(index * 10 + rotation)
            inner = radius * (0.92 if index % 3 else 0.86)
            outer = radius * (1.00 if index % 3 else 1.04)
            c.create_line(cx+math.cos(angle)*inner, cy+math.sin(angle)*inner,
                          cx+math.cos(angle)*outer, cy+math.sin(angle)*outer,
                          fill="#836A46" if index % 3 == 0 else "#39343D",
                          width=2 if index % 3 == 0 else 1)
        sweep = rotation * 0.72
        c.create_arc(cx-radius, cy-radius, cx+radius, cy+radius,
                     start=sweep, extent=42, style="arc", outline="#B99A64", width=2)
        for angle in (0, 90, 180, 270):
            rad = math.radians(angle + rotation * 0.15)
            x1, y1 = cx + math.cos(rad)*radius*0.78, cy + math.sin(rad)*radius*0.78
            x2, y2 = cx + math.cos(rad)*radius*1.08, cy + math.sin(rad)*radius*1.08
            c.create_line(x1, y1, x2, y2, fill="#5D5141", width=1)

    def _draw_center_sensor_stack(self, c):
        """Panel central con medidas reales y un analizador de audio animado."""
        x = self.FCX + min(92, max(60, int((self.CENTER_X1-self.CENTER_X0)*0.14)))
        y = HDR_H + 66
        w = max(184, self.CENTER_X1 - x - 12)
        h = min(358, self.CTRL_Y - y - 42)
        if h < 240:
            return
        c.create_rectangle(x, y, x+w, y+h, fill="#171922", outline="#51483F", width=1)
        self._bracket(c, x, y, w, h, col="#836A46", bl=10)
        c.create_rectangle(x+1, y+1, x+w-1, y+37, fill="#201F27", outline="")
        c.create_text(x+12, y+13, text="SENSORES / SISTEMA", fill="#E7B66B",
                      font=font_display(9), anchor="w")
        c.create_text(x+w-12, y+14, text="EN DIRECTO", fill="#B3A68F",
                      font=font_body(8), anchor="e")

        gap = 8
        tile_w = (w - 30) / 2
        for i, (label, key, color) in enumerate((("CPU", "cpu", C_PRI), ("MEMORIA", "ram", C_BLUE))):
            tx = x+10+i*(tile_w+gap)
            ty = y+48
            value = max(0.0, min(100.0, float(self._stats.get(key, 0.0))))
            c.create_rectangle(tx, ty, tx+tile_w, ty+68, fill="#201F27", outline="#39343D")
            c.create_text(tx+8, ty+13, text=label, fill="#A79B87", font=font_display(7), anchor="w")
            c.create_text(tx+8, ty+37, text=f"{value:.0f}%", fill=color, font=font_display(16), anchor="w")
            c.create_rectangle(tx+8, ty+53, tx+tile_w-8, ty+57, fill="#39343D", outline="")
            c.create_rectangle(tx+8, ty+53, tx+8+(tile_w-16)*value/100, ty+57, fill=color, outline="")

        wave_y = y+143
        c.create_text(x+10, wave_y, text="ANALIZADOR DE AUDIO", fill="#B3A68F",
                      font=font_display(8), anchor="w")
        c.create_text(x+w-10, wave_y, text="ENTRADA" if not self.speaking else "SALIDA",
                      fill=C_GREEN if not self.speaking else C_BLUE,
                      font=font_body_bold(8), anchor="e")
        graph_top, graph_bottom = wave_y+18, wave_y+88
        c.create_rectangle(x+10, graph_top, x+w-10, graph_bottom,
                           fill="#11131A", outline="#302B31")
        wave = self._wave_jarvis if self.speaking else self._wave_user
        bars = max(16, min(28, len(wave)))
        stride = (w-32) / bars
        for i in range(bars):
            v = wave[i % len(wave)] / 30.0
            bh = 4 + min(1.0, v) * (graph_bottom-graph_top-12)
            bx = x+16+i*stride
            by = (graph_top+graph_bottom)/2
            c.create_rectangle(bx, by-bh/2, bx+max(2, stride-2), by+bh/2,
                               fill="#E7B66B" if i % 4 == 0 else "#A7834D", outline="")

        net_y = graph_bottom + 26
        up = max(0.0, self._stats.get("net_up", 0.0))
        down = max(0.0, self._stats.get("net_down", 0.0))
        c.create_text(x+10, net_y, text="RED / KB/S", fill="#A79B87",
                      font=font_display(7), anchor="w")
        c.create_text(x+w-10, net_y, text=f"TX {up:.0f} / RX {down:.0f}",
                      fill="#EFE9DD", font=font_body(8), anchor="e")
        c.create_line(x+10, net_y+13, x+w-10, net_y+13, fill="#39343D", width=1)
        backend = "GEMINI / ENLACE ACTIVO" if self._jarvis_state in {"LISTENING", "SPEAKING", "THINKING"} else "GEMINI / CONECTANDO"
        c.create_oval(x+12, net_y+27, x+19, net_y+34,
                      fill=C_GREEN if "ACTIVO" in backend else C_GOLD, outline="")
        c.create_text(x+26, net_y+30, text=backend, fill="#C7B99F",
                      font=font_body_bold(8), anchor="w")

    def _draw_flight_cameo(self, c):
        """Bandeja inferior futurista con archivo visual y estado del sistema."""
        if not self._flight_clips:
            return
        panel_x = self.CENTER_X0 + 10
        panel_w = self.CENTER_X1 - self.CENTER_X0 - 20
        panel_h = 108
        panel_y = self.H - FOOTER_H - panel_h - 4
        c.create_rectangle(panel_x, panel_y, panel_x+panel_w, panel_y+panel_h,
                           fill="#15171F", outline="#51483F", width=1)
        self._bracket(c, panel_x, panel_y, panel_w, panel_h, col="#836A46", bl=9)
        c.create_line(panel_x+154, panel_y+8, panel_x+154, panel_y+panel_h-8,
                      fill="#39343D", width=1)
        video_w = min(248, panel_w-330)
        video_x = (self.CENTER_X0+self.CENTER_X1-video_w)//2
        c.create_line(video_x-10, panel_y+8, video_x-10, panel_y+panel_h-8,
                      fill="#39343D", width=1)
        c.create_line(video_x+video_w+10, panel_y+8, video_x+video_w+10, panel_y+panel_h-8,
                      fill="#39343D", width=1)

        c.create_text(panel_x+12, panel_y+18, text="VIGILANCIA DE JARVIS", fill="#E7B66B",
                      font=font_display(8), anchor="w")
        c.create_text(panel_x+12, panel_y+39, text="IRON MAN / AVENGERS", fill="#EFE9DD",
                      font=font_body_bold(8), anchor="w")
        c.create_text(panel_x+12, panel_y+58, text=f"{len(self._flight_clips):02d} SECUENCIAS",
                      fill="#B3A68F", font=font_display(8), anchor="w")
        c.create_text(panel_x+12, panel_y+77, text="FEED DE VIGILANCIA",
                      fill="#836A46", font=font_body(7), anchor="w")

        clip = self._flight_clip or self._flight_clips[0]
        elapsed = max(0.0, time.monotonic()-self._flight_cameo_started) if self._flight_cameo_started else 0.0
        active = bool(self._flight_cameo_started and elapsed < self._flight_cameo_duration)
        frames = clip["frames"]
        frame_index = int(elapsed*1000/clip["frame_ms"]) % len(frames) if active else 0
        c.create_rectangle(video_x, panel_y+5, video_x+video_w, panel_y+panel_h-5,
                           fill="#10131A", outline="#836A46", width=1)
        c.create_text(video_x+8, panel_y+13,
                      text=clip["title"] if active else "VIGILANCIA / EN ESPERA",
                      fill="#F0D7A7" if active else "#B3A68F",
                      font=font_display(7), anchor="w")
        image_x = video_x+(video_w-218)//2
        c.create_image(image_x, panel_y+19, image=frames[frame_index], anchor="nw")
        if active:
            caption = clip["caption"]
            progress = min(1.0, elapsed/self._flight_cameo_duration)
        else:
            caption = "FEED DE VIGILANCIA ACTIVO"
            progress = 0.0
        c.create_text(video_x+8, panel_y+101, text=caption,
                      fill="#B3A68F", font=font_body(7), anchor="w")
        c.create_rectangle(video_x+video_w-40, panel_y+103,
                           video_x+video_w-8, panel_y+105, fill="#39343D", outline="")
        if active:
            c.create_rectangle(video_x+video_w-40, panel_y+103,
                               video_x+video_w-40+32*progress, panel_y+105,
                               fill=C_PRI, outline="")

        right_x = video_x+video_w+20
        status = self._state_badge_text("PAUSED" if self.paused else self._jarvis_state).upper()
        c.create_text(right_x, panel_y+18, text="SISTEMA / ESTADO", fill="#E7B66B",
                      font=font_display(8), anchor="w")
        c.create_oval(right_x, panel_y+31, right_x+7, panel_y+38,
                      fill=self._state_color("PAUSED" if self.paused else self._jarvis_state), outline="")
        c.create_text(right_x+12, panel_y+35, text=status, fill="#EFE9DD",
                      font=font_body_bold(8), anchor="w")
        c.create_text(right_x, panel_y+57, text=f"GEMINI  /  {self._current_voice.upper()}",
                      fill="#B3A68F", font=font_body(8), anchor="w")
        c.create_text(right_x, panel_y+78,
                      text=f"CPU {self._stats['cpu']:.0f}%   MEM {self._stats['ram']:.0f}%",
                      fill="#A79B87", font=font_body(8), anchor="w")

    def _draw_hud_modules(self, c):
        """Tarjetas de estado del backend y audio, siempre verificables."""
        center_w = self.CENTER_X1 - self.CENTER_X0
        gap = 8
        tile_w = min(210, int((center_w - 32 - gap * 2) / 3))
        if tile_w < 104:
            return
        total_w = tile_w * 3 + gap * 2
        start_x = self.CENTER_X0 + (center_w - total_w) / 2
        y = HDR_H + 7
        h = 43
        state = "ENLACE ACTIVO" if self._jarvis_state in {"LISTENING", "SPEAKING", "THINKING"} else "CONECTANDO"
        microphone = "ENTRADA ACTIVA" if not self.muted and not self.paused else "ENTRADA EN PAUSA"
        modules = [
            ("MOTOR DE IA", "GEMINI LIVE  \u00b7  " + state, C_PRI),
            ("MICROFONO", "16 kHz  \u00b7  " + microphone, C_GREEN if not self.muted else C_ORG),
            ("VOZ DE JARVIS", f"{self._current_voice.upper()}  \u00b7  24 kHz", C_BLUE),
        ]
        for index, (title, value, accent) in enumerate(modules):
            x = start_x + index * (tile_w + gap)
            c.create_rectangle(x, y, x+tile_w, y+h, fill="#1B1C24", outline="#39343D", width=1)
            c.create_line(x+1, y+1, x+tile_w-1, y+1, fill=accent, width=2)
            c.create_text(x+9, y+13, text=title, fill="#A79B87",
                          font=font_display(8), anchor="w")
            c.create_text(x+9, y+30, text=value, fill=C_TEXT,
                          font=font_body_bold(8 if tile_w < 170 else 9), anchor="w")
            c.create_oval(x+tile_w-14, y+9, x+tile_w-8, y+15,
                          fill=accent if self.status_blink else "#5D5141", outline="")

    def _draw_visor_core(self, c):
        """Óptica de visor: retícula de enfoque, barrido y señal de voz."""
        cx, cy = self.FCX, self.FCY - 28
        radius = min(168, max(95, (self.CENTER_X1 - self.CENTER_X0) * 0.24))
        blue, pale, dim = "#36BFFF", "#BCEEFF", "#275B79"
        for fraction, width, color in ((1.0, 2, dim), (0.82, 2, blue), (0.54, 1, pale)):
            rr = radius * fraction
            c.create_oval(cx-rr, cy-rr, cx+rr, cy+rr, outline=color, width=width)
        for index in range(24):
            angle = math.radians(index * 15 + self.tick * 0.14)
            inner = radius * (0.89 if index % 3 else 0.83)
            outer = radius * (1.02 if index % 3 else 1.09)
            c.create_line(cx + math.cos(angle)*inner, cy + math.sin(angle)*inner,
                          cx + math.cos(angle)*outer, cy + math.sin(angle)*outer,
                          fill=pale if index % 3 == 0 else dim, width=2 if index % 3 == 0 else 1)
        for ring, count, extent, speed in ((0.94, 6, 33, 0.48), (0.70, 4, 43, -0.76)):
            rr = radius * ring
            for index in range(count):
                c.create_arc(cx-rr, cy-rr, cx+rr, cy+rr,
                             start=self.tick*speed + index*360/count, extent=extent,
                             style="arc", outline=blue, width=4)
        sweep = math.radians(self.tick * 0.7)
        c.create_line(cx, cy, cx+math.cos(sweep)*radius*0.82,
                      cy-math.sin(sweep)*radius*0.82, fill=blue, width=2)
        c.create_line(cx-radius*0.37, cy, cx+radius*0.37, cy, fill=dim)
        c.create_line(cx, cy-radius*0.37, cx, cy+radius*0.37, fill=dim)
        c.create_oval(cx-7, cy-7, cx+7, cy+7, outline=pale, width=2)
        c.create_text(cx, cy+radius+27, text="VISOR / ANÁLISIS DE ENTORNO",
                      fill=pale, font=font_display(10))
        c.create_text(cx, cy+radius+45,
                      text=f"GEMINI LIVE  ·  {'VOZ ACTIVA' if self.speaking else 'ENLACE DE VOZ'}",
                      fill=blue, font=font_body_bold(9))

    def _draw_tactical_core(self, c):
        """Plano táctico con capas hexagonales y marcador de barrido."""
        cx, cy = self.FCX, self.FCY - 28
        radius = min(166, max(95, (self.CENTER_X1 - self.CENTER_X0) * 0.23))
        gold, red, dim = "#FFBA58", "#EF5C45", "#6D3A29"
        for scale, color, width in ((1.16, dim, 2), (0.94, gold, 3), (0.62, red, 2)):
            rr = radius * scale
            points = [coord for index in range(6)
                      for coord in (cx + math.cos(math.radians(index*60-30))*rr,
                                    cy + math.sin(math.radians(index*60-30))*rr)]
            c.create_polygon(*points, fill="", outline=color, width=width)
        for index in range(6):
            angle = math.radians(index*60-30)
            c.create_line(cx+math.cos(angle)*radius*0.65, cy+math.sin(angle)*radius*0.65,
                          cx+math.cos(angle)*radius*1.12, cy+math.sin(angle)*radius*1.12,
                          fill=gold, width=2)
        scan_y = cy-radius*0.75 + (self.tick*1.2) % (radius*1.5)
        c.create_line(cx-radius*0.76, scan_y, cx+radius*0.76, scan_y,
                      fill=red, width=2)
        for index in range(12):
            a = math.radians(index*30 + self.tick*0.22)
            x = cx+math.cos(a)*radius*0.78
            y = cy+math.sin(a)*radius*0.78
            c.create_oval(x-2, y-2, x+2, y+2, fill=gold, outline="")
        c.create_text(cx, cy-9, text="J.A.R.V.I.S", fill="#FFE5B4",
                      font=font_display(19))
        c.create_text(cx, cy+18, text="MATRIZ DE VIGILANCIA", fill=gold,
                      font=font_display(9))
        c.create_text(cx, cy+radius+34,
                      text=f"GEMINI LIVE   /   CPU {self._stats['cpu']:.0f}%   /   MEM {self._stats['ram']:.0f}%",
                      fill="#FFD399", font=font_body_bold(9))

    def _draw(self):
        c  = self.bg
        W  = self.W
        H  = self.H
        t  = self.tick
        c.delete("all")

        if self._template_background_photo is not None:
            c.create_image(0, 0, image=self._template_background_photo, anchor="nw")

        # ── Arka plan ────────────────────────────────────────────────────────
        # Nokta ızgarası — çok ince
        if self._ui_template == "sukima":
            step = 48
            for x in range(0, W, step):
                for y in range(0, H, step):
                    c.create_rectangle(x, y, x+1, y+1, fill=C_DIMMER, outline="")

        # Tarama çizgisi (yavaş, çok soluk)
        scan_y = (t * 0.7) % (H + 60) - 30
        for i in range(2):
            ly = (scan_y + i * 20) % H
            c.create_line(0, ly, W, ly+35, fill="#171922", width=1)

        # Partiküller
        R, G, B = self._orb_rgb()
        for p in self.particles:
            if self.speaking:
                col = self._ac(255, 110, 0, p['a'])
            else:
                col = self._ac(R, G, B, p['a'])
            r = p['r']
            c.create_oval(p['x']-r, p['y']-r, p['x']+r, p['y']+r,
                          fill=col, outline="")

        # ── Bölücü çizgiler (ince, soluk) ────────────────────────────────────
        c.create_line(self.LEFT_W, HDR_H, self.LEFT_W, H-FOOTER_H,
                      fill=C_DIM, width=1)
        c.create_line(W-self.RIGHT_W, HDR_H, W-self.RIGHT_W, H-FOOTER_H,
                      fill=C_DIM, width=1)

        # ── Yan paneller ──────────────────────────────────────────────────────
        self._draw_left_panel(c)
        self._draw_right_panel(c)

        # ── Orb ──────────────────────────────────────────────────────────────
        if self._ui_template == "sukima":
            self._draw_radar_frame(c)
            self._draw_orb(c)
            self._draw_center_sensor_stack(c)
        elif self._ui_template == "visor":
            self._draw_visor_core(c)
        else:
            self._draw_tactical_core(c)
        self._draw_hud_modules(c)

        state_label = self._state_badge_text("PAUSED" if self.paused else self._jarvis_state)
        state_col = self._state_color(state_label)
        draw_text_glow(c, self.FCX, self.CTRL_Y - 34, text=SYSTEM_NAME,
                       fill=C_TEXT, glow_color=C_MID, font=font_display(18))
        c.create_text(self.FCX, self.CTRL_Y - 12, text=f"● {state_label.title()}",
                      fill=state_col, font=font_body_bold(11))

        # ── HEADER ───────────────────────────────────────────────────────────
        c.create_rectangle(0, 0, W, HDR_H, fill=C_BG, outline="")
        # Alt çizgi — teal parlak
        c.create_line(0, HDR_H, W, HDR_H, fill=C_MID, width=1)
        for i in range(3):
            a = 60 - i * 18
            c.create_line(0, HDR_H-1-i, W, HDR_H-1-i,
                          fill=self._ac(231, 182, 107, a), width=1)

        # Büyük başlık
        draw_text_glow(c, W//2+18, 24, text=SYSTEM_NAME,
                       fill=C_PRI, glow_color=C_MID, font=font_display(26))
        c.create_text(W//2+18, 52, text="ASISTENTE EN TIEMPO REAL / SUKIMA LABS",
                      fill=C_MID, font=font_body(10))
        if self._brand_icon_photo:
            c.create_image(W//2-245, 35, image=self._brand_icon_photo, anchor="center")

        indicator_state = "PAUSED" if self.paused else self._jarvis_state
        ind_col = self._state_color(indicator_state)
        indicator_text = self._state_badge_text(indicator_state)
        sym = "●" if self.status_blink else "○"
        c.create_text(W-22, 36, text=f"{sym}  {indicator_text}",
                      fill=ind_col, font=font_body_bold(11), anchor="e")

        # ── FOOTER ───────────────────────────────────────────────────────────
        c.create_rectangle(0, H-FOOTER_H, W, H, fill=C_BG, outline="")
        c.create_line(0, H-FOOTER_H, W, H-FOOTER_H, fill=C_DIM, width=1)
        brand_x = self.LEFT_W+10
        c.create_rectangle(brand_x, H-27, brand_x+166, H-6,
                           fill="#1B1C24", outline="#51483F", width=1)
        self._bracket(c, brand_x, H-27, 166, 21, col="#836A46", bl=5)
        c.create_text(brand_x+10, H-16, fill="#E7B66B", font=font_display(7),
                      text="SUKIMA LABS  /  JARVIS", anchor="w")
        c.create_text(self.FCX, H-16, fill="#A79B87", font=font_body(7),
                       text=f"GEMINI LIVE  /  {len(self._flight_clips):02d} ESCENAS  /  {UI_TEMPLATES[self._ui_template]}")
        c.create_text(W-18, H-16, fill="#B3A68F", font=font_body(8),
                       text="[F4] AUDIO  [F5] PAUSA  [F6] INTERFAZ  [F9] MINI  [F11] PANTALLA  [ESC] SALIR", anchor="e")
        self._draw_flight_cameo(c)

    def wait_for_api_key(self):
        while not self._api_key_ready:
            time.sleep(0.1)

    def _show_setup_ui(self, edit_mode: bool = False):
        self._close_setup_ui()

        self.setup_frame = tk.Frame(self.root, bg="#11131A",
                                    highlightbackground=C_PRI,
                                    highlightthickness=1)
        setup_w = min(820, max(620, int(self.W * 0.48)))
        setup_h = min(720, max(560, int(self.H * 0.62)))
        self.setup_frame.place(relx=0.5, rely=0.5, anchor="center", width=setup_w, height=setup_h)
        self.setup_frame.pack_propagate(False)

        title = "◈ AJUSTES DE GEMINI" if edit_mode else "◈ CONFIGURACIÓN INICIAL"
        subtitle = (
            "Actualiza el motor y la configuración."
            if edit_mode else
            "Elige Gemini o LM Studio. LM Studio no requiere clave API."
        )
        config = load_app_config()

        # ── Backend secimi ───────────────────────────────────────────────────
        tk.Label(self.setup_frame, text="MOTOR DE IA",
                 fg=C_DIM, bg="#11131A", font=font_body(12)).pack(pady=(18, 4))
        self._backend_var = tk.StringVar(value=str(config.get("backend", "gemini")))
        backend_row = tk.Frame(self.setup_frame, bg="#11131A")
        backend_row.pack(pady=(0, 6))
        tk.Radiobutton(backend_row, text="Gemini en la nube", variable=self._backend_var,
                       value="gemini", fg=C_TEXT, bg="#11131A",
                       activebackground="#11131A", selectcolor="#34313A",
                       font=font_body(12)).pack(side="left", padx=12)
        tk.Radiobutton(backend_row, text="LM Studio (local)", variable=self._backend_var,
                       value="lmstudio", fg=C_TEXT, bg="#11131A",
                       activebackground="#11131A", selectcolor="#34313A",
                       font=font_body(12)).pack(side="left", padx=12)

        tk.Label(self.setup_frame, text=title,
                 fg=C_PRI, bg="#11131A", font=font_display(20)).pack(pady=(28, 6))
        tk.Label(self.setup_frame, text=subtitle,
                 fg=C_MID, bg="#11131A", font=font_body(13)).pack(pady=(0, 14))
        tk.Label(self.setup_frame, text="CLAVE API DE GEMINI",
                 fg=C_DIM, bg="#11131A", font=font_body(12)).pack(pady=(8, 4))

        self.api_entry = tk.Entry(
            self.setup_frame, width=60,
            fg=C_TEXT, bg="#171922", insertbackground=C_TEXT,
            borderwidth=0, font=font_body(14), show="*")
        self.api_entry.pack(pady=(0, 8), ipady=5)

        current_key = str(config.get("gemini_api_key", "") or "")
        if current_key:
            self.api_entry.insert(0, current_key)

        tk.Label(self.setup_frame, text="CLAVE API DE YOUTUBE",
                 fg=C_DIM, bg="#11131A", font=font_body(12)).pack(pady=(10, 4))

        self.youtube_api_entry = tk.Entry(
            self.setup_frame, width=60,
            fg=C_TEXT, bg="#171922", insertbackground=C_TEXT,
            borderwidth=0, font=font_body(14), show="*")
        self.youtube_api_entry.pack(pady=(0, 8), ipady=5)
        current_youtube_key = str(config.get("youtube_api_key", "") or "")
        if current_youtube_key:
            self.youtube_api_entry.insert(0, current_youtube_key)

        tk.Label(self.setup_frame, text="USUARIO O CANAL DE YOUTUBE",
                 fg=C_DIM, bg="#11131A", font=font_body(12)).pack(pady=(10, 4))

        self.youtube_handle_entry = tk.Entry(
            self.setup_frame, width=60,
            fg=C_TEXT, bg="#171922", insertbackground=C_TEXT,
            borderwidth=0, font=font_body(14))
        self.youtube_handle_entry.pack(pady=(0, 8), ipady=5)
        current_handle = str(config.get("youtube_channel_handle", "") or "")
        if current_handle:
            self.youtube_handle_entry.insert(0, current_handle)

        # ── LM Studio (yerel) ayarlari ───────────────────────────────────────
        tk.Label(self.setup_frame, text="URL DE LM STUDIO (modo local)",
                 fg=C_DIM, bg="#11131A", font=font_body(12)).pack(pady=(10, 4))
        self.lmstudio_url_entry = tk.Entry(
            self.setup_frame, width=60,
            fg=C_TEXT, bg="#171922", insertbackground=C_TEXT,
            borderwidth=0, font=font_body(13))
        self.lmstudio_url_entry.pack(pady=(0, 6), ipady=4)
        self.lmstudio_url_entry.insert(0, str(config.get("lmstudio_base_url", "http://127.0.0.1:1234/v1") or ""))

        tk.Label(self.setup_frame, text="ID DEL MODELO DE LM STUDIO",
                 fg=C_DIM, bg="#11131A", font=font_body(12)).pack(pady=(6, 4))
        self.lmstudio_model_entry = tk.Entry(
            self.setup_frame, width=60,
            fg=C_TEXT, bg="#171922", insertbackground=C_TEXT,
            borderwidth=0, font=font_body(13))
        self.lmstudio_model_entry.pack(pady=(0, 8), ipady=4)
        self.lmstudio_model_entry.insert(0, str(config.get("lmstudio_model", "local-model") or "local-model"))

        buttons = tk.Frame(self.setup_frame, bg="#11131A")
        buttons.pack(pady=14)

        tk.Button(buttons, text="▸ GUARDAR",
                  command=self._save_api_key, bg=C_BG, fg=C_PRI,
                  activebackground="#39343D", font=font_body_bold(13),
                  borderwidth=0, padx=24, pady=10).pack(side="left", padx=8)

        if edit_mode:
            tk.Button(buttons, text="CERRAR",
                      command=self._close_setup_ui, bg="#1B1C24", fg=C_DIM,
                      activebackground="#39343D", font=font_body_bold(13),
                      borderwidth=0, padx=24, pady=10).pack(side="left", padx=8)

    def _save_api_key(self):
        was_ready = self._api_key_ready
        backend = getattr(self, "_backend_var", None)
        backend_val = backend.get() if backend else "gemini"
        key = self.api_entry.get().strip() if self.api_entry else ""
        # Gemini modunda anahtar zorunlu; LM Studio modunda degil.
        if backend_val == "gemini" and not key:
            return

        youtube_key = self.youtube_api_entry.get().strip() if self.youtube_api_entry else ""
        youtube_handle = self.youtube_handle_entry.get().strip() if self.youtube_handle_entry else ""
        lmstudio_url = (
            self.lmstudio_url_entry.get().strip()
            if getattr(self, "lmstudio_url_entry", None) else "http://127.0.0.1:1234/v1"
        )
        lmstudio_model = (
            self.lmstudio_model_entry.get().strip()
            if getattr(self, "lmstudio_model_entry", None) else "local-model"
        )

        save_app_config(
            {
                "backend": backend_val,
                "gemini_api_key": key,
                "youtube_api_key": youtube_key,
                "youtube_channel_handle": youtube_handle,
                "voice": self._current_voice,
                "lmstudio_base_url": lmstudio_url or "http://127.0.0.1:1234/v1",
                "lmstudio_model": lmstudio_model or "local-model",
            }
        )
        self._close_setup_ui()
        self._api_key_ready = True
        self._refresh_settings_status()
        if was_ready:
            self.write_log("SYS: Configuración actualizada.")
        else:
            self.set_state("LISTENING")
            self.write_log("SYS: JARVIS listo. Te escucho.")


