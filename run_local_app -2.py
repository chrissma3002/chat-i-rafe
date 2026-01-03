import math
import os
import queue
import re
import shutil
import signal
import socket
import subprocess
import threading
import time
import tkinter as tk
import urllib.request
import webbrowser
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import customtkinter as ctk

# ---------------- CONFIG ----------------
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
PROJECT_ROOT = Path(__file__).resolve().parent
DEV_ARGS_BASE = ["run", "dev", "--"]  # npm run dev -- ...


# ---------------- UTIL ----------------
def resolve_npm_path() -> str | None:
    override = os.environ.get("LOCAL_VITE_NPM_PATH")
    if override:
        candidate = Path(override).expanduser()
        if candidate.exists():
            return str(candidate)

    names = ["npm.cmd", "npm", "npm.exe"]
    for name in names:
        found = shutil.which(name)
        if found:
            return found

    windows_dirs = [
        Path(os.environ.get("ProgramFiles", "")) / "nodejs",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "nodejs",
        Path.home() / "AppData" / "Roaming" / "npm",
    ]
    unix_dirs = [
        Path("/usr/local/bin"),
        Path("/usr/bin"),
        Path("/opt/homebrew/bin"),
        Path.home() / ".nvm" / "versions",
    ]
    search_dirs = windows_dirs if os.name == "nt" else unix_dirs

    for base in search_dirs:
        for name in names:
            candidate = base / name
            if candidate.exists():
                return str(candidate)

    return None


def npm_cmd(npm_path: str, args: list[str]) -> list[str]:
    # On Windows, npm is often a .cmd shim that needs cmd.exe
    if os.name == "nt" and npm_path.lower().endswith((".cmd", ".bat")):
        return ["cmd.exe", "/c", npm_path, *args]
    return [npm_path, *args]


def now_ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def is_port_open(host: str, port: int, timeout: float = 0.25) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


@dataclass
class LogEvent:
    level: str  # "info" | "success" | "warning" | "error"
    message: str
    timestamp: str


