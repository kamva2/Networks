import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import threading
import socket
import os
import base64
import uuid
import time


# ─── Colour palette ────────────────────────────────────────────────────────────
BG_MAIN      = "#F2F6FA"
BG_SIDEBAR   = "#F2F6FA"
BG_CHAT      = "#FAFBFC"
BG_BUBBLE_ME = "#1A6FBF"
BG_BUBBLE_TH = "#E8EDF2"
BG_INPUT     = "#FFFFFF"
BG_HEADER    = "#1E5FA8"
BG_ITEM_HVR  = "#E2EBF5"
BG_ITEM_SEL  = "#C8D8ED"
BG_SEARCH    = "#E8EEF4"
BG_CARD      = "#FFFFFF"

FG_PRIMARY   = "#1A2C42"
FG_SECONDARY = "#6B7F96"
FG_TIME      = "#8A9AB0"
FG_BLUE      = "#1A6FBF"
FG_NAME      = "#1558A0"

ACCENT_PRIVATE   = "#C0392B"
ACCENT_GROUP     = "#1A6FBF"
ACCENT_BROADCAST = "#3D4450"

FONT_BODY    = ("Segoe UI", 10)
FONT_SMALL   = ("Segoe UI", 8)
FONT_NAME    = ("Segoe UI", 10, "bold")
FONT_HEADER  = ("Segoe UI", 11, "bold")
FONT_TITLE   = ("Segoe UI", 13, "bold")
FONT_BIG     = ("Segoe UI", 15, "bold")


def _lighten(hex_color, factor=1.18):
    import colorsys
    try:
        r, g, b = (int(hex_color[i:i+2], 16) / 255 for i in (1, 3, 5))
        h, s, v = colorsys.rgb_to_hsv(r, g, b)
        r2, g2, b2 = colorsys.hsv_to_rgb(h, max(s - 0.08, 0), min(v * factor, 1))
        return f"#{int(r2*255):02x}{int(g2*255):02x}{int(b2*255):02x}"
    except Exception:
        return hex_color


class RoundedButton(tk.Frame):
    def __init__(self, parent, text, command, bg=FG_BLUE, fg="white",
                 width=120, height=34, font=FONT_BODY, **kw):
        super().__init__(parent, bg=bg, cursor="hand2", width=width, height=height, **kw)
        self.pack_propagate(False)
        self._bg = bg
        self._hover_bg = _lighten(bg)
        self._command = command
        self._lbl = tk.Label(self, text=text, font=font, bg=bg, fg=fg, cursor="hand2")
        self._lbl.place(relx=0.5, rely=0.5, anchor="center")
        for w in (self, self._lbl):
            w.bind("<Button-1>", lambda e: self._command())
            w.bind("<Enter>",    lambda e: self._hover(True))
            w.bind("<Leave>",    lambda e: self._hover(False))

    def _hover(self, on):
        c = self._hover_bg if on else self._bg
        self.config(bg=c); self._lbl.config(bg=c)