# ---------------- APP ----------------
class ViteControlCenter(ctk.CTk):
    COLORS = {
        "bg": "#0b0c10",
        "panel": "#12131a",
        "panel2": "#171926",
        "border": "#26283a",
        "text": "#f3f4f6",
        "muted": "#a7adbb",
        "accent": "#6d5efc",
        "accent2": "#9b8cff",
        "success": "#2bd576",
        "warning": "#f5c043",
        "error": "#ff4d4d",
    }

    def __init__(self):
        super().__init__()

        ctk.set_appearance_mode("dark")

        # Note: I can't use the slur you requested as the app name.
        self.title("AI Control Center")
        self.geometry("980x700")
        self.minsize(980, 700)
        self.configure(fg_color=self.COLORS["bg"])
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        # State
        self.npm_path: str | None = None
        self.proc: subprocess.Popen | None = None
        self.proc_lock = threading.Lock()
        self.stop_event = threading.Event()

        self.server_ready = False
        self.server_start_time: datetime | None = None
        self.session_count = 0

        self.log_q: "queue.Queue[LogEvent]" = queue.Queue()

        # Settings (interactive)
        self.host_var = tk.StringVar(value=DEFAULT_HOST)
        self.port_var = tk.StringVar(value=str(DEFAULT_PORT))
        self.auto_launch_var = tk.BooleanVar(value=True)
        self.incognito_var = tk.BooleanVar(value=True)

        # Animation
        self._pulse_phase = 0.0
        self._ambient_phase = 0.0

        # Page transition animation
        self._current_page_name: str | None = None
        self._transitioning = False
        self._page_anim_token = 0

        # Toast animation
        self._toast_y = 30
        self._toast_anim_token = 0

        # Fonts
        family_ui = "Segoe UI Variable" if os.name == "nt" else "Helvetica"
        family_mono = "Consolas" if os.name == "nt" else "Menlo"
        self.font_h1 = ctk.CTkFont(family=family_ui, size=20, weight="bold")
        self.font_h2 = ctk.CTkFont(family=family_ui, size=14, weight="bold")
        self.font_body = ctk.CTkFont(family=family_ui, size=13)
        self.font_small = ctk.CTkFont(family=family_ui, size=11)
        self.font_mono = (family_mono, 11)

        # UI
        self._build_shell()
        self._build_pages()
        self._switch_page("Dashboard", animate=False)

        # Background loops
        self.after(50, self._drain_logs)
        self.after(16, self._animate)  # smoother UI animations
        self.after(1000, self._tick_uptime)

        # Start server
        self.start_server()

    # --------- Layout Shell ----------
    def _build_shell(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Left rail
        self.rail = ctk.CTkFrame(
            self,
            width=220,
            corner_radius=0,
            fg_color=self.COLORS["panel"],
            border_width=0,
        )
        self.rail.grid(row=0, column=0, sticky="nsw")
        self.rail.grid_propagate(False)

        # Brand block
        brand = ctk.CTkFrame(self.rail, fg_color="transparent")
        brand.pack(fill="x", padx=16, pady=(18, 10))

        badge = ctk.CTkFrame(
            brand, width=44, height=44, corner_radius=14, fg_color=self.COLORS["accent"]
        )
        badge.pack(side="left")
        badge.pack_propagate(False)
        ctk.CTkLabel(
            badge,
            text="AI",
            text_color="white",
            font=ctk.CTkFont(size=15, weight="bold"),
        ).place(relx=0.5, rely=0.5, anchor="center")

        titlebox = ctk.CTkFrame(brand, fg_color="transparent")
        titlebox.pack(side="left", padx=(10, 0), fill="x", expand=True)
        ctk.CTkLabel(
            titlebox,
            text="AI Control",
            font=self.font_h2,
            text_color=self.COLORS["text"],
        ).pack(anchor="w")
        ctk.CTkLabel(
            titlebox,
            text="Center",
            font=self.font_h2,
            text_color=self.COLORS["accent2"],
        ).pack(anchor="w")

        # Nav buttons
        self.nav_buttons: dict[str, ctk.CTkButton] = {}
        for name in ["Dashboard", "Logs", "Settings"]:
            btn = ctk.CTkButton(
                self.rail,
                text=name,
                height=42,
                corner_radius=14,
                fg_color="transparent",
                hover_color=self._blend(self.COLORS["panel2"], "#ffffff", 0.04),
                text_color=self.COLORS["muted"],
                anchor="w",
                command=lambda n=name: self._switch_page(n),
                font=self.font_body,
            )
            btn.pack(fill="x", padx=14, pady=6)
            self.nav_buttons[name] = btn

        # Rail footer status pill
        self.rail_status = ctk.CTkFrame(
            self.rail,
            corner_radius=16,
            fg_color=self.COLORS["panel2"],
            border_width=1,
            border_color=self.COLORS["border"],
        )
        self.rail_status.pack(side="bottom", fill="x", padx=14, pady=14)

        self.rail_dot = ctk.CTkFrame(
            self.rail_status,
            width=10,
            height=10,
            corner_radius=999,
            fg_color=self.COLORS["warning"],
        )
        self.rail_dot.pack(side="left", padx=(12, 8), pady=12)
        self.rail_dot.pack_propagate(False)

        self.rail_status_label = ctk.CTkLabel(
            self.rail_status,
            text="Starting…",
            text_color=self.COLORS["muted"],
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.rail_status_label.pack(side="left", pady=12)

        # Main area
        self.main = ctk.CTkFrame(self, fg_color="transparent")
        self.main.grid(row=0, column=1, sticky="nsew")
        self.main.grid_columnconfigure(0, weight=1)
        self.main.grid_rowconfigure(1, weight=1)

        # Top bar with ambient accent line (animated)
        self.topbar = ctk.CTkFrame(
            self.main,
            fg_color="transparent",
            height=62,
        )
        self.topbar.grid(row=0, column=0, sticky="ew", padx=20, pady=(18, 8))
        self.topbar.grid_columnconfigure(0, weight=1)

        self.page_title = ctk.CTkLabel(
            self.topbar,
            text="Dashboard",
            font=self.font_h1,
            text_color=self.COLORS["text"],
        )
        self.page_title.grid(row=0, column=0, sticky="w")

        self.ambient = ctk.CTkProgressBar(
            self.topbar,
            height=8,
            corner_radius=999,
            fg_color=self._blend(self.COLORS["panel2"], "#000000", 0.2),
            progress_color=self.COLORS["accent"],
        )
        self.ambient.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        self.ambient.set(0.2)

        # Toast
        self.toast = ctk.CTkLabel(
            self.main,
            text="",
            fg_color=self.COLORS["panel2"],
            corner_radius=14,
            text_color=self.COLORS["text"],
            font=self.font_small,
            padx=12,
            pady=8,
        )
        self.toast_visible = False

        # Page container
        self.page_container = ctk.CTkFrame(self.main, fg_color="transparent")
        self.page_container.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 20))
        self.page_container.grid_columnconfigure(0, weight=1)
        self.page_container.grid_rowconfigure(0, weight=1)

    def _build_pages(self):
        self.pages: dict[str, ctk.CTkFrame] = {}

        self.pages["Dashboard"] = self._build_dashboard(self.page_container)
        self.pages["Logs"] = self._build_logs(self.page_container)
        self.pages["Settings"] = self._build_settings(self.page_container)

        # Use place() for animated transitions
        for p in self.pages.values():
            p.place_forget()

    # --------- Page transitions ----------
    def _ease_out_cubic(self, t: float) -> float:
        t = max(0.0, min(1.0, t))
        return 1 - (1 - t) ** 3

    def _page_width(self) -> int:
        self.update_idletasks()
        w = int(self.page_container.winfo_width())
        return w if w > 10 else 800

    def _show_page_instant(self, name: str):
        for p in self.pages.values():
            p.place_forget()
        self.pages[name].place(x=0, y=0, relwidth=1, relheight=1)
        self._current_page_name = name

    def _animate_page_transition(self, from_name: str, to_name: str):
        if from_name == to_name:
            return

        # If a transition is already running, cancel it and fall back to instant switch
        # (prevents mid-transition weirdness and keeps things feeling smooth).
        if self._transitioning:
            self._page_anim_token += 1
            self._transitioning = False
            self._show_page_instant(to_name)
            return

        self._transitioning = True
        self._page_anim_token += 1
        token = self._page_anim_token

        w = self._page_width()
        from_page = self.pages[from_name]
        to_page = self.pages[to_name]

        from_page.place(x=0, y=0, relwidth=1, relheight=1)
        to_page.place(x=w, y=0, relwidth=1, relheight=1)

        start = time.perf_counter()
        duration = 0.26  # seconds

        def frame():
            if token != self._page_anim_token:
                self._transitioning = False
                return

            t = (time.perf_counter() - start) / duration
            if t >= 1.0:
                from_page.place_forget()
                to_page.place_configure(x=0)
                self._current_page_name = to_name
                self._transitioning = False
                return

            e = self._ease_out_cubic(t)
            x_from = int(-w * e)  # 0 -> -w
            x_to = int(w * (1.0 - e))  # w -> 0

            from_page.place_configure(x=x_from)
            to_page.place_configure(x=x_to)

            self.after(16, frame)  # ~60fps

        frame()

    def _switch_page(self, name: str, animate: bool = True):
        for k, btn in self.nav_buttons.items():
            if k == name:
                btn.configure(
                    fg_color=self._blend(self.COLORS["accent"], "#000000", 0.25),
                    text_color="white",
                    hover=False,
                )
            else:
                btn.configure(
                    fg_color="transparent",
                    text_color=self.COLORS["muted"],
                    hover=True,
                )

        self.page_title.configure(text=name)

        if self._current_page_name is None or not animate:
            self._show_page_instant(name)
            return

        self._animate_page_transition(self._current_page_name, name)

    # --------- Dashboard ----------
    def _build_dashboard(self, parent: ctk.CTkFrame) -> ctk.CTkFrame:
        page = ctk.CTkFrame(parent, fg_color="transparent")
        page.grid_columnconfigure(0, weight=2)
        page.grid_columnconfigure(1, weight=1)
        page.grid_rowconfigure(1, weight=1)

        # Status hero card
        hero = ctk.CTkFrame(
            page,
            corner_radius=20,
            fg_color=self.COLORS["panel2"],
            border_width=1,
            border_color=self.COLORS["border"],
        )
        hero.grid(row=0, column=0, sticky="ew", padx=(0, 14), pady=(0, 14))
        hero.grid_columnconfigure(0, weight=1)

        top = ctk.CTkFrame(hero, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 12))
        top.grid_columnconfigure(0, weight=1)

        self.hero_status = ctk.CTkLabel(
            top,
            text="Booting Vite…",
            font=self.font_h2,
            text_color=self.COLORS["warning"],
        )
        self.hero_status.grid(row=0, column=0, sticky="w")

        self.url_label = ctk.CTkLabel(
            top,
            text=self.current_url(),
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=self.COLORS["muted"],
        )
        self.url_label.grid(row=1, column=0, sticky="w", pady=(6, 0))

        # Stats row
        stats = ctk.CTkFrame(hero, fg_color="transparent")
        stats.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 14))
        stats.grid_columnconfigure((0, 1, 2), weight=1)

        self.stat_uptime = self._stat_card(stats, 0, "Uptime", "0s")
        self.stat_sessions = self._stat_card(stats, 1, "Sessions", "0")
        self.stat_state = self._stat_card(stats, 2, "State", "Starting")

        # Quick actions
        actions = ctk.CTkFrame(
            page,
            corner_radius=20,
            fg_color=self.COLORS["panel2"],
            border_width=1,
            border_color=self.COLORS["border"],
        )
        actions.grid(row=0, column=1, sticky="ew", pady=(0, 14))
        actions.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            actions,
            text="Quick Actions",
            font=self.font_h2,
            text_color=self.COLORS["text"],
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(16, 10))

        self.btn_new_session = ctk.CTkButton(
            actions,
            text="New Session",
            height=44,
            corner_radius=16,
            fg_color=self.COLORS["accent"],
            hover_color=self._blend(self.COLORS["accent"], "#ffffff", 0.08),
            text_color="white",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self.launch_session,
            state="disabled",
        )
        self.btn_new_session.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 10))

        self.btn_copy_url = ctk.CTkButton(
            actions,
            text="Copy URL",
            height=40,
            corner_radius=16,
            fg_color=self._blend(self.COLORS["panel"], "#ffffff", 0.04),
            hover_color=self._blend(self.COLORS["panel"], "#ffffff", 0.08),
            text_color=self.COLORS["text"],
            font=self.font_body,
            command=self.copy_url,
        )
        self.btn_copy_url.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 10))

        self.btn_restart = ctk.CTkButton(
            actions,
            text="Restart Server",
            height=40,
            corner_radius=16,
            fg_color=self._blend(self.COLORS["panel"], "#ffffff", 0.04),
            hover_color=self._blend(self.COLORS["panel"], "#ffffff", 0.08),
            text_color=self.COLORS["text"],
            font=self.font_body,
            command=self.restart_server,
        )
        self.btn_restart.grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 16))

        # Session timeline
        timeline = ctk.CTkFrame(
            page,
            corner_radius=20,
            fg_color=self.COLORS["panel2"],
            border_width=1,
            border_color=self.COLORS["border"],
        )
        timeline.grid(row=1, column=0, columnspan=2, sticky="nsew")
        timeline.grid_columnconfigure(0, weight=1)
        timeline.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(timeline, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 10))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text="Session Timeline",
            font=self.font_h2,
            text_color=self.COLORS["text"],
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            header,
            text="Each session is a separate browser window",
            font=self.font_small,
            text_color=self.COLORS["muted"],
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

        self.timeline_list = ctk.CTkScrollableFrame(
            timeline,
            corner_radius=16,
            fg_color=self._blend(self.COLORS["panel"], "#000000", 0.12),
        )
        self.timeline_list.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 16))

        return page

    def _stat_card(self, parent, col: int, label: str, value: str):
        card = ctk.CTkFrame(
            parent,
            corner_radius=16,
            fg_color=self._blend(self.COLORS["panel"], "#ffffff", 0.03),
            border_width=1,
            border_color=self.COLORS["border"],
        )
        card.grid(row=0, column=col, sticky="ew", padx=(0 if col == 0 else 10, 0))
        ctk.CTkLabel(
            card,
            text=label.upper(),
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=self.COLORS["muted"],
        ).pack(anchor="w", padx=12, pady=(10, 0))
        val = ctk.CTkLabel(
            card,
            text=value,
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=self.COLORS["text"],
        )
        val.pack(anchor="w", padx=12, pady=(4, 10))
        return val

    # --------- Logs ----------
    def _build_logs(self, parent: ctk.CTkFrame) -> ctk.CTkFrame:
        page = ctk.CTkFrame(parent, fg_color="transparent")
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(1, weight=1)

        toolbar = ctk.CTkFrame(
            page,
            corner_radius=18,
            fg_color=self.COLORS["panel2"],
            border_width=1,
            border_color=self.COLORS["border"],
        )
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        toolbar.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            toolbar, text="Logs", font=self.font_h2, text_color=self.COLORS["text"]
        ).grid(row=0, column=0, sticky="w", padx=16, pady=14)

        self.log_filter_var = tk.StringVar(value="")
        self.log_filter = ctk.CTkEntry(
            toolbar,
            textvariable=self.log_filter_var,
            placeholder_text="Filter (regex or text)…",
            height=36,
            corner_radius=14,
        )
        self.log_filter.grid(row=0, column=1, sticky="ew", padx=(0, 10), pady=14)

        ctk.CTkButton(
            toolbar,
            text="Clear",
            height=36,
            width=90,
            corner_radius=14,
            fg_color=self._blend(self.COLORS["panel"], "#ffffff", 0.04),
            hover_color=self._blend(self.COLORS["panel"], "#ffffff", 0.08),
            command=self.clear_logs,
        ).grid(row=0, column=2, sticky="e", padx=(0, 16), pady=14)

        # Rounded container, but use a plain tk.Text inside for stability
        box = ctk.CTkFrame(
            page,
            corner_radius=20,
            fg_color=self.COLORS["panel2"],
            border_width=1,
            border_color=self.COLORS["border"],
        )
        box.grid(row=1, column=0, sticky="nsew")
        box.grid_columnconfigure(0, weight=1)
        box.grid_rowconfigure(0, weight=1)

        inner = ctk.CTkFrame(box, fg_color="transparent")
        inner.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)
        inner.grid_columnconfigure(0, weight=1)
        inner.grid_rowconfigure(0, weight=1)

        self.log_text = tk.Text(
            inner,
            bg=self.COLORS["panel"],
            fg=self.COLORS["muted"],
            insertbackground=self.COLORS["text"],
            relief="flat",
            highlightthickness=0,
            wrap="word",
            font=self.font_mono,
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")

        sb = ctk.CTkScrollbar(inner, command=self.log_text.yview)
        sb.grid(row=0, column=1, sticky="ns", padx=(10, 0))
        self.log_text.configure(yscrollcommand=sb.set)

        # tags
        self.log_text.tag_configure("ts", foreground=self.COLORS["muted"])
        self.log_text.tag_configure("info", foreground=self.COLORS["text"])
        self.log_text.tag_configure("success", foreground=self.COLORS["success"])
        self.log_text.tag_configure("warning", foreground=self.COLORS["warning"])
        self.log_text.tag_configure("error", foreground=self.COLORS["error"])

        self.log_text.configure(state="disabled")

        return page

    # --------- Settings ----------
    def _build_settings(self, parent: ctk.CTkFrame) -> ctk.CTkFrame:
        page = ctk.CTkFrame(parent, fg_color="transparent")
        page.grid_columnconfigure(0, weight=1)

        card = ctk.CTkFrame(
            page,
            corner_radius=20,
            fg_color=self.COLORS["panel2"],
            border_width=1,
            border_color=self.COLORS["border"],
        )
        card.grid(row=0, column=0, sticky="ew")
        card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            card,
            text="Server Settings",
            font=self.font_h2,
            text_color=self.COLORS["text"],
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=16, pady=(16, 10))

        ctk.CTkLabel(
            card, text="Host", font=self.font_body, text_color=self.COLORS["muted"]
        ).grid(row=1, column=0, sticky="w", padx=16, pady=(6, 6))
        self.host_entry = ctk.CTkEntry(
            card, textvariable=self.host_var, height=36, corner_radius=14
        )
        self.host_entry.grid(row=1, column=1, sticky="ew", padx=16, pady=(6, 6))

        ctk.CTkLabel(
            card, text="Port", font=self.font_body, text_color=self.COLORS["muted"]
        ).grid(row=2, column=0, sticky="w", padx=16, pady=(6, 6))
        self.port_entry = ctk.CTkEntry(
            card, textvariable=self.port_var, height=36, corner_radius=14
        )
        self.port_entry.grid(row=2, column=1, sticky="ew", padx=16, pady=(6, 6))

        self.auto_launch = ctk.CTkSwitch(
            card,
            text="Auto-launch a session when server becomes ready",
            variable=self.auto_launch_var,
            onvalue=True,
            offvalue=False,
        )
        self.auto_launch.grid(
            row=3, column=0, columnspan=2, sticky="w", padx=16, pady=(10, 6)
        )

        self.incognito = ctk.CTkSwitch(
            card,
            text="Prefer incognito/private window (Chrome/Edge if found)",
            variable=self.incognito_var,
            onvalue=True,
            offvalue=False,
        )
        self.incognito.grid(
            row=4, column=0, columnspan=2, sticky="w", padx=16, pady=(6, 6)
        )

        btnrow = ctk.CTkFrame(card, fg_color="transparent")
        btnrow.grid(row=5, column=0, columnspan=2, sticky="ew", padx=16, pady=(12, 16))
        btnrow.grid_columnconfigure(0, weight=1)

        ctk.CTkButton(
            btnrow,
            text="Apply & Restart",
            height=40,
            corner_radius=16,
            fg_color=self.COLORS["accent"],
            hover_color=self._blend(self.COLORS["accent"], "#ffffff", 0.08),
            command=self.apply_settings_and_restart,
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkButton(
            btnrow,
            text="Stop Server",
            height=40,
            corner_radius=16,
            fg_color=self._blend(self.COLORS["panel"], "#ffffff", 0.04),
            hover_color=self._blend(self.COLORS["panel"], "#ffffff", 0.08),
            command=self.stop_server,
        ).grid(row=0, column=1, sticky="e")

        # NPM diagnostics card
        diag = ctk.CTkFrame(
            page,
            corner_radius=20,
            fg_color=self.COLORS["panel2"],
            border_width=1,
            border_color=self.COLORS["border"],
        )
        diag.grid(row=1, column=0, sticky="ew", pady=(14, 0))
        diag.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            diag, text="Diagnostics", font=self.font_h2, text_color=self.COLORS["text"]
        ).pack(anchor="w", padx=16, pady=(16, 8))

        self.diag_label = ctk.CTkLabel(
            diag,
            text="npm: (detecting...)",
            font=self.font_small,
            text_color=self.COLORS["muted"],
            justify="left",
        )
        self.diag_label.pack(anchor="w", padx=16, pady=(0, 16))

        return page

    # --------- Core server behavior ----------
    def current_url(self) -> str:
        host = (self.host_var.get() or DEFAULT_HOST).strip()
        port_s = (self.port_var.get() or str(DEFAULT_PORT)).strip()
        try:
            port = int(port_s)
        except ValueError:
            port = DEFAULT_PORT
        return f"http://{host}:{port}/"

    def _dev_args(self) -> list[str]:
        host = (self.host_var.get() or DEFAULT_HOST).strip()
        port = int((self.port_var.get() or str(DEFAULT_PORT)).strip())
        return DEV_ARGS_BASE + ["--host", host, "--port", str(port)]

    def start_server(self):
        with self.proc_lock:
            if self.proc and self.proc.poll() is None:
                self.toast_msg("Server already running.", level="warning")
                return

        self.server_ready = False
        self.server_start_time = None
        self._set_status("Starting", "Warming up Vite…", level="warning")

        self.npm_path = resolve_npm_path()
        if not self.npm_path:
            self._set_status(
                "Error",
                "npm not found. Install Node.js or set LOCAL_VITE_NPM_PATH.",
                level="error",
            )
            self.enqueue_log(
                "error", "npm not found. Install Node.js or set LOCAL_VITE_NPM_PATH."
            )
            self._refresh_diag()
            return

        self._refresh_diag()
        self.enqueue_log("info", f"npm found: {self.npm_path}")

        self.stop_event.clear()
        threading.Thread(target=self._server_thread, daemon=True).start()

    def _server_thread(self):
        # Ensure dependencies
        node_modules = PROJECT_ROOT / "node_modules"
        if not node_modules.exists():
            self.enqueue_log("warning", "node_modules missing — running npm install…")
            rc = self._run_and_stream(
                npm_cmd(self.npm_path, ["install"]), cwd=PROJECT_ROOT
            )
            if rc != 0:
                self._set_status(
                    "Error", f"npm install failed (code {rc})", level="error"
                )
                return
            self.enqueue_log("success", "Dependencies installed.")

        # Start Vite server
        cmd = npm_cmd(self.npm_path, self._dev_args())
        self.enqueue_log("info", "Starting Vite dev server…")
        self.enqueue_log("info", "CMD: " + " ".join(cmd))

        kwargs = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["preexec_fn"] = os.setsid

        try:
            p = subprocess.Popen(
                cmd,
                cwd=PROJECT_ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                **kwargs,
            )
        except Exception as e:
            self._set_status("Error", f"Failed to start server: {e}", level="error")
            return

        with self.proc_lock:
            self.proc = p
        self.server_start_time = datetime.now()

        threading.Thread(
            target=self._stream_proc_output, args=(p,), daemon=True
        ).start()
        threading.Thread(target=self._ready_monitor, daemon=True).start()

    def _run_and_stream(self, cmd: list[str], cwd: Path) -> int:
        try:
            p = subprocess.Popen(
                cmd,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except Exception as e:
            self.enqueue_log("error", f"Failed to run command: {e}")
            return 1

        assert p.stdout is not None
        for line in p.stdout:
            if self.stop_event.is_set():
                break
            s = line.rstrip()
            if s:
                self.enqueue_log("info", s)

        try:
            return p.wait(timeout=5)
        except Exception:
            return 1

    def _stream_proc_output(self, p: subprocess.Popen):
        if not p.stdout:
            return
        for line in p.stdout:
            if self.stop_event.is_set():
                return
            s = line.rstrip()
            if s:
                self.enqueue_log("info", s)

    def _ready_monitor(self):
        url = self.current_url()
        host = (self.host_var.get() or DEFAULT_HOST).strip()
        port = int((self.port_var.get() or str(DEFAULT_PORT)).strip())

        while not self.stop_event.is_set():
            with self.proc_lock:
                p = self.proc
            if not p:
                return
            if p.poll() is not None:
                self._set_status("Error", "Server exited unexpectedly.", level="error")
                return

            if is_port_open(host, port, timeout=0.2):
                break
            time.sleep(0.2)

        while not self.stop_event.is_set():
            with self.proc_lock:
                p = self.proc
            if not p:
                return
            if p.poll() is not None:
                self._set_status("Error", "Server exited unexpectedly.", level="error")
                return

            try:
                with urllib.request.urlopen(url, timeout=0.8) as r:
                    status = getattr(r, "status", 200)
                    if 200 <= status < 500:
                        self.server_ready = True
                        self._set_status("Active", "Server online", level="success")
                        self.enqueue_log("success", f"Server ready: {url}")
                        if self.auto_launch_var.get():
                            self.after(0, self.launch_session)
                        return
            except Exception:
                pass

            time.sleep(0.4)

    def stop_server(self):
        self.stop_event.set()
        with self.proc_lock:
            p = self.proc
            self.proc = None

        if not p:
            self._set_status("Stopped", "Server is not running.", level="warning")
            return

        self.enqueue_log("warning", "Stopping server…")

        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(p.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            else:
                try:
                    os.killpg(os.getpgid(p.pid), signal.SIGTERM)
                except Exception:
                    p.terminate()
        except Exception as e:
            self.enqueue_log("warning", f"Stop error: {e}")

        self.server_ready = False
        self._set_status("Stopped", "Server stopped.", level="warning")
        self.after(0, lambda: self.btn_new_session.configure(state="disabled"))

    def restart_server(self):
        self.stop_server()
        self.start_server()
        self.toast_msg("Restart requested.", level="info")

    def apply_settings_and_restart(self):
        host = (self.host_var.get() or "").strip()
        port_s = (self.port_var.get() or "").strip()

        if not host:
            self.toast_msg("Host cannot be empty.", level="error")
            return

        try:
            port = int(port_s)
            if port < 1 or port > 65535:
                raise ValueError
        except ValueError:
            self.toast_msg("Port must be an integer 1–65535.", level="error")
            return

        self.url_label.configure(text=self.current_url())
        self.enqueue_log("info", f"Settings applied: host={host}, port={port}")
        self.restart_server()

    # --------- Sessions ----------
    def launch_session(self):
        if not self.server_ready:
            self.toast_msg("Server not ready yet.", level="warning")
            return

        url = self.current_url()
        self.url_label.configure(text=url)

        # Show dialog to ask user preference
        choice = self._ask_browser_mode()
        
        if choice is None:
            # User canceled the dialog
            return
        
        opened = False
        if choice == "incognito":
            opened = self._open_private_window(url)
            if not opened:
                self.toast_msg("Could not open in incognito mode. Opening in default browser.", level="warning")
                webbrowser.open(url)
        else:
            # Regular mode
            webbrowser.open(url)

        self.session_count += 1
        self.stat_sessions.configure(text=str(self.session_count))

        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = ctk.CTkFrame(
            self.timeline_list,
            corner_radius=14,
            fg_color=self._blend(self.COLORS["panel2"], "#000000", 0.12),
            border_width=1,
            border_color=self.COLORS["border"],
        )
        entry.pack(fill="x", padx=10, pady=8)

        left = ctk.CTkFrame(entry, fg_color="transparent")
        left.pack(side="left", fill="x", expand=True, padx=12, pady=10)

        ctk.CTkLabel(
            left,
            text=f"Session #{self.session_count}",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=self.COLORS["text"],
        ).pack(anchor="w")
        ctk.CTkLabel(
            left, text=stamp, font=self.font_small, text_color=self.COLORS["muted"]
        ).pack(anchor="w", pady=(2, 0))

        ctk.CTkButton(
            entry,
            text="Open",
            width=72,
            height=32,
            corner_radius=12,
            fg_color=self._blend(self.COLORS["panel"], "#ffffff", 0.04),
            hover_color=self._blend(self.COLORS["panel"], "#ffffff", 0.08),
            command=lambda u=url: webbrowser.open(u),
        ).pack(side="right", padx=10, pady=10)

        self.enqueue_log("success", f"Session launched: {url}")
        self.toast_msg("Session opened.", level="success")
        self.btn_new_session.configure(state="normal")

    def _ask_browser_mode(self) -> str | None:
        """
        Show a dialog asking user to choose between Incognito and Regular mode.
        Returns: "incognito", "regular", or None if canceled
        """
        dialog = ctk.CTkToplevel(self)
        dialog.title("Browser Mode")
        dialog.geometry("420x220")
        dialog.resizable(False, False)
        dialog.configure(fg_color=self.COLORS["bg"])
        
        # Make it modal
        dialog.transient(self)
        dialog.grab_set()
        
        # Center the dialog
        dialog.update_idletasks()
        x = self.winfo_x() + (self.winfo_width() // 2) - (420 // 2)
        y = self.winfo_y() + (self.winfo_height() // 2) - (220 // 2)
        dialog.geometry(f"+{x}+{y}")
        
        result = {"choice": None}
        
        # Content frame
        content = ctk.CTkFrame(
            dialog, 
            fg_color=self.COLORS["panel2"],
            corner_radius=20,
            border_width=1,
            border_color=self.COLORS["border"]
        )
        content.pack(fill="both", expand=True, padx=20, pady=20)
        
        # Title
        ctk.CTkLabel(
            content,
            text="Choose Browser Mode",
            font=self.font_h2,
            text_color=self.COLORS["text"],
        ).pack(pady=(20, 10))
        
        # Description
        ctk.CTkLabel(
            content,
            text="How would you like to open the browser?",
            font=self.font_body,
            text_color=self.COLORS["muted"],
        ).pack(pady=(0, 20))
        
        # Button container
        btn_frame = ctk.CTkFrame(content, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=(0, 20))
        btn_frame.grid_columnconfigure((0, 1), weight=1)
        
        def choose_incognito():
            result["choice"] = "incognito"
            dialog.destroy()
        
        def choose_regular():
            result["choice"] = "regular"
            dialog.destroy()
        
        # Incognito button
        ctk.CTkButton(
            btn_frame,
            text="🕵️ Incognito",
            height=50,
            corner_radius=16,
            fg_color=self.COLORS["accent"],
            hover_color=self._blend(self.COLORS["accent"], "#ffffff", 0.08),
            text_color="white",
            font=ctk.CTkFont(size=14, weight="bold"),
            command=choose_incognito,
        ).grid(row=0, column=0, sticky="ew", padx=(0, 5))
        
        # Regular button
        ctk.CTkButton(
            btn_frame,
            text="🌐 Regular",
            height=50,
            corner_radius=16,
            fg_color=self._blend(self.COLORS["panel"], "#ffffff", 0.08),
            hover_color=self._blend(self.COLORS["panel"], "#ffffff", 0.12),
            text_color=self.COLORS["text"],
            font=ctk.CTkFont(size=14, weight="bold"),
            command=choose_regular,
        ).grid(row=0, column=1, sticky="ew", padx=(5, 0))
        
        # Wait for dialog to close
        dialog.wait_window()
        
        return result["choice"]

    def _open_private_window(self, url: str) -> bool:
        candidates: list[tuple[str, list[str]]] = []

        # Windows
        candidates += [
            (
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                ["--incognito", "--disable-features=BlockThirdPartyCookies", url],
            ),
            (
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                ["--incognito", "--disable-features=BlockThirdPartyCookies", url],
            ),
            (
                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                ["--inprivate", "--disable-features=BlockThirdPartyCookies", url],
            ),
            (
                r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
                ["--inprivate", "--disable-features=BlockThirdPartyCookies", url],
            ),
        ]
        # macOS
        candidates += [
            (
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                ["--incognito", "--disable-features=BlockThirdPartyCookies", url],
            ),
            (
                "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                ["--inprivate", "--disable-features=BlockThirdPartyCookies", url],
            ),
        ]
        # Linux
        candidates += [
            ("/usr/bin/google-chrome", ["--incognito", "--disable-features=BlockThirdPartyCookies", url]),
            ("/usr/bin/chromium", ["--incognito", "--disable-features=BlockThirdPartyCookies", url]),
            ("/usr/bin/chromium-browser", ["--incognito", "--disable-features=BlockThirdPartyCookies", url]),
            ("/usr/bin/microsoft-edge", ["--inprivate", "--disable-features=BlockThirdPartyCookies", url]),
        ]

        for exe, args in candidates:
            if os.path.exists(exe):
                try:
                    subprocess.Popen([exe, *args])
                    return True
                except Exception:
                    continue
        return False

    def copy_url(self):
        url = self.current_url()
        try:
            self.clipboard_clear()
            self.clipboard_append(url)
            self.toast_msg("URL copied to clipboard.", level="success")
        except Exception:
            self.toast_msg("Failed to copy URL.", level="error")

    # --------- Status / UI updates ----------
    def _set_status(self, state_text: str, hero_text: str, level: str = "info"):
        def apply():
            self.stat_state.configure(text=state_text)
            self.hero_status.configure(text=hero_text)

            if level == "success":
                dot = self.COLORS["success"]
                txt = self.COLORS["success"]
                rail = "Online"
            elif level == "warning":
                dot = self.COLORS["warning"]
                txt = self.COLORS["warning"]
                rail = "Starting"
            elif level == "error":
                dot = self.COLORS["error"]
                txt = self.COLORS["error"]
                rail = "Error"
            else:
                dot = self.COLORS["muted"]
                txt = self.COLORS["text"]
                rail = "Info"

            self.rail_dot.configure(fg_color=dot)
            self.rail_status_label.configure(text=rail, text_color=self.COLORS["muted"])
            self.hero_status.configure(text_color=txt)

            self.url_label.configure(text=self.current_url())

            if self.server_ready:
                self.btn_new_session.configure(state="normal")
                self.rail_status_label.configure(
                    text="Online", text_color=self.COLORS["text"]
                )
            else:
                self.btn_new_session.configure(state="disabled")

        self.after(0, apply)

    def _tick_uptime(self):
        if self.server_start_time:
            delta = datetime.now() - self.server_start_time
            s = int(delta.total_seconds())
            if s < 60:
                txt = f"{s}s"
            elif s < 3600:
                txt = f"{s // 60}m {s % 60}s"
            else:
                txt = f"{s // 3600}h {(s % 3600) // 60}m"
            self.stat_uptime.configure(text=txt)
        self.after(1000, self._tick_uptime)

    def _animate(self):
        # Ambient top bar “breath” (smooth sine)
        self._ambient_phase += 0.02
        v = 0.55 + 0.25 * math.sin(time.time() * 0.9)  # 0.30..0.80
        v = max(0.0, min(1.0, v))
        self.ambient.set(v)

        # Pulse the rail dot gently when ready
        if self.server_ready:
            self._pulse_phase += 0.12
            t = (1.0 + math.sin(self._pulse_phase)) / 2.0
            col = self._blend(self.COLORS["success"], "#b8ffcf", 0.18 * t)
            self.rail_dot.configure(fg_color=col)

        self.after(16, self._animate)

    # --------- Toast animation ----------
    def _animate_toast_y(self, start_y: int, end_y: int, ms: int = 200, on_done=None):
        self._toast_anim_token += 1
        token = self._toast_anim_token

        start = time.perf_counter()
        duration = max(0.08, ms / 1000.0)

        def frame():
            if token != self._toast_anim_token:
                return

            t = (time.perf_counter() - start) / duration
            if t >= 1.0:
                self._toast_y = end_y
                if self.toast_visible:
                    self.toast.place_configure(y=end_y)
                if on_done:
                    on_done()
                return

            e = self._ease_out_cubic(t)
            y = int(start_y + (end_y - start_y) * e)
            self._toast_y = y

            if self.toast_visible:
                self.toast.place_configure(y=y)

            self.after(16, frame)

        frame()

    def toast_msg(self, msg: str, level: str = "info"):
        bg = self.COLORS["panel2"]
        if level == "success":
            fg = self.COLORS["success"]
        elif level == "warning":
            fg = self.COLORS["warning"]
        elif level == "error":
            fg = self.COLORS["error"]
        else:
            fg = self.COLORS["text"]

        self.toast.configure(text=msg, text_color=fg, fg_color=bg)

        # Show (slide up)
        if not self.toast_visible:
            self.toast_visible = True
            self._toast_y = 30
            self.toast.place(relx=0.5, rely=1.0, y=self._toast_y, anchor="s")

        self._animate_toast_y(self._toast_y, -16, ms=210)

        # Hide (slide down) after a delay
        def hide():
            def done():
                self.toast.place_forget()
                self.toast_visible = False

            self._animate_toast_y(self._toast_y, 30, ms=180, on_done=done)

        self.after(2200, hide)

    def _refresh_diag(self):
        npm = self.npm_path or resolve_npm_path() or "(not found)"
        self.after(
            0,
            lambda: self.diag_label.configure(
                text=f"npm: {npm}\nproject: {PROJECT_ROOT}"
            ),
        )

    # --------- Logging ----------
    def enqueue_log(self, level: str, message: str):
        self.log_q.put(LogEvent(level=level, message=message, timestamp=now_ts()))

    def clear_logs(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")
        self.enqueue_log("info", "Logs cleared.")

    def _drain_logs(self):
        filt = self.log_filter_var.get().strip()
        regex = None
        if filt:
            m = re.fullmatch(r"/(.+)/", filt)
            if m:
                try:
                    regex = re.compile(m.group(1), re.IGNORECASE)
                except re.error:
                    regex = None

        changed = False
        while True:
            try:
                ev = self.log_q.get_nowait()
            except queue.Empty:
                break

            if filt:
                hay = f"{ev.timestamp} {ev.level.upper()} {ev.message}"
                if regex:
                    if not regex.search(hay):
                        continue
                else:
                    if filt.lower() not in hay.lower():
                        continue

            self._append_log(ev)
            changed = True

        if changed:
            self.log_text.see("end")

        self.after(60, self._drain_logs)

    def _append_log(self, ev: LogEvent):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"{ev.timestamp} ", ("ts",))
        self.log_text.insert("end", f"[{ev.level.upper():7}] ", (ev.level,))
        self.log_text.insert("end", ev.message + "\n", (ev.level,))
        self.log_text.configure(state="disabled")

    # --------- Shutdown ----------
    def on_close(self):
        try:
            self.stop_server()
        finally:
            self.destroy()

    # --------- Color helper ----------
    def _blend(self, a: str, b: str, t: float) -> str:
        t = max(0.0, min(1.0, t))
        a = a.lstrip("#")
        b = b.lstrip("#")
        ar, ag, ab = int(a[0:2], 16), int(a[2:4], 16), int(a[4:6], 16)
        br, bg, bb = int(b[0:2], 16), int(b[2:4], 16), int(b[4:6], 16)
        cr = int(ar + (br - ar) * t)
        cg = int(ag + (bg - ag) * t)
        cb = int(ab + (bb - ab) * t)
        return f"#{cr:02x}{cg:02x}{cb:02x}"


if __name__ == "__main__":
    app = ViteControlCenter()
    app.mainloop()