class ScrollableFrame(tk.Frame):
    def __init__(self, parent, bg=BG_SIDEBAR, **kw):
        super().__init__(parent, bg=bg, **kw)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0, yscrollincrement=1)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg=bg)
        self.inner.bind("<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.window_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        self.canvas.bind("<Configure>",
            lambda e: self.canvas.itemconfig(self.window_id, width=e.width))
        self.canvas.bind_all("<MouseWheel>",
            lambda e: self.canvas.yview_scroll(-1 * (e.delta // 120), "units"))

    def scroll_to_bottom(self):
        self.canvas.update_idletasks()
        self.canvas.yview_moveto(1.0)


class StyledPanel(tk.Toplevel):
    """Consistent modal card panel."""
    def __init__(self, parent, title, bg_accent=FG_BLUE):
        super().__init__(parent)
        self.configure(bg=BG_MAIN)
        self.title(title)
        self.resizable(False, False)
        self.grab_set()
        self.transient(parent)
        tk.Frame(self, bg=bg_accent, height=4).pack(fill="x")
        self.card = tk.Frame(self, bg=BG_CARD, padx=24, pady=20)
        self.card.pack(fill="both", expand=True, padx=12, pady=12)
        tk.Label(self.card, text=title, font=FONT_TITLE,
                 bg=BG_CARD, fg=FG_PRIMARY).pack(anchor="w", pady=(0, 14))
        self.update_idletasks()
        px = parent.winfo_x() + (parent.winfo_width()  - self.winfo_width())  // 2
        py = parent.winfo_y() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{px}+{py}")


class Chat77App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Chat77")
        self.geometry("900x580")
        self.minsize(700, 460)
        self.configure(bg=BG_MAIN)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.sock = None
        self.beep_sock = None
        self.sock_lock = threading.Lock()
        self.recv_buffer = b""
        self.aliase = ""
        self.private_partners = set()
        self.pending_requesters = set()
        self.groups = set()
        self.pending_group_invites = set()
        self.incoming_transfers = {}
        self.online_users = set()

        self.current_chat = None
        self.chat_histories = {}
        self.sidebar_items = {}
        self.sidebar_meta  = {}
        self.unread_counts = {}
        self._current_mode = None
        self._connecting = False
        self._online_users_callback = None

        self._build_login_screen()

    # ──────────────────────────────────────────────────────────────────────
    # SOCKET HELPERS
    # ──────────────────────────────────────────────────────────────────────
    def _safe_send(self, text):
        try:
            if not self.sock: return False
            with self.sock_lock:
                self.sock.sendall((text + "\n").encode())
            return True
        except Exception as ex:
            self.after(0, self._system_msg, f"Network send failed: {ex}")
            return False

    def _recv_line_sync(self):
        while True:
            if b"\n" in self.recv_buffer:
                line, self.recv_buffer = self.recv_buffer.split(b"\n", 1)
                return line.decode(errors="ignore").rstrip("\r")
            chunk = self.sock.recv(4096)
            if not chunk: return None
            self.recv_buffer += chunk

    def _on_close(self):
        try: self._safe_send("exit")
        except Exception: pass
        try:
            if self.sock: self.sock.close()
        except Exception: pass
        try:
            if self.beep_sock: self.beep_sock.close()
        except Exception: pass
        self.destroy()

    # ──────────────────────────────────────────────────────────────────────
    # LOGIN SCREEN
    # ──────────────────────────────────────────────────────────────────────
    def _build_login_screen(self):
        self.login_frame = tk.Frame(self, bg="#E8F0FA")
        self.login_frame.pack(fill="both", expand=True)

        left = tk.Frame(self.login_frame, bg=BG_HEADER, width=340)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        tk.Label(left, text="Chat77", font=("Segoe UI", 36, "bold"),
                 bg=BG_HEADER, fg="#FFFFFF").place(relx=0.5, rely=0.42, anchor="center")
        tk.Label(left, text="Connect. Chat. Together.",
                 font=("Segoe UI", 11), bg=BG_HEADER, fg="#A8C8E8")\
            .place(relx=0.5, rely=0.52, anchor="center")

        right = tk.Frame(self.login_frame, bg="#E8F0FA")
        right.pack(side="left", fill="both", expand=True)

        card = tk.Frame(right, bg=BG_CARD, padx=44, pady=40)
        card.place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(card, text="Sign In", font=("Segoe UI", 20, "bold"),
                 bg=BG_CARD, fg=FG_PRIMARY).grid(row=0, columnspan=2, pady=(0, 4), sticky="w")
        tk.Label(card, text="Enter your credentials to continue",
                 font=FONT_SMALL, bg=BG_CARD, fg=FG_SECONDARY)\
            .grid(row=1, columnspan=2, pady=(0, 22), sticky="w")

        def field_lbl(txt, r):
            tk.Label(card, text=txt, font=("Segoe UI", 9, "bold"), bg=BG_CARD,
                     fg=FG_SECONDARY, anchor="w").grid(row=r, column=0, columnspan=2,
                                                        sticky="w", pady=(8, 2))

        def field_entry(r, show=None):
            f = tk.Frame(card, bg=BG_SEARCH)
            f.grid(row=r, column=0, columnspan=2, sticky="ew", pady=(0, 2))
            e = tk.Entry(f, font=FONT_BODY, bg=BG_SEARCH, fg=FG_PRIMARY,
                         insertbackground=FG_PRIMARY, relief="flat",
                         width=30, show=show, bd=0)
            e.pack(fill="x", padx=10, pady=8)
            return e

        field_lbl("Server IP", 2);  self.e_ip   = field_entry(3)
        field_lbl("Username",  4);  self.e_user = field_entry(5)
        field_lbl("Password",  6);  self.e_pass = field_entry(7, show="•")

        self.auth_mode = tk.StringVar(value="LOGIN")
        frm = tk.Frame(card, bg=BG_CARD)
        frm.grid(row=8, columnspan=2, pady=(14, 0), sticky="w")
        for val, txt in (("LOGIN", "Login"), ("REGISTER", "Register")):
            tk.Radiobutton(frm, text=txt, variable=self.auth_mode, value=val,
                           bg=BG_CARD, fg=FG_PRIMARY, selectcolor=BG_SEARCH,
                           activebackground=BG_CARD, font=FONT_BODY)\
                .pack(side="left", padx=(0, 18))

        self.login_status = tk.Label(card, text="", font=FONT_SMALL,
                                     bg=BG_CARD, fg="#CC3333", wraplength=340)
        self.login_status.grid(row=9, columnspan=2, pady=(10, 0))

        btn_f = tk.Frame(card, bg=BG_CARD)
        btn_f.grid(row=10, columnspan=2, pady=(18, 0))
        self.connect_btn = RoundedButton(btn_f, "Connect  →", self._do_connect,
                                         width=160, height=40, font=FONT_NAME)
        self.connect_btn.pack()

        self.e_ip.insert(0, "127.0.0.1")
        self.e_ip.focus_set()
        self.bind("<Return>", lambda _: self._do_connect())

    def _do_connect(self):
        if self._connecting: return
        ip = self.e_ip.get().strip(); user = self.e_user.get().strip()
        pwd = self.e_pass.get().strip(); mode = self.auth_mode.get()
        if not ip or not user or not pwd:
            self.login_status.config(text="Please fill in all fields.", fg="#CC3333"); return
        self._connecting = True
        self.login_status.config(text="Connecting…", fg=FG_SECONDARY)
        self.update()
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((ip, 22081)); self.recv_buffer = b""
        except Exception as ex:
            self.login_status.config(text=f"Cannot connect: {ex}", fg="#CC3333")
            self._connecting = False; return
        try:
            self.beep_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.beep_sock.bind(("", 0))
            self._beep_port = self.beep_sock.getsockname()[1]
        except Exception as ex:
            self.login_status.config(text=f"UDP setup failed: {ex}", fg="#CC3333")
            self._connecting = False; return
        ok = self._authenticate(user, pwd, mode)
        if ok:
            self.aliase = user
            self.login_frame.destroy()
            self._build_main_ui()
            self._register_beep_port()
            self._initial_sync()
            threading.Thread(target=self._recv_loop,  daemon=True).start()
            threading.Thread(target=self._beep_loop, daemon=True).start()
        self._connecting = False

    def _authenticate(self, user, pwd, mode):
        while True:
            try:
                msg = self._recv_line_sync()
                if msg is None:
                    self.login_status.config(text="Connection lost during auth.", fg="#CC3333")
                    return False
            except Exception:
                self.login_status.config(text="Connection lost during auth.", fg="#CC3333")
                return False
            if msg.startswith("Authorise MODE"):    self._safe_send(mode)
            elif msg == "ALIAS?":                   self._safe_send(user)
            elif msg == "PASSWORD?":                self._safe_send(pwd)
            elif msg.startswith("ERROR:"):
                self.login_status.config(text=msg, fg="#CC3333"); return False
            elif msg == "This alias is already logged in":
                self.login_status.config(text=msg, fg="#CC3333"); return False
            elif msg in ("AUTH_SUCCESS", "SUCCESSFULLY AUTHENTICATE"): return True
            else: self.login_status.config(text=msg, fg=FG_SECONDARY)

    def _initial_sync(self):
        self._safe_send("my groups")
        self._safe_send("my private chats")

    # ──────────────────────────────────────────────────────────────────────
    # MODE SELECTOR
    # ──────────────────────────────────────────────────────────────────────
    def _build_main_ui(self):
        self._show_mode_selector()

    def _show_mode_selector(self):
        for attr in ("main_pane", "mode_frame"):
            w = getattr(self, attr, None)
            if w and w.winfo_exists(): w.destroy()

        self.mode_frame = tk.Frame(self, bg=BG_MAIN)
        self.mode_frame.pack(fill="both", expand=True)

        # top bar
        bar = tk.Frame(self.mode_frame, bg=BG_HEADER)
        bar.pack(fill="x")
        inner_bar = tk.Frame(bar, bg=BG_HEADER, height=56)
        inner_bar.pack(fill="x")
        tk.Label(inner_bar, text="Chat77", font=FONT_BIG,
                 bg=BG_HEADER, fg="#FFFFFF").place(x=24, y=14)
        tk.Label(inner_bar, text=f"@{self.aliase}", font=FONT_BODY,
                 bg=BG_HEADER, fg="#A8C8E8").place(x=122, y=18)
        logout_wrap = tk.Frame(inner_bar, bg=BG_HEADER)
        logout_wrap.place(relx=1.0, x=-18, y=13, anchor="ne")
        RoundedButton(logout_wrap, "Logout", self._logout,
                      bg="#CC3333", fg="white", width=76, height=30,
                      font=FONT_SMALL).pack()

        tk.Label(self.mode_frame, text="Select a chat mode to get started",
                 font=("Segoe UI", 12), bg=BG_MAIN, fg=FG_SECONDARY)\
            .pack(pady=(50, 36))

        cards_row = tk.Frame(self.mode_frame, bg=BG_MAIN)
        cards_row.pack()

        modes = [
            ("Private\nText",  ACCENT_PRIVATE,   "💬", "Direct messages\nbetween two users",  self._open_private_ui),
            ("Group\nChat",    ACCENT_GROUP,      "👥", "Conversations with\nmultiple members", self._open_group_ui),
            ("Broadcast",      ACCENT_BROADCAST,  "🌐", "Send to everyone\ncurrently online",   self._open_broadcast_ui),
        ]

        for col, (title, accent, icon, desc, cmd) in enumerate(modes):
            card = tk.Frame(cards_row, bg=BG_CARD, width=210, height=235,
                            cursor="hand2", relief="flat",
                            highlightthickness=1, highlightbackground="#D8E4F0")
            card.grid(row=0, column=col, padx=22)
            card.grid_propagate(False)

            stripe = tk.Frame(card, bg=accent, height=6)
            stripe.place(x=0, y=0, relwidth=1)

            tk.Label(card, text=icon, font=("Segoe UI", 30),
                     bg=BG_CARD, fg=accent).place(relx=0.5, y=52, anchor="center")
            tk.Label(card, text=title, font=("Segoe UI", 14, "bold"),
                     bg=BG_CARD, fg=FG_PRIMARY, justify="center")\
                .place(relx=0.5, y=122, anchor="center")
            tk.Label(card, text=desc, font=("Segoe UI", 8),
                     bg=BG_CARD, fg=FG_SECONDARY, justify="center")\
                .place(relx=0.5, y=176, anchor="center")

            hov = _lighten(accent, 1.45)

            def bind_card(cw, sw, command, ac=accent, hbg=hov):
                def _e(e): cw.config(highlightbackground=ac); sw.config(bg=hbg)
                def _l(e): cw.config(highlightbackground="#D8E4F0"); sw.config(bg=ac)
                def _cl(e): command()
                for child in list(cw.winfo_children()) + [cw]:
                    child.bind("<Enter>", _e)
                    child.bind("<Leave>", _l)
                    child.bind("<Button-1>", _cl)

            bind_card(card, stripe, cmd)

    # ── per-mode openers ───────────────────────────────────────────────────
    def _open_private_ui(self):
        self._destroy_mode_frame()
        self._build_split_ui(mode="private")
        for p in self.private_partners:
            self._add_sidebar_item(f"private:{p}", p, "Private chat")
        if self.private_partners:
            self._select_chat(f"private:{next(iter(self.private_partners))}")

    def _open_group_ui(self):
        self._destroy_mode_frame()
        self._build_split_ui(mode="group")
        for g in self.groups:
            self._add_sidebar_item(f"group:{g}", g, "Group chat")
        if self.groups:
            self._select_chat(f"group:{next(iter(self.groups))}")

    def _open_broadcast_ui(self):
        self._destroy_mode_frame()
        self._build_split_ui(mode="broadcast")
        self._add_sidebar_item("broadcast", "Broadcast", "Everyone online")
        self._select_chat("broadcast")

    def _destroy_mode_frame(self):
        w = getattr(self, "mode_frame", None)
        if w and w.winfo_exists(): w.destroy()

    def _go_back_to_selector(self):
        w = getattr(self, "main_pane", None)
        if w and w.winfo_exists(): w.destroy()
        self.sidebar_items = {}; self.sidebar_meta = {}
        self.current_chat = None; self.unread_counts = {}
        self._show_mode_selector()

    # ──────────────────────────────────────────────────────────────────────
    # SPLIT UI
    # ──────────────────────────────────────────────────────────────────────
    def _build_split_ui(self, mode="broadcast"):
        self._current_mode = mode
        self.sidebar_items = {}; self.sidebar_meta = {}
        self.current_chat = None; self.unread_counts = {}

        self.main_pane = tk.PanedWindow(self, orient="horizontal",
                                         sashrelief="flat", sashwidth=1, bg="#D0DCE8")
        self.main_pane.pack(fill="both", expand=True)
        self._build_sidebar(mode=mode)
        self._build_chat_area(mode=mode)
        self.main_pane.add(self.sidebar,        minsize=280)
        self.main_pane.add(self.chat_container, minsize=420)

    # ──────────────────────────────────────────────────────────────────────
    # SIDEBAR
    # ──────────────────────────────────────────────────────────────────────
    def _build_sidebar(self, mode="broadcast"):
        accent = {"private": ACCENT_PRIVATE,
                  "group": ACCENT_GROUP,
                  "broadcast": ACCENT_BROADCAST}.get(mode, BG_HEADER)

        self.sidebar = tk.Frame(self.main_pane, bg=BG_SIDEBAR, width=300)

        # header
        top = tk.Frame(self.sidebar, bg=BG_HEADER)
        top.pack(fill="x")
        inner_top = tk.Frame(top, bg=BG_HEADER, height=56)
        inner_top.pack(fill="x")
        tk.Label(inner_top, text="Chat77", font=FONT_BIG,
                 bg=BG_HEADER, fg="#FFFFFF").place(x=14, y=14)
        back = tk.Label(inner_top, text="← Back", font=("Segoe UI", 9),
                        bg=BG_HEADER, fg="#A8C8E8", cursor="hand2")
        back.place(relx=1.0, x=-14, y=20, anchor="ne")
        back.bind("<Button-1>", lambda e: self._go_back_to_selector())
        back.bind("<Enter>",    lambda e: back.config(fg="#FFFFFF"))
        back.bind("<Leave>",    lambda e: back.config(fg="#A8C8E8"))

        # accent stripe
        tk.Frame(self.sidebar, bg=accent, height=3).pack(fill="x")

        # action buttons
        if mode == "private":
            act = tk.Frame(self.sidebar, bg=BG_SIDEBAR, padx=10, pady=10)
            act.pack(fill="x")
            self._sidebar_btn(act, "➕  Connect to User", ACCENT_PRIVATE, self._show_connect_panel)
            self._sidebar_btn(act, "👤  Online Users",    "#8E1C13",       self._show_online_users_panel)
            tk.Frame(self.sidebar, bg="#D8E4F0", height=1).pack(fill="x")

        elif mode == "group":
            act = tk.Frame(self.sidebar, bg=BG_SIDEBAR, padx=10, pady=10)
            act.pack(fill="x")
            self._sidebar_btn(act, "➕  Create New Group", ACCENT_GROUP, self._show_create_group_panel)
            self._sidebar_btn(act, "👥  My Groups",        "#154E8A",    self._show_my_groups_panel)
            tk.Frame(self.sidebar, bg="#D8E4F0", height=1).pack(fill="x")

        # search
        sf = tk.Frame(self.sidebar, bg=BG_SIDEBAR, padx=10, pady=8)
        sf.pack(fill="x")
        si = tk.Frame(sf, bg=BG_SEARCH)
        si.pack(fill="x")
        tk.Label(si, text="🔍", bg=BG_SEARCH, fg=FG_SECONDARY,
                 font=("Segoe UI", 9)).pack(side="left", padx=(8, 2), pady=7)
        self.search_var = tk.StringVar()
        se = tk.Entry(si, textvariable=self.search_var, bg=BG_SEARCH,
                      fg=FG_PRIMARY, font=FONT_BODY, insertbackground=FG_PRIMARY,
                      relief="flat", borderwidth=0)
        se.pack(side="left", fill="x", expand=True, padx=(0, 8), pady=7)
        self.search_var.trace_add("write", self._filter_sidebar)
        tk.Frame(self.sidebar, bg="#D8E4F0", height=1).pack(fill="x")

        # section label
        sec_lbl = {"private": "Conversations", "group": "Groups",
                   "broadcast": "Channel"}.get(mode, "Chats")
        tk.Label(self.sidebar, text=sec_lbl.upper(),
                 font=("Segoe UI", 7, "bold"), bg=BG_SIDEBAR,
                 fg=FG_SECONDARY).pack(anchor="w", padx=14, pady=(8, 2))

        # chat list
        self.chat_list = ScrollableFrame(self.sidebar, bg=BG_SIDEBAR)
        self.chat_list.pack(fill="both", expand=True)

        # footer
        tk.Frame(self.sidebar, bg="#D8E4F0", height=1).pack(fill="x")
        foot = tk.Frame(self.sidebar, bg=BG_HEADER, padx=12, pady=9)
        foot.pack(fill="x", side="bottom")
        av_txt = self.aliase[0].upper() if self.aliase else "?"
        tk.Label(foot, text=av_txt, font=("Segoe UI", 11, "bold"),
                 bg="#2980B9", fg="white", width=3, pady=4).pack(side="left")
        tk.Label(foot, text=self.aliase, font=FONT_NAME,
                 bg=BG_HEADER, fg="#FFFFFF").pack(side="left", padx=10)
        RoundedButton(foot, "Logout", self._logout, bg="#CC3333",
                      width=68, height=26, font=FONT_SMALL).pack(side="right")

    def _sidebar_btn(self, parent, text, bg_col, cmd):
        btn = tk.Frame(parent, bg=bg_col, cursor="hand2", height=40)
        btn.pack(fill="x", pady=3)
        btn.pack_propagate(False)
        lbl = tk.Label(btn, text=text, font=("Segoe UI", 9, "bold"),
                       bg=bg_col, fg="#FFFFFF", cursor="hand2")
        lbl.place(relx=0.5, rely=0.5, anchor="center")
        hov = _lighten(bg_col, 1.22)
        def _e(e, w=btn, l=lbl, h=hov): w.config(bg=h); l.config(bg=h)
        def _l(e, w=btn, l=lbl, b=bg_col): w.config(bg=b); l.config(bg=b)
        def _c(e): cmd()
        for w in (btn, lbl):
            w.bind("<Enter>", _e); w.bind("<Leave>", _l); w.bind("<Button-1>", _c)

    # ──────────────────────────────────────────────────────────────────────
    # CHAT AREA
    # ──────────────────────────────────────────────────────────────────────
    def _build_chat_area(self, mode="broadcast"):
        accent = {"private": ACCENT_PRIVATE,
                  "group": ACCENT_GROUP,
                  "broadcast": ACCENT_BROADCAST}.get(mode, BG_HEADER)

        self.chat_container = tk.Frame(self.main_pane, bg=BG_CHAT)

        self.chat_header = tk.Frame(self.chat_container, bg=BG_HEADER)
        self.chat_header.pack(fill="x")
        inner_hdr = tk.Frame(self.chat_header, bg=BG_HEADER, height=56)
        inner_hdr.pack(fill="x")

        self.header_av = tk.Label(inner_hdr, font=("Segoe UI", 13, "bold"),
                                  fg="white", width=3, pady=4)
        self.header_av.place(x=16, y=10)

        info_f = tk.Frame(inner_hdr, bg=BG_HEADER)
        info_f.place(x=70, y=8)
        self.header_name = tk.Label(info_f, text="Select a conversation",
                                    font=FONT_HEADER, bg=BG_HEADER, fg="#FFFFFF")
        self.header_name.pack(anchor="w")
        self.header_sub = tk.Label(info_f, text="", font=FONT_SMALL,
                                   bg=BG_HEADER, fg="#A8C8E8")
        self.header_sub.pack(anchor="w")

        self._hdr_btns = {}
        hbtn_wrap = tk.Frame(inner_hdr, bg=BG_HEADER)
        hbtn_wrap.place(relx=1.0, x=-14, y=12, anchor="ne")

        btns = []
        if mode == "group":
            btns.append(("👥  Invite", "Invite Member", self._prompt_invite_group))
        btns.append(("🚫  End", "End Chat", self._end_current_chat))

        for txt, tip, cmd in btns:
            b = tk.Label(hbtn_wrap, text=txt, font=("Segoe UI", 9),
                         bg=BG_HEADER, fg="#A8C8E8", cursor="hand2", padx=6, pady=4)
            b.pack(side="left", padx=4)
            b.bind("<Button-1>", lambda e, c=cmd: c())
            b.bind("<Enter>",    lambda e, w=b: w.config(fg="#FFFFFF"))
            b.bind("<Leave>",    lambda e, w=b: w.config(fg="#A8C8E8"))
            self._hdr_btns[tip] = b

        # accent stripe
        tk.Frame(self.chat_container, bg=accent, height=3).pack(fill="x")

        self.messages_frame = ScrollableFrame(self.chat_container, bg=BG_CHAT)
        self.messages_frame.pack(fill="both", expand=True)

        # input bar
        input_outer = tk.Frame(self.chat_container, bg="#EBF1F8", pady=10, padx=12)
        input_outer.pack(fill="x", side="bottom")
        input_inner = tk.Frame(input_outer, bg=BG_INPUT,
                               highlightthickness=1, highlightbackground="#C8D8ED")
        input_inner.pack(fill="x")
        self.msg_entry = tk.Text(input_inner, font=FONT_BODY, bg=BG_INPUT,
                                 fg=FG_PRIMARY, insertbackground=FG_PRIMARY,
                                 relief="flat", height=2, wrap="word",
                                 borderwidth=0, padx=10, pady=8)
        self.msg_entry.pack(side="left", fill="x", expand=True)
        self.msg_entry.bind("<Return>",       self._send_message_event)
        self.msg_entry.bind("<Shift-Return>", self._insert_newline)

        send_btn = tk.Label(input_inner, text="➤", font=("Segoe UI", 16),
                            bg=BG_INPUT, fg=FG_BLUE, cursor="hand2", padx=12)
        send_btn.pack(side="right")
        send_btn.bind("<Button-1>", self._send_message_event)
        send_btn.bind("<Enter>", lambda e: send_btn.config(fg=FG_PRIMARY))
        send_btn.bind("<Leave>", lambda e: send_btn.config(fg=FG_BLUE))

        if mode in ("private", "group"):
            file_btn = tk.Label(input_inner, text="📎", font=("Segoe UI", 15),
                                bg=BG_INPUT, fg=FG_SECONDARY, cursor="hand2", padx=6)
            file_btn.pack(side="right")
            file_btn.bind("<Button-1>", lambda e: self._prompt_send_file())
            file_btn.bind("<Enter>", lambda e: file_btn.config(fg=FG_PRIMARY))
            file_btn.bind("<Leave>", lambda e: file_btn.config(fg=FG_SECONDARY))

    # ──────────────────────────────────────────────────────────────────────
    # SIDEBAR ITEMS + UNREAD
    # ──────────────────────────────────────────────────────────────────────
    def _add_sidebar_item(self, key, label, subtitle="", notify=False):
        if key in self.sidebar_items:
            self.sidebar_meta[key]["label"]    = label.lower()
            self.sidebar_meta[key]["subtitle"] = subtitle.lower()
            if notify: self._mark_unread(key)
            return

        mode = self._current_mode
        if mode == "private"   and (key.startswith("group:") or key == "broadcast"): return
        if mode == "group"     and (key.startswith("private:") or key == "broadcast"): return
        if mode == "broadcast" and (key.startswith("private:") or key.startswith("group:")): return

        if key == "broadcast":
            av_char = "🌐"; av_bg = ACCENT_BROADCAST; display = "Broadcast"
        elif key.startswith("group:"):
            n = key[6:]; av_char = n[0].upper() if n else "G"
            av_bg = ACCENT_GROUP; display = label
        else:
            n = key[8:]; av_char = n[0].upper() if n else "?"
            av_bg = ACCENT_PRIVATE; display = label

        frame = tk.Frame(self.chat_list.inner, bg=BG_SIDEBAR, cursor="hand2")
        frame.pack(fill="x")

        av_lbl = tk.Label(frame, text=av_char, font=("Segoe UI", 11, "bold"),
                          bg=av_bg, fg="white", width=3, pady=10)
        av_lbl.pack(side="left", padx=(10, 0), pady=6)

        text_f = tk.Frame(frame, bg=BG_SIDEBAR)
        text_f.pack(side="left", fill="x", expand=True, padx=10, pady=6)
        name_lbl = tk.Label(text_f, text=display, font=FONT_NAME,
                            bg=BG_SIDEBAR, fg=FG_PRIMARY, anchor="w")
        name_lbl.pack(fill="x")
        sub_lbl = tk.Label(text_f, text=subtitle, font=FONT_SMALL,
                           bg=BG_SIDEBAR, fg=FG_SECONDARY, anchor="w")
        sub_lbl.pack(fill="x")

        badge = tk.Label(frame, text="", font=("Segoe UI", 8, "bold"),
                         bg=BG_SIDEBAR, fg="#FFFFFF", width=0)
        badge.pack(side="right", padx=(0, 10))

        tk.Frame(self.chat_list.inner, bg="#E0EAF2", height=1).pack(fill="x")

        all_widgets = (frame, av_lbl, text_f, name_lbl, sub_lbl, badge)

        def on_enter(_):
            if self.current_chat != key:
                for w in (frame, text_f, name_lbl, sub_lbl): w.config(bg=BG_ITEM_HVR)

        def on_leave(_):
            if self.current_chat != key:
                for w in (frame, text_f, name_lbl, sub_lbl): w.config(bg=BG_SIDEBAR)

        for w in all_widgets:
            w.bind("<Enter>",    on_enter)
            w.bind("<Leave>",    on_leave)
            w.bind("<Button-1>", lambda e, k=key: self._select_chat(k))

        self.sidebar_items[key] = frame
        self.sidebar_meta[key]  = {
            "label": display.lower(), "subtitle": subtitle.lower(),
            "av_lbl": av_lbl, "name_lbl": name_lbl,
            "sub_lbl": sub_lbl, "badge": badge, "text_f": text_f
        }
        self.unread_counts[key] = 0
        if notify: self._mark_unread(key)

    def _remove_sidebar_item(self, key):
        frame = self.sidebar_items.pop(key, None)
        if frame:
            try: frame.destroy()
            except Exception: pass
        self.sidebar_meta.pop(key, None)
        self.unread_counts.pop(key, None)
        if self.current_chat == key:
            self.current_chat = None

    def _mark_unread(self, key):
        if key == self.current_chat: return
        self.unread_counts[key] = self.unread_counts.get(key, 0) + 1
        meta  = self.sidebar_meta.get(key, {})
        badge = meta.get("badge")
        if not badge: return
        ac = (ACCENT_PRIVATE if key.startswith("private:") else
              ACCENT_GROUP   if key.startswith("group:")   else ACCENT_BROADCAST)
        count = self.unread_counts[key]
        badge.config(text=str(count) if count < 100 else "99+",
                     bg=ac, fg="white", padx=5, pady=1)

    def _clear_unread(self, key):
        self.unread_counts[key] = 0
        meta  = self.sidebar_meta.get(key, {})
        badge = meta.get("badge")
        if badge: badge.config(text="", bg=BG_SIDEBAR, padx=0)

    def _filter_sidebar(self, *_):
        q = self.search_var.get().strip().lower()
        for key, frame in self.sidebar_items.items():
            meta = self.sidebar_meta.get(key, {})
            vis  = not q or q in f"{meta.get('label', '')} {meta.get('subtitle', '')}"
            if vis:
                if not frame.winfo_manager(): frame.pack(fill="x")
            else:
                frame.pack_forget()

    def _set_notification(self, key):
        self._mark_unread(key)

    def _select_chat(self, key):
        if self.current_chat and self.current_chat in self.sidebar_items:
            old_m = self.sidebar_meta.get(self.current_chat, {})
            try:
                self.sidebar_items[self.current_chat].config(bg=BG_SIDEBAR)
                for wk in ("text_f", "name_lbl", "sub_lbl"):
                    w = old_m.get(wk)
                    if w: w.config(bg=BG_SIDEBAR)
            except Exception: pass

        self.current_chat = key
        self._clear_unread(key)

        if key in self.sidebar_items:
            self.sidebar_items[key].config(bg=BG_ITEM_SEL)
            m = self.sidebar_meta.get(key, {})
            for wk in ("text_f", "name_lbl", "sub_lbl"):
                w = m.get(wk)
                if w: w.config(bg=BG_ITEM_SEL)

        if key not in self.chat_histories:
            self.chat_histories[key] = []
        self._refresh_chat_header(key)
        self._render_messages(key)

    # ──────────────────────────────────────────────────────────────────────
    # CHAT HEADER / MESSAGES
    # ──────────────────────────────────────────────────────────────────────
    def _refresh_chat_header(self, key):
        if key == "broadcast":
            name = "Broadcast"; sub = "Message everyone online"
            av_char = "🌐"; av_bg = ACCENT_BROADCAST
        elif key.startswith("private:"):
            p = key[8:]
            name = p; sub = "Private conversation"
            av_char = p[0].upper() if p else "?"; av_bg = ACCENT_PRIVATE
        else:
            g = key[6:]
            name = g; sub = "Group conversation"
            av_char = g[0].upper() if g else "G"; av_bg = ACCENT_GROUP
        self.header_name.config(text=name)
        self.header_sub.config(text=sub)
        self.header_av.config(text=av_char, bg=av_bg)

    def _render_messages(self, key):
        for w in self.messages_frame.inner.winfo_children():
            w.destroy()
        msgs = self.chat_histories.get(key, [])
        if not msgs:
            ph = tk.Frame(self.messages_frame.inner, bg=BG_CHAT)
            ph.pack(fill="both", expand=True)
            tk.Label(ph, text="No messages yet — say hello! 👋",
                     font=("Segoe UI", 11), bg=BG_CHAT, fg="#B8CCE0")\
                .place(relx=0.5, rely=0.45, anchor="center")
            return
        for msg in msgs:
            self._add_bubble(msg)
        self.messages_frame.scroll_to_bottom()

    def _add_bubble(self, msg):
        sender = msg["sender"]; text = msg["text"]
        ts = msg["timestamp"];  is_me = msg["is_me"]

        outer = tk.Frame(self.messages_frame.inner, bg=BG_CHAT)
        outer.pack(fill="x", padx=16, pady=3)

        if sender == "":
            tk.Label(outer, text=text, font=("Segoe UI", 8, "italic"),
                     bg=BG_CHAT, fg=FG_SECONDARY, justify="center").pack(pady=2)
            return

        side = "right" if is_me else "left"
        bbg  = BG_BUBBLE_ME if is_me else BG_BUBBLE_TH
        bfg  = "#FFFFFF"    if is_me else FG_PRIMARY
        tfg  = "#A8D0F0"    if is_me else FG_TIME

        wrapper = tk.Frame(outer, bg=BG_CHAT)
        wrapper.pack(side=side, anchor="e" if is_me else "w")

        bubble = tk.Frame(wrapper, bg=bbg, padx=12, pady=8)
        bubble.pack()

        if not is_me and sender:
            tk.Label(bubble, text=sender, font=("Segoe UI", 8, "bold"),
                     bg=bbg, fg=FG_NAME).pack(anchor="w")
        tk.Label(bubble, text=text, font=FONT_BODY,
                 bg=bbg, fg=bfg, wraplength=400,
                 justify="left", anchor="w").pack(anchor="w")
        tk.Label(bubble, text=ts, font=("Segoe UI", 7),
                 bg=bbg, fg=tfg).pack(anchor="e", pady=(2, 0))

        self.messages_frame.scroll_to_bottom()

    def _push_message(self, key, sender, text, is_me):
        ts = time.strftime("%H:%M")
        if key not in self.chat_histories:
            self.chat_histories[key] = []
        msg = {"sender": sender, "text": text, "timestamp": ts, "is_me": is_me}
        self.chat_histories[key].append(msg)
        if self.current_chat == key:
            self._add_bubble(msg)
        else:
            self._mark_unread(key)

    def _system_msg(self, text, key=None):
        key = key or self.current_chat or "broadcast"
        self._push_message(key, "", f"ℹ  {text}", False)

    # ──────────────────────────────────────────────────────────────────────
    # SEND
    # ──────────────────────────────────────────────────────────────────────
    def _insert_newline(self, event=None):
        self.msg_entry.insert("insert", "\n"); return "break"

    def _send_message_event(self, event=None):
        if event and getattr(event, "keysym", "") == "Return":
            self._send_message(); return "break"
        self._send_message(); return "break"

    def _send_message(self):
        text = self.msg_entry.get("1.0", "end-1c").strip()
        if not text or not self.current_chat: return
        self.msg_entry.delete("1.0", "end")
        key = self.current_chat
        try:
            if key == "broadcast":
                if self._safe_send(f"{self.aliase}: {text}"):
                    self._push_message("broadcast", "You", text, True)
            elif key.startswith("private:"):
                partner = key[8:]
                if self._safe_send(f"private txt {partner} {text}"):
                    self._push_message(key, "You", text, True)
            elif key.startswith("group:"):
                group = key[6:]
                if self._safe_send(f"group txt {group} {text}"):
                    self._push_message(key, "You", text, True)
        except Exception as ex:
            self._system_msg(f"Send error: {ex}")

    # ──────────────────────────────────────────────────────────────────────
    # STYLED PANELS
    # ──────────────────────────────────────────────────────────────────────
    def _show_connect_panel(self):
        panel = StyledPanel(self, "Connect to User", ACCENT_PRIVATE)
        panel.geometry("360x210")
        tk.Label(panel.card, text="Enter the username to connect with:",
                 font=FONT_BODY, bg=BG_CARD, fg=FG_SECONDARY).pack(anchor="w")
        ef = tk.Frame(panel.card, bg=BG_SEARCH)
        ef.pack(fill="x", pady=(8, 0))
        e = tk.Entry(ef, font=FONT_BODY, bg=BG_SEARCH, fg=FG_PRIMARY,
                     insertbackground=FG_PRIMARY, relief="flat", bd=0)
        e.pack(fill="x", padx=10, pady=8)
        e.focus_set()
        st = tk.Label(panel.card, text="", font=FONT_SMALL, bg=BG_CARD, fg="#CC3333")
        st.pack(anchor="w", pady=(4, 0))
        def do_connect():
            name = e.get().strip()
            if not name: st.config(text="Please enter a username."); return
            self._safe_send(f"connect to {name}"); panel.destroy()
        br = tk.Frame(panel.card, bg=BG_CARD); br.pack(fill="x", pady=(14, 0))
        RoundedButton(br, "Connect", do_connect, bg=ACCENT_PRIVATE, width=120, height=36).pack(side="left")
        RoundedButton(br, "Cancel", panel.destroy, bg="#8A9AB0", width=80, height=36)\
            .pack(side="left", padx=(10, 0))
        e.bind("<Return>", lambda _: do_connect())

    def _show_online_users_panel(self):
        panel = StyledPanel(self, "Online Users", ACCENT_PRIVATE)
        panel.geometry("340x440")
        tk.Label(panel.card, text="Click a user to send a connection request.",
                 font=FONT_SMALL, bg=BG_CARD, fg=FG_SECONDARY).pack(anchor="w", pady=(0, 10))

        container = tk.Frame(panel.card, bg=BG_CARD)
        container.pack(fill="both", expand=True)
        self._online_panel_ref = panel

        loading = tk.Label(container, text="Fetching online users…",
                           font=FONT_BODY, bg=BG_CARD, fg=FG_SECONDARY)
        loading.pack(pady=20)

        def populate(users):
            for w in container.winfo_children(): w.destroy()
            users = [u for u in users if u != self.aliase]
            if not users:
                tk.Label(container, text="No other users are online right now.",
                         font=FONT_BODY, bg=BG_CARD, fg=FG_SECONDARY).pack(pady=20)
                return
            sf = ScrollableFrame(container, bg=BG_CARD)
            sf.pack(fill="both", expand=True)
            for user in sorted(users):
                row = tk.Frame(sf.inner, bg=BG_CARD, cursor="hand2")
                row.pack(fill="x", pady=2)
                av = tk.Label(row, text=user[0].upper(), font=("Segoe UI", 10, "bold"),
                              bg=ACCENT_PRIVATE, fg="white", width=3, pady=6)
                av.pack(side="left")
                nm = tk.Label(row, text=user, font=FONT_NAME, bg=BG_CARD, fg=FG_PRIMARY)
                nm.pack(side="left", padx=10)
                cl = tk.Label(row, text="Connect →", font=FONT_SMALL, bg=BG_CARD, fg=FG_BLUE)
                cl.pack(side="right", padx=8)
                tk.Frame(sf.inner, bg="#EBF1F8", height=1).pack(fill="x")
                def _conn(u=user):
                    self._safe_send(f"connect to {u}")
                    if panel.winfo_exists(): panel.destroy()
                for w in (row, av, nm, cl):
                    w.bind("<Button-1>", lambda e, u=user: _conn(u))
                    w.bind("<Enter>",    lambda e, r=row, n=nm, c=cl:
                           (r.config(bg=BG_ITEM_HVR), n.config(bg=BG_ITEM_HVR), c.config(bg=BG_ITEM_HVR)))
                    w.bind("<Leave>",    lambda e, r=row, n=nm, c=cl:
                           (r.config(bg=BG_CARD), n.config(bg=BG_CARD), c.config(bg=BG_CARD)))

        self._online_users_callback = populate
        self._safe_send("online clients")

    def _show_create_group_panel(self):
        panel = StyledPanel(self, "Create New Group", ACCENT_GROUP)
        panel.geometry("360x210")
        tk.Label(panel.card, text="Enter a name for your new group:",
                 font=FONT_BODY, bg=BG_CARD, fg=FG_SECONDARY).pack(anchor="w")
        ef = tk.Frame(panel.card, bg=BG_SEARCH)
        ef.pack(fill="x", pady=(8, 0))
        e = tk.Entry(ef, font=FONT_BODY, bg=BG_SEARCH, fg=FG_PRIMARY,
                     insertbackground=FG_PRIMARY, relief="flat", bd=0)
        e.pack(fill="x", padx=10, pady=8)
        e.focus_set()
        st = tk.Label(panel.card, text="", font=FONT_SMALL, bg=BG_CARD, fg="#CC3333")
        st.pack(anchor="w", pady=(4, 0))
        def do_create():
            name = e.get().strip()
            if not name: st.config(text="Please enter a group name."); return
            self._safe_send(f"create group {name}"); panel.destroy()
        br = tk.Frame(panel.card, bg=BG_CARD); br.pack(fill="x", pady=(14, 0))
        RoundedButton(br, "Create", do_create, bg=ACCENT_GROUP, width=120, height=36).pack(side="left")
        RoundedButton(br, "Cancel", panel.destroy, bg="#8A9AB0", width=80, height=36)\
            .pack(side="left", padx=(10, 0))
        e.bind("<Return>", lambda _: do_create())

    def _show_my_groups_panel(self):
        panel = StyledPanel(self, "My Groups", ACCENT_GROUP)
        panel.geometry("340x420")
        tk.Label(panel.card, text="Your groups — click one to open it.",
                 font=FONT_SMALL, bg=BG_CARD, fg=FG_SECONDARY).pack(anchor="w", pady=(0, 10))
        if not self.groups:
            tk.Label(panel.card,
                     text="You haven't joined any groups yet.\nUse 'Create New Group' to get started.",
                     font=FONT_BODY, bg=BG_CARD, fg=FG_SECONDARY, justify="center").pack(pady=30)
            return
        sf = ScrollableFrame(panel.card, bg=BG_CARD)
        sf.pack(fill="both", expand=True)
        for g in sorted(self.groups):
            row = tk.Frame(sf.inner, bg=BG_CARD, cursor="hand2")
            row.pack(fill="x", pady=2)
            av = tk.Label(row, text=g[0].upper(), font=("Segoe UI", 10, "bold"),
                          bg=ACCENT_GROUP, fg="white", width=3, pady=6)
            av.pack(side="left")
            nm = tk.Label(row, text=g, font=FONT_NAME, bg=BG_CARD, fg=FG_PRIMARY)
            nm.pack(side="left", padx=10)
            ol = tk.Label(row, text="Open →", font=FONT_SMALL, bg=BG_CARD, fg=FG_BLUE)
            ol.pack(side="right", padx=8)
            tk.Frame(sf.inner, bg="#EBF1F8", height=1).pack(fill="x")
            def _open(grp=g):
                key = f"group:{grp}"
                self._add_sidebar_item(key, grp, "Group chat")
                self._select_chat(key)
                panel.destroy()
            for w in (row, av, nm, ol):
                w.bind("<Button-1>", lambda e, gn=g: _open(gn))
                w.bind("<Enter>",    lambda e, r=row, n=nm, o=ol:
                       (r.config(bg=BG_ITEM_HVR), n.config(bg=BG_ITEM_HVR), o.config(bg=BG_ITEM_HVR)))
                w.bind("<Leave>",    lambda e, r=row, n=nm, o=ol:
                       (r.config(bg=BG_CARD), n.config(bg=BG_CARD), o.config(bg=BG_CARD)))

    # ──────────────────────────────────────────────────────────────────────
    # RECEIVE LOOP
    # ──────────────────────────────────────────────────────────────────────
    def _recv_loop(self):
        try:
            while True:
                line = self._recv_line_sync()
                if line is None: break
                line = line.strip()
                if line: self.after(0, self._handle_server_msg, line)
        except Exception: pass
        self.after(0, self._system_msg, "Disconnected from server.")

    def _handle_server_msg(self, msg):
        if msg.startswith("PRIVATE_REQUEST_FROM:"):
            requester = msg.split(":", 1)[1]
            self.pending_requesters.add(requester)
            self._show_styled_popup(
                f"🔔  {requester} wants to chat privately.",
                [("Accept", lambda r=requester: self._accept_conn(r), ACCENT_GROUP),
                 ("Reject", lambda r=requester: self._reject_conn(r), "#CC3333")]); return

        if msg.startswith("PRIVATE_CONNECTED:"):
            partner = msg.split(":", 1)[1]
            self.private_partners.add(partner)
            self.pending_requesters.discard(partner)
            self._add_sidebar_item(f"private:{partner}", partner, "Private chat")
            self._system_msg(f"Private chat with {partner} connected.", f"private:{partner}"); return

        if msg.startswith("PRIVATE_REJECTED:"):
            self._system_msg(f"{msg.split(':',1)[1]} declined your request."); return

        if msg.startswith("PRIVATE_ENDED:"):
            parts = msg.split(":", 2)
            who = parts[1] if len(parts) > 1 else "?"
            reason = parts[2] if len(parts) > 2 else "ended"
            self.private_partners.discard(who)
            self._system_msg(f"Private chat with {who} ended ({reason}).", f"private:{who}")
            self._remove_sidebar_item(f"private:{who}"); return

        if msg.startswith("GROUP_INVITE:"):
            parts = msg.split(":", 2)
            if len(parts) == 3:
                gname, inviter = parts[1], parts[2]
                self.pending_group_invites.add(gname)
                self._show_styled_popup(
                    f"👥  {inviter} invited you to group '{gname}'.",
                    [("Join",    lambda g=gname: self._accept_group(g), ACCENT_GROUP),
                     ("Decline", lambda g=gname: self._reject_group(g), "#CC3333")]); return

        if msg.startswith("GROUP_JOINED:"):
            gname = msg.split(":", 1)[1]
            self.groups.add(gname)
            self.pending_group_invites.discard(gname)
            self._add_sidebar_item(f"group:{gname}", gname, "Group chat"); return

        if msg.startswith("[Group:"):
            try:
                be = msg.index("]"); gname = msg[7:be]; rest = msg[be+2:]
                sender, text = (rest.split(":", 1) if ":" in rest else ("?", rest))
                sender = sender.strip(); text = text.strip()
                key = f"group:{gname}"
                self.groups.add(gname)
                self._add_sidebar_item(key, gname, "Group chat", notify=True)
                self._push_message(key, sender, text, False)
            except Exception: self._system_msg(msg)
            return

        if msg.startswith("[Private:"):
            try:
                be = msg.index("]"); rest = msg[be+2:]
                sender, text = (rest.split(":", 1) if ":" in rest else ("?", rest))
                sender = sender.strip(); text = text.strip()
                key = f"private:{sender}"
                self.private_partners.add(sender)
                self._add_sidebar_item(key, sender, "Private chat", notify=True)
                self._push_message(key, sender, text, False)
            except Exception: self._system_msg(msg)
            return

        if msg.startswith("[Offline Private]"):
            try:
                rest = msg[len("[Offline Private] "):]
                sender, text = (rest.split(":", 1) if ":" in rest else ("?", rest))
                sender = sender.strip(); text = text.strip()
                key = f"private:{sender}"
                self.private_partners.add(sender)
                self._add_sidebar_item(key, sender, "Private chat", notify=True)
                self._push_message(key, sender, text, False)
            except Exception: self._system_msg(msg)
            return

        if msg.startswith("FILE_START_FROM|"):
            parts = msg.split("|", 4)
            if len(parts) == 5:
                self.incoming_transfers[parts[4]] = {
                    "filename": os.path.basename(parts[2]),
                    "sender": parts[1], "size": parts[3], "chunks": {}}
            return

        if msg.startswith("FILE_CHUNK_FROM|"):
            parts = msg.split("|", 4)
            if len(parts) == 5:
                _, sender, tid, seq, chunk_b64 = parts
                if tid in self.incoming_transfers and seq.isdigit():
                    try:
                        self.incoming_transfers[tid]["chunks"][int(seq)] = \
                            base64.b64decode(chunk_b64.encode())
                    except Exception: pass
            return

        if msg.startswith("FILE_END_FROM|"):
            parts = msg.split("|", 3)
            if len(parts) == 4:
                _, sender, tid, total_s = parts
                if total_s.isdigit(): self._finalize_transfer(sender, tid, int(total_s))
            return

        if msg.startswith("Groups:"):
            names = msg.split(":", 1)[1].strip()
            if names and names.lower() != "none":
                for g in [n.strip() for n in names.split(",") if n.strip()]:
                    self.groups.add(g)
                    self._add_sidebar_item(f"group:{g}", g, "Group chat")
            return

        if msg.startswith("Private chats:"):
            names = msg.split(":", 1)[1].strip()
            if names and names.lower() != "none":
                for p in [n.strip() for n in names.split(",") if n.strip()]:
                    self.private_partners.add(p)
                    self._add_sidebar_item(f"private:{p}", p, "Private chat")
            return

        if msg.startswith("Online clients:"):
            names = msg.split(":", 1)[1].strip()
            self.online_users = (set(u.strip() for u in names.split(",") if u.strip())
                                 if names and names != "No clients online." else set())
            cb = self._online_users_callback
            if cb:
                self._online_users_callback = None
                cb(list(self.online_users))
            return

        if msg.startswith("INFO:"):
            self._system_msg(msg[5:].strip()); return

        if ": " in msg:
            sender, text = msg.split(": ", 1)
            sender = sender.strip()
            if sender != self.aliase:
                self._push_message("broadcast", sender, text, False)
            return

        if msg == "you are now connected":
            self._system_msg(msg); return

        self._system_msg(msg)

    # ──────────────────────────────────────────────────────────────────────
    # BEEP LOOP
    # ──────────────────────────────────────────────────────────────────────
    def _beep_loop(self):
        while True:
            try:
                payload, _ = self.beep_sock.recvfrom(4096)
                text = payload.decode(errors="ignore")
                if text.startswith("BEEP:"):
                    parts = text.split(":", 2)
                    if len(parts) == 3:
                        sender = parts[1].strip(); channel = parts[2].strip()
                        if channel in ("PRIVATE", "FILE"):
                            self.after(0, self._mark_unread, f"private:{sender}")
                        elif channel == "BROADCAST":
                            self.after(0, self._mark_unread, "broadcast")
                        elif channel.startswith("GROUP:"):
                            self.after(0, self._mark_unread, f"group:{channel.split(':',1)[1].strip()}")
            except Exception: break

    def _register_beep_port(self):
        self._safe_send(f"BEEP_UDP_PORT:{self._beep_port}")

    # ──────────────────────────────────────────────────────────────────────
    # FILE TRANSFER
    # ──────────────────────────────────────────────────────────────────────
    def _finalize_transfer(self, sender, transfer_id, total_chunks):
        transfer = self.incoming_transfers.get(transfer_id)
        if not transfer: return
        chunks = transfer["chunks"]
        missing = [i for i in range(total_chunks) if i not in chunks]
        if missing:
            self._system_msg(f"Incomplete file from {sender} ({len(missing)} missing chunks)")
            self.incoming_transfers.pop(transfer_id, None); return
        data = b"".join(chunks[i] for i in range(total_chunks))
        dl_dir = os.path.join(os.getcwd(), "downloads")
        os.makedirs(dl_dir, exist_ok=True)
        out = os.path.join(dl_dir, transfer["filename"])
        with open(out, "wb") as f: f.write(data)
        self._system_msg(f"📎 File from {sender} saved: {out}", key=f"private:{sender}")
        self.incoming_transfers.pop(transfer_id, None)

    def _send_file_to(self, target, path):
        if not os.path.isfile(path): self._system_msg("File not found."); return
        def _do():
            try:
                with open(path, "rb") as f: data = f.read()
                filename = os.path.basename(path); tid = str(uuid.uuid4())
                chunk_size = 400; total = (len(data) + chunk_size - 1) // chunk_size
                self._safe_send(f"FILE_START|{target}|{filename}|{len(data)}|{tid}")
                for i in range(total):
                    encoded = base64.b64encode(data[i*chunk_size:(i+1)*chunk_size]).decode()
                    self._safe_send(f"FILE_CHUNK|{target}|{tid}|{i}|{encoded}")
                self._safe_send(f"FILE_END|{target}|{tid}|{total}")
                self.after(0, self._system_msg, f"📎 Sent {filename} to {target}", f"private:{target}")
            except Exception as ex:
                self.after(0, self._system_msg, f"File send error: {ex}")
        threading.Thread(target=_do, daemon=True).start()

    # ──────────────────────────────────────────────────────────────────────
    # PROMPTS / ACTIONS
    # ──────────────────────────────────────────────────────────────────────
    def _prompt_send_file(self):
        key = self.current_chat
        if not key or not (key.startswith("private:") or key.startswith("group:")):
            self._show_styled_popup("Open a private or group chat to send files.", [])
            return
        target = key[8:] if key.startswith("private:") else key[6:]
        path = filedialog.askopenfilename(parent=self, title="Choose a file")
        if path:
            self._send_file_to(target, path)

    def _prompt_connect(self):
        name = simpledialog.askstring("Connect", "Enter username to connect to:", parent=self)
        if name: self._safe_send(f"connect to {name}")

    def _prompt_create_group(self):
        name = simpledialog.askstring("New Group", "Group name:", parent=self)
        if name: self._safe_send(f"create group {name}")

    def _prompt_invite_group(self):
        if not self.current_chat or not self.current_chat.startswith("group:"):
            self._show_styled_popup("Open a group chat first to invite members.", []); return
        gname = self.current_chat[6:]
        panel = StyledPanel(self, f"Invite to '{gname}'", ACCENT_GROUP)
        panel.geometry("360x190")
        tk.Label(panel.card, text="Username to invite:", font=FONT_BODY,
                 bg=BG_CARD, fg=FG_SECONDARY).pack(anchor="w")
        ef = tk.Frame(panel.card, bg=BG_SEARCH); ef.pack(fill="x", pady=(8, 0))
        e = tk.Entry(ef, font=FONT_BODY, bg=BG_SEARCH, fg=FG_PRIMARY,
                     insertbackground=FG_PRIMARY, relief="flat", bd=0)
        e.pack(fill="x", padx=10, pady=8); e.focus_set()
        def do_invite():
            user = e.get().strip()
            if user: self._safe_send(f"invite group {gname} {user}")
            panel.destroy()
        br = tk.Frame(panel.card, bg=BG_CARD); br.pack(fill="x", pady=(14, 0))
        RoundedButton(br, "Invite", do_invite, bg=ACCENT_GROUP, width=100, height=36).pack(side="left")
        RoundedButton(br, "Cancel", panel.destroy, bg="#8A9AB0", width=80, height=36)\
            .pack(side="left", padx=(10, 0))
        e.bind("<Return>", lambda _: do_invite())

    def _ask_online(self):
        self._safe_send("online clients")

    def _accept_conn(self, requester):
        self._safe_send(f"accept connection {requester}")

    def _reject_conn(self, requester):
        self._safe_send(f"reject connection {requester}")

    def _accept_group(self, gname):
        self._safe_send(f"accept group {gname}")

    def _reject_group(self, gname):
        self._safe_send(f"reject group {gname}")

    def _end_current_chat(self):
        key = self.current_chat
        if not key: return
        if key.startswith("private:"):
            self._safe_send(f"end private {key[8:]}")
        elif key.startswith("group:"):
            self._show_styled_popup("Group leaving is not yet supported by the server.", [])

    def _logout(self):
        try: self._safe_send("exit")
        except Exception: pass
        self._on_close()

    # ──────────────────────────────────────────────────────────────────────
    # STYLED POPUP
    # ──────────────────────────────────────────────────────────────────────
    def _show_styled_popup(self, message, buttons):
        popup = tk.Toplevel(self)
        popup.configure(bg=BG_MAIN)
        popup.title("Notification")
        popup.resizable(False, False)
        popup.grab_set()
        popup.transient(self)
        tk.Frame(popup, bg=ACCENT_GROUP, height=4).pack(fill="x")
        card = tk.Frame(popup, bg=BG_CARD, padx=28, pady=22)
        card.pack(fill="both", expand=True, padx=10, pady=10)
        tk.Label(card, text=message, font=FONT_BODY, bg=BG_CARD, fg=FG_PRIMARY,
                 wraplength=340, justify="left").pack(anchor="w", pady=(0, 16))
        if buttons:
            br = tk.Frame(card, bg=BG_CARD); br.pack(anchor="w")
            for label, cmd, col in buttons:
                def _action(c=cmd, p=popup):
                    c()
                    if p.winfo_exists(): p.destroy()
                RoundedButton(br, label, _action, bg=col,
                              width=96, height=32).pack(side="left", padx=(0, 8))
        else:
            RoundedButton(card, "OK", popup.destroy,
                          bg=ACCENT_GROUP, width=80, height=32).pack(anchor="w")
        popup.update_idletasks()
        px = self.winfo_x() + (self.winfo_width()  - popup.winfo_width())  // 2
        py = self.winfo_y() + (self.winfo_height() - popup.winfo_height()) // 2
        popup.geometry(f"+{px}+{py}")
        popup.after(18000, lambda: popup.destroy() if popup.winfo_exists() else None)


if __name__ == "__main__":
    app = Chat77App()
    app.mainloop()