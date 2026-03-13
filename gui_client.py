import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import threading
import socket
import os
import base64
import uuid
import time


# ─── Colour palette ───────────────────────────────────────────────────────────
BG_SIDEBAR   = "#111B21"
BG_CHAT      = "#0B141A"
BG_BUBBLE_ME = "#005C4B"
BG_BUBBLE_TH = "#202C33"
BG_INPUT     = "#202C33"
BG_HEADER    = "#202C33"
BG_ITEM_HVR  = "#2A3942"
BG_ITEM_SEL  = "#2A3942"
BG_SEARCH    = "#2A3942"

FG_PRIMARY   = "#E9EDEF"
FG_SECONDARY = "#8696A0"
FG_TIME      = "#8696A0"
FG_GREEN     = "#00A884"
FG_NAME      = "#53BDEB"

FONT_BODY    = ("Segoe UI", 10)
FONT_SMALL   = ("Segoe UI", 8)
FONT_NAME    = ("Segoe UI", 10, "bold")
FONT_HEADER  = ("Segoe UI", 11, "bold")
FONT_TITLE   = ("Segoe UI", 13, "bold")


class RoundedButton(tk.Frame):
    def __init__(self, parent, text, command, bg=FG_GREEN, fg="white",
                 width=120, height=34, font=FONT_BODY, **kw):
        super().__init__(parent, bg=bg, cursor="hand2",
                         width=width, height=height, **kw)
        self.pack_propagate(False)
        self._bg = bg
        self._hover_bg = self._lighten(bg)
        self._command = command

        self._lbl = tk.Label(self, text=text, font=font, bg=bg, fg=fg, cursor="hand2")
        self._lbl.place(relx=0.5, rely=0.5, anchor="center")

        for w in (self, self._lbl):
            w.bind("<Button-1>", lambda e: self._command())
            w.bind("<Enter>", lambda e: self._on_enter())
            w.bind("<Leave>", lambda e: self._on_leave())

    @staticmethod
    def _lighten(hex_color):
        import colorsys
        try:
            r, g, b = (int(hex_color[i:i+2], 16) / 255 for i in (1, 3, 5))
            h, s, v = colorsys.rgb_to_hsv(r, g, b)
            r2, g2, b2 = colorsys.hsv_to_rgb(h, s, min(v * 1.15, 1))
            return f"#{int(r2*255):02x}{int(g2*255):02x}{int(b2*255):02x}"
        except Exception:
            return hex_color

    def _on_enter(self):
        self.config(bg=self._hover_bg)
        self._lbl.config(bg=self._hover_bg)

    def _on_leave(self):
        self.config(bg=self._bg)
        self._lbl.config(bg=self._bg)


class ScrollableFrame(tk.Frame):
    def __init__(self, parent, bg=BG_SIDEBAR, **kw):
        super().__init__(parent, bg=bg, **kw)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0, yscrollincrement=1)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg=bg)

        self.inner.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )

        self.window_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        self.canvas.bind(
            "<Configure>",
            lambda e: self.canvas.itemconfig(self.window_id, width=e.width)
        )

        self.canvas.bind_all(
            "<MouseWheel>",
            lambda e: self.canvas.yview_scroll(-1 * (e.delta // 120), "units")
        )

    def scroll_to_bottom(self):
        self.canvas.update_idletasks()
        self.canvas.yview_moveto(1.0)


class Chat77App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Chat77")
        self.geometry("1100x700")
        self.minsize(800, 550)
        self.configure(bg=BG_SIDEBAR)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Network state
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

        # UI state
        self.current_chat = None
        self.chat_histories = {}
        self.sidebar_items = {}
        self.sidebar_meta = {}
        self._connecting = False

        self._build_login_screen()

    # ──────────────────────────────────────────────────────────────────────
    # SOCKET HELPERS
    # ──────────────────────────────────────────────────────────────────────
    def _safe_send(self, text):
        try:
            if not self.sock:
                return False
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
            if not chunk:
                return None
            self.recv_buffer += chunk

    def _on_close(self):
        try:
            self._safe_send("exit")
        except Exception:
            pass

        try:
            if self.sock:
                self.sock.close()
        except Exception:
            pass

        try:
            if self.beep_sock:
                self.beep_sock.close()
        except Exception:
            pass

        self.destroy()

    # ──────────────────────────────────────────────────────────────────────
    # LOGIN SCREEN
    # ──────────────────────────────────────────────────────────────────────
    def _build_login_screen(self):
        self.login_frame = tk.Frame(self, bg=BG_CHAT)
        self.login_frame.pack(fill="both", expand=True)

        card = tk.Frame(self.login_frame, bg=BG_HEADER, padx=40, pady=40)
        card.place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(card, text="Chat77", font=("Segoe UI", 28, "bold"),
                 bg=BG_HEADER, fg=FG_GREEN).grid(row=0, columnspan=2, pady=(0, 4))

        tk.Label(card, text="Connect. Chat. Together.",
                 font=FONT_SMALL, bg=BG_HEADER, fg=FG_SECONDARY)\
            .grid(row=1, columnspan=2, pady=(0, 24))

        def lbl(txt, r):
            tk.Label(card, text=txt, font=FONT_BODY, bg=BG_HEADER,
                     fg=FG_SECONDARY, anchor="w")\
                .grid(row=r, column=0, sticky="w", pady=4)

        def entry(r, show=None):
            e = tk.Entry(card, font=FONT_BODY, bg=BG_SEARCH, fg=FG_PRIMARY,
                         insertbackground=FG_PRIMARY, relief="flat",
                         width=28, show=show)
            e.grid(row=r, column=1, padx=(12, 0), pady=4, ipady=6)
            return e

        lbl("Server IP", 2)
        self.e_ip = entry(2)
        lbl("Username", 3)
        self.e_user = entry(3)
        lbl("Password", 4)
        self.e_pass = entry(4, show="•")

        self.auth_mode = tk.StringVar(value="LOGIN")
        frm = tk.Frame(card, bg=BG_HEADER)
        frm.grid(row=5, columnspan=2, pady=(12, 0))

        for val, txt in (("LOGIN", "Login"), ("REGISTER", "Register")):
            tk.Radiobutton(frm, text=txt, variable=self.auth_mode, value=val,
                           bg=BG_HEADER, fg=FG_PRIMARY, selectcolor=BG_SEARCH,
                           activebackground=BG_HEADER, font=FONT_BODY)\
                .pack(side="left", padx=12)

        self.login_status = tk.Label(card, text="", font=FONT_SMALL,
                                     bg=BG_HEADER, fg="#FF6B6B", wraplength=320)
        self.login_status.grid(row=6, columnspan=2, pady=(8, 0))

        btn_frame = tk.Frame(card, bg=BG_HEADER)
        btn_frame.grid(row=7, columnspan=2, pady=(18, 0))

        self.connect_btn = RoundedButton(btn_frame, "Connect", self._do_connect,
                                         width=140, height=38)
        self.connect_btn.pack()

        self.e_ip.insert(0, "127.0.0.1")
        self.e_ip.focus_set()
        self.bind("<Return>", lambda _: self._do_connect())

    def _do_connect(self):
        if self._connecting:
            return

        ip = self.e_ip.get().strip()
        user = self.e_user.get().strip()
        pwd = self.e_pass.get().strip()
        mode = self.auth_mode.get()

        if not ip or not user or not pwd:
            self.login_status.config(text="Please fill in all fields.", fg="#FF6B6B")
            return

        self._connecting = True
        self.login_status.config(text="Connecting…", fg=FG_SECONDARY)
        self.update()

        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((ip, 22081))
            self.recv_buffer = b""
        except Exception as ex:
            self.login_status.config(text=f"Cannot connect: {ex}", fg="#FF6B6B")
            self._connecting = False
            return

        try:
            self.beep_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.beep_sock.bind(("", 0))
            self._beep_port = self.beep_sock.getsockname()[1]
        except Exception as ex:
            self.login_status.config(text=f"UDP setup failed: {ex}", fg="#FF6B6B")
            self._connecting = False
            return

        ok = self._authenticate(user, pwd, mode)
        if ok:
            self.aliase = user
            self.login_frame.destroy()
            self._build_main_ui()
            self._register_beep_port()
            self._initial_sync()
            threading.Thread(target=self._recv_loop, daemon=True).start()
            threading.Thread(target=self._beep_loop, daemon=True).start()

        self._connecting = False

    def _authenticate(self, user, pwd, mode):
        while True:
            try:
                msg = self._recv_line_sync()
                if msg is None:
                    self.login_status.config(text="Connection lost during auth.", fg="#FF6B6B")
                    return False
            except Exception:
                self.login_status.config(text="Connection lost during auth.", fg="#FF6B6B")
                return False

            if msg.startswith("Authorise MODE"):
                self._safe_send(mode)

            elif msg == "ALIAS?":
                self._safe_send(user)

            elif msg == "PASSWORD?":
                self._safe_send(pwd)

            elif msg.startswith("ERROR:"):
                self.login_status.config(text=msg, fg="#FF6B6B")
                return False

            elif msg == "This alias is already logged in":
                self.login_status.config(text=msg, fg="#FF6B6B")
                return False

            elif msg in ("AUTH_SUCCESS", "SUCCESSFULLY AUTHENTICATE"):
                return True

            else:
                self.login_status.config(text=msg, fg=FG_SECONDARY)

    def _initial_sync(self):
        self._safe_send("my groups")
        self._safe_send("my private chats")

    # ──────────────────────────────────────────────────────────────────────
    # MAIN UI
    # ──────────────────────────────────────────────────────────────────────
    def _build_main_ui(self):
        self.main_pane = tk.PanedWindow(
            self,
            orient="horizontal",
            sashrelief="flat",
            sashwidth=1,
            bg="#2A3942"
        )
        self.main_pane.pack(fill="both", expand=True)

        self._build_sidebar()
        self._build_chat_area()

        self.main_pane.add(self.sidebar, minsize=280)
        self.main_pane.add(self.chat_container, minsize=400)

        self._add_sidebar_item("broadcast", "🌐  Broadcast", "Everyone")
        self._select_chat("broadcast")

    def _build_sidebar(self):
        self.sidebar = tk.Frame(self.main_pane, bg=BG_SIDEBAR, width=300)

        top = tk.Frame(self.sidebar, bg=BG_HEADER, padx=12, pady=10)
        top.pack(fill="x")

        tk.Label(top, text="Chat77", font=FONT_TITLE,
                 bg=BG_HEADER, fg=FG_PRIMARY).pack(side="left")

        btn_bar = tk.Frame(top, bg=BG_HEADER)
        btn_bar.pack(side="right")

        for sym, cmd in (
            ("👥", self._prompt_create_group),
            ("➕", self._prompt_connect),
            ("⚙", self._ask_online),
        ):
            b = tk.Label(btn_bar, text=sym, font=("Segoe UI", 14),
                         bg=BG_HEADER, fg=FG_SECONDARY, cursor="hand2", padx=6)
            b.pack(side="left")
            b.bind("<Button-1>", lambda e, c=cmd: c())
            b.bind("<Enter>", lambda e, w=b: w.config(fg=FG_PRIMARY))
            b.bind("<Leave>", lambda e, w=b: w.config(fg=FG_SECONDARY))

        search_frame = tk.Frame(self.sidebar, bg=BG_SIDEBAR, pady=6, padx=8)
        search_frame.pack(fill="x")

        s_inner = tk.Frame(search_frame, bg=BG_SEARCH, pady=6, padx=10)
        s_inner.pack(fill="x")

        tk.Label(s_inner, text="🔍", bg=BG_SEARCH, fg=FG_SECONDARY,
                 font=("Segoe UI", 10)).pack(side="left")

        self.search_var = tk.StringVar()
        se = tk.Entry(s_inner, textvariable=self.search_var, bg=BG_SEARCH,
                      fg=FG_PRIMARY, font=FONT_BODY, insertbackground=FG_PRIMARY,
                      relief="flat", borderwidth=0)
        se.pack(side="left", fill="x", expand=True, padx=(6, 0))
        self.search_var.trace_add("write", self._filter_sidebar)

        self.chat_list = ScrollableFrame(self.sidebar, bg=BG_SIDEBAR)
        self.chat_list.pack(fill="both", expand=True)

        tk.Frame(self.sidebar, bg="#2A3942", height=1).pack(fill="x")

        info = tk.Frame(self.sidebar, bg=BG_HEADER, padx=12, pady=8)
        info.pack(fill="x", side="bottom")

        av = tk.Label(info, text=self.aliase[0].upper() if self.aliase else "?",
                      font=("Segoe UI", 12, "bold"), bg=FG_GREEN,
                      fg="white", width=3)
        av.pack(side="left")

        tk.Label(info, text=self.aliase, font=FONT_NAME,
                 bg=BG_HEADER, fg=FG_PRIMARY).pack(side="left", padx=10)

        RoundedButton(info, "Logout", self._logout, bg="#FF6B6B",
                      width=70, height=26, font=FONT_SMALL).pack(side="right")

    def _build_chat_area(self):
        self.chat_container = tk.Frame(self.main_pane, bg=BG_CHAT)

        self.chat_header = tk.Frame(self.chat_container, bg=BG_HEADER, pady=10, padx=16)
        self.chat_header.pack(fill="x")

        self.header_av = tk.Label(self.chat_header, text="🌐",
                                  font=("Segoe UI", 14), bg=FG_GREEN,
                                  fg="white", width=3)
        self.header_av.pack(side="left")

        info = tk.Frame(self.chat_header, bg=BG_HEADER)
        info.pack(side="left", padx=10)

        self.header_name = tk.Label(info, text="Select a chat", font=FONT_HEADER,
                                    bg=BG_HEADER, fg=FG_PRIMARY)
        self.header_name.pack(anchor="w")

        self.header_sub = tk.Label(info, text="", font=FONT_SMALL,
                                   bg=BG_HEADER, fg=FG_SECONDARY)
        self.header_sub.pack(anchor="w")

        hbtn = tk.Frame(self.chat_header, bg=BG_HEADER)
        hbtn.pack(side="right")

        self._hdr_btns = {}
        for sym, tip, cmd in (
            ("📎", "Send File", self._prompt_send_file),
            ("👥", "Invite Member", self._prompt_invite_group),
            ("🚫", "End Chat", self._end_current_chat),
        ):
            b = tk.Label(hbtn, text=sym, font=("Segoe UI", 14),
                         bg=BG_HEADER, fg=FG_SECONDARY, cursor="hand2", padx=8)
            b.pack(side="left")
            b.bind("<Button-1>", lambda e, c=cmd: c())
            b.bind("<Enter>", lambda e, w=b: w.config(fg=FG_PRIMARY))
            b.bind("<Leave>", lambda e, w=b: w.config(fg=FG_SECONDARY))
            self._hdr_btns[tip] = b

        tk.Frame(self.chat_container, bg="#2A3942", height=1).pack(fill="x")

        self.messages_frame = ScrollableFrame(self.chat_container, bg=BG_CHAT)
        self.messages_frame.pack(fill="both", expand=True)

        self.input_outer = tk.Frame(self.chat_container, bg=BG_SIDEBAR, pady=8, padx=8)
        self.input_outer.pack(fill="x", side="bottom")

        input_inner = tk.Frame(self.input_outer, bg=BG_INPUT, pady=6, padx=12)
        input_inner.pack(fill="x")

        self.msg_entry = tk.Text(input_inner, font=FONT_BODY, bg=BG_INPUT,
                                 fg=FG_PRIMARY, insertbackground=FG_PRIMARY,
                                 relief="flat", height=2, wrap="word", borderwidth=0)
        self.msg_entry.pack(side="left", fill="x", expand=True)
        self.msg_entry.bind("<Return>", self._send_message_event)
        self.msg_entry.bind("<Shift-Return>", self._insert_newline)

        send_btn = tk.Label(input_inner, text="➤", font=("Segoe UI", 16),
                            bg=BG_INPUT, fg=FG_GREEN, cursor="hand2", padx=8)
        send_btn.pack(side="right")
        send_btn.bind("<Button-1>", self._send_message_event)
        send_btn.bind("<Enter>", lambda e: send_btn.config(fg=FG_PRIMARY))
        send_btn.bind("<Leave>", lambda e: send_btn.config(fg=FG_GREEN))

    # ──────────────────────────────────────────────────────────────────────
    # SIDEBAR
    # ──────────────────────────────────────────────────────────────────────
    def _add_sidebar_item(self, key, label, subtitle="", notify=False):
        if key in self.sidebar_items:
            self.sidebar_meta[key] = {
                "label": label.lower(),
                "subtitle": subtitle.lower()
            }
            if notify:
                self._set_notification(key)
            return

        frame = tk.Frame(self.chat_list.inner, bg=BG_SIDEBAR, cursor="hand2")
        frame.pack(fill="x")

        if key == "broadcast":
            av_char = "🌐"
            av_bg = FG_GREEN
        elif key.startswith("group:"):
            name = label.replace("👥", "").strip()
            av_char = name[0].upper() if name else "?"
            av_bg = "#E67E22"
        else:
            name = label.replace("👤", "").strip()
            av_char = name[0].upper() if name else "?"
            av_bg = "#7B68EE"

        av_lbl = tk.Label(frame, text=av_char, font=("Segoe UI", 12, "bold"),
                          bg=av_bg, fg="white", width=3, pady=8)
        av_lbl.pack(side="left", padx=(8, 0), pady=6)

        text_frame = tk.Frame(frame, bg=BG_SIDEBAR)
        text_frame.pack(side="left", fill="x", expand=True, padx=10, pady=6)

        name_lbl = tk.Label(text_frame, text=label, font=FONT_NAME,
                            bg=BG_SIDEBAR, fg=FG_PRIMARY, anchor="w")
        name_lbl.pack(fill="x")

        sub_lbl = tk.Label(text_frame, text=subtitle, font=FONT_SMALL,
                           bg=BG_SIDEBAR, fg=FG_SECONDARY, anchor="w")
        sub_lbl.pack(fill="x")

        tk.Frame(self.chat_list.inner, bg="#1A2229", height=1).pack(fill="x")

        def on_enter(_):
            frame.config(bg=BG_ITEM_SEL if self.current_chat == key else BG_ITEM_HVR)

        def on_leave(_):
            frame.config(bg=BG_ITEM_SEL if self.current_chat == key else BG_SIDEBAR)

        for w in (frame, av_lbl, text_frame, name_lbl, sub_lbl):
            w.bind("<Enter>", on_enter)
            w.bind("<Leave>", on_leave)
            w.bind("<Button-1>", lambda e, k=key: self._select_chat(k))

        self.sidebar_items[key] = frame
        self.sidebar_meta[key] = {
            "label": label.lower(),
            "subtitle": subtitle.lower()
        }

        if notify:
            self._set_notification(key)

    def _remove_sidebar_item(self, key):
        frame = self.sidebar_items.pop(key, None)
        if frame:
            try:
                frame.destroy()
            except Exception:
                pass
        self.sidebar_meta.pop(key, None)

        if self.current_chat == key:
            self.current_chat = None
            if "broadcast" in self.sidebar_items:
                self._select_chat("broadcast")

    def _filter_sidebar(self, *_):
        q = self.search_var.get().strip().lower()
        for key, frame in self.sidebar_items.items():
            meta = self.sidebar_meta.get(key, {})
            searchable = f"{meta.get('label', '')} {meta.get('subtitle', '')}"
            if not q or q in searchable:
                if not frame.winfo_manager():
                    frame.pack(fill="x")
            else:
                frame.pack_forget()

    def _set_notification(self, key):
        frame = self.sidebar_items.get(key)
        if not frame or self.current_chat == key:
            return

        orig = frame.cget("bg")

        def flash(n=0):
            if not frame.winfo_exists():
                return
            if n >= 6:
                frame.config(bg=orig)
                return
            frame.config(bg="#005C4B" if n % 2 == 0 else orig)
            self.after(250, lambda: flash(n + 1))

        flash()

    def _select_chat(self, key):
        if self.current_chat and self.current_chat in self.sidebar_items:
            try:
                self.sidebar_items[self.current_chat].config(bg=BG_SIDEBAR)
            except Exception:
                pass

        self.current_chat = key

        if key in self.sidebar_items:
            self.sidebar_items[key].config(bg=BG_ITEM_SEL)

        if key not in self.chat_histories:
            self.chat_histories[key] = []

        self._refresh_chat_header(key)
        self._render_messages(key)

    # ──────────────────────────────────────────────────────────────────────
    # CHAT HEADER / MESSAGES
    # ──────────────────────────────────────────────────────────────────────
    def _refresh_chat_header(self, key):
        if key == "broadcast":
            name = "Broadcast"
            sub = "Message everyone online"
            av = "🌐"
            av_bg = FG_GREEN
        elif key.startswith("private:"):
            partner = key[8:]
            name = partner
            sub = "Private chat"
            av = partner[0].upper() if partner else "?"
            av_bg = "#7B68EE"
        else:
            group = key[6:]
            name = group
            sub = "Group chat"
            av = group[0].upper() if group else "?"
            av_bg = "#E67E22"

        self.header_name.config(text=name)
        self.header_sub.config(text=sub)
        self.header_av.config(text=av, bg=av_bg)

        is_group = key.startswith("group:")
        is_private = key.startswith("private:")

        self._hdr_btns["Send File"].config(fg=FG_SECONDARY if is_private else "#3A515D")
        self._hdr_btns["Invite Member"].config(fg=FG_SECONDARY if is_group else "#3A515D")

    def _render_messages(self, key):
        for w in self.messages_frame.inner.winfo_children():
            w.destroy()

        msgs = self.chat_histories.get(key, [])
        if not msgs:
            tk.Label(self.messages_frame.inner, text="No messages yet. Say hello! 👋",
                     font=FONT_BODY, bg=BG_CHAT, fg="#3A515D").pack(pady=40)
            return

        for msg in msgs:
            self._add_bubble(msg, key)

        self.messages_frame.scroll_to_bottom()

    def _add_bubble(self, msg, key=None):
        sender = msg["sender"]
        text = msg["text"]
        ts = msg["timestamp"]
        is_me = msg["is_me"]

        outer = tk.Frame(self.messages_frame.inner, bg=BG_CHAT)
        outer.pack(fill="x", padx=12, pady=2)

        bubble_bg = BG_BUBBLE_ME if is_me else BG_BUBBLE_TH
        side = "right" if is_me else "left"

        wrapper = tk.Frame(outer, bg=BG_CHAT)
        wrapper.pack(side=side)

        bubble = tk.Frame(wrapper, bg=bubble_bg, padx=10, pady=6)
        bubble.pack()

        if not is_me and sender:
            tk.Label(bubble, text=sender, font=FONT_SMALL,
                     bg=bubble_bg, fg=FG_NAME).pack(anchor="w")

        tk.Label(bubble, text=text, font=FONT_BODY,
                 bg=bubble_bg, fg=FG_PRIMARY,
                 wraplength=380, justify="left", anchor="w").pack(anchor="w")

        tk.Label(bubble, text=ts, font=("Segoe UI", 7),
                 bg=bubble_bg, fg=FG_TIME).pack(anchor="e")

        self.messages_frame.scroll_to_bottom()

    def _push_message(self, key, sender, text, is_me):
        ts = time.strftime("%H:%M")
        if key not in self.chat_histories:
            self.chat_histories[key] = []

        msg = {
            "sender": sender,
            "text": text,
            "timestamp": ts,
            "is_me": is_me
        }
        self.chat_histories[key].append(msg)

        if self.current_chat == key:
            self._add_bubble(msg, key)
        else:
            self._set_notification(key)

    def _system_msg(self, text, key=None):
        key = key or self.current_chat or "broadcast"
        self._push_message(key, "", f"ℹ  {text}", False)

    # ──────────────────────────────────────────────────────────────────────
    # SEND
    # ──────────────────────────────────────────────────────────────────────
    def _insert_newline(self, event=None):
        self.msg_entry.insert("insert", "\n")
        return "break"

    def _send_message_event(self, event=None):
        if event and getattr(event, "keysym", "") == "Return":
            self._send_message()
            return "break"
        self._send_message()
        return "break"

    def _send_message(self):
        text = self.msg_entry.get("1.0", "end-1c").strip()
        if not text or not self.current_chat:
            return

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
    # RECEIVE LOOP
    # ──────────────────────────────────────────────────────────────────────
    def _recv_loop(self):
        try:
            while True:
                line = self._recv_line_sync()
                if line is None:
                    break
                line = line.strip()
                if line:
                    self.after(0, self._handle_server_msg, line)
        except Exception:
            pass

        self.after(0, self._system_msg, "Disconnected from server.")

    def _handle_server_msg(self, msg):
        if msg.startswith("PRIVATE_REQUEST_FROM:"):
            requester = msg.split(":", 1)[1]
            self.pending_requesters.add(requester)
            self._show_popup(
                f"🔔 {requester} wants to chat privately.",
                [("Accept", lambda r=requester: self._accept_conn(r)),
                 ("Reject", lambda r=requester: self._reject_conn(r))]
            )
            return

        if msg.startswith("PRIVATE_CONNECTED:"):
            partner = msg.split(":", 1)[1]
            self.private_partners.add(partner)
            self.pending_requesters.discard(partner)
            self._add_sidebar_item(f"private:{partner}", f"👤  {partner}", "Private chat")
            self._system_msg(f"Private chat with {partner} connected.", f"private:{partner}")
            return

        if msg.startswith("PRIVATE_REJECTED:"):
            who = msg.split(":", 1)[1]
            self._system_msg(f"{who} rejected your request.")
            return

        if msg.startswith("PRIVATE_ENDED:"):
            parts = msg.split(":", 2)
            who = parts[1] if len(parts) > 1 else "?"
            reason = parts[2] if len(parts) > 2 else "ended"
            self.private_partners.discard(who)
            self._system_msg(f"Private chat with {who} ended ({reason}).", f"private:{who}")
            self._remove_sidebar_item(f"private:{who}")
            return

        if msg.startswith("GROUP_INVITE:"):
            parts = msg.split(":", 2)
            if len(parts) == 3:
                gname, inviter = parts[1], parts[2]
                self.pending_group_invites.add(gname)
                self._show_popup(
                    f"👥 {inviter} invited you to group '{gname}'.",
                    [("Accept", lambda g=gname: self._accept_group(g)),
                     ("Decline", lambda g=gname: self._reject_group(g))]
                )
            return

        if msg.startswith("GROUP_JOINED:"):
            gname = msg.split(":", 1)[1]
            self.groups.add(gname)
            self.pending_group_invites.discard(gname)
            self._add_sidebar_item(f"group:{gname}", f"👥  {gname}", "Group chat")
            return

        if msg.startswith("[Group:"):
            try:
                bracket_end = msg.index("]")
                gname = msg[7:bracket_end]
                rest = msg[bracket_end + 2:]

                if ":" in rest:
                    sender, text = rest.split(":", 1)
                    sender = sender.strip()
                    text = text.strip()
                else:
                    sender, text = "?", rest

                key = f"group:{gname}"
                self.groups.add(gname)
                self._add_sidebar_item(key, f"👥  {gname}", "Group chat", notify=True)
                self._push_message(key, sender, text, False)
            except Exception:
                self._system_msg(msg)
            return

        if msg.startswith("[Private:"):
            try:
                bracket_end = msg.index("]")
                rest = msg[bracket_end + 2:]
                if ":" in rest:
                    sender, text = rest.split(":", 1)
                    sender = sender.strip()
                    text = text.strip()
                else:
                    sender, text = "?", rest

                key = f"private:{sender}"
                self.private_partners.add(sender)
                self._add_sidebar_item(key, f"👤  {sender}", "Private chat", notify=True)
                self._push_message(key, sender, text, False)
            except Exception:
                self._system_msg(msg)
            return

        if msg.startswith("[Offline Private]"):
            try:
                rest = msg[len("[Offline Private] "):]
                if ":" in rest:
                    sender, text = rest.split(":", 1)
                    sender = sender.strip()
                    text = text.strip()
                else:
                    sender, text = "?", rest

                key = f"private:{sender}"
                self.private_partners.add(sender)
                self._add_sidebar_item(key, f"👤  {sender}", "Private chat", notify=True)
                self._push_message(key, sender, text, False)
            except Exception:
                self._system_msg(msg)
            return

        if msg.startswith("FILE_START_FROM|"):
            parts = msg.split("|", 4)
            if len(parts) == 5:
                sender = parts[1]
                filename = parts[2]
                size_str = parts[3]
                transfer_id = parts[4]
                self.incoming_transfers[transfer_id] = {
                    "filename": os.path.basename(filename),
                    "sender": sender,
                    "size": size_str,
                    "chunks": {}
                }
            return

        if msg.startswith("FILE_CHUNK_FROM|"):
            parts = msg.split("|", 4)
            if len(parts) == 5:
                sender = parts[1]
                transfer_id = parts[2]
                seq = parts[3]
                chunk_b64 = parts[4]
                if transfer_id in self.incoming_transfers and seq.isdigit():
                    try:
                        chunk = base64.b64decode(chunk_b64.encode())
                        self.incoming_transfers[transfer_id]["chunks"][int(seq)] = chunk
                    except Exception:
                        pass
            return

        if msg.startswith("FILE_END_FROM|"):
            parts = msg.split("|", 3)
            if len(parts) == 4:
                sender = parts[1]
                transfer_id = parts[2]
                total_s = parts[3]
                if total_s.isdigit():
                    self._finalize_transfer(sender, transfer_id, int(total_s))
            return

        if msg.startswith("Groups:"):
            names = msg.split(":", 1)[1].strip()
            if names and names.lower() != "none":
                for g in [n.strip() for n in names.split(",") if n.strip()]:
                    self.groups.add(g)
                    self._add_sidebar_item(f"group:{g}", f"👥  {g}", "Group chat")
            return

        if msg.startswith("Private chats:"):
            names = msg.split(":", 1)[1].strip()
            if names and names.lower() != "none":
                for p in [n.strip() for n in names.split(",") if n.strip()]:
                    self.private_partners.add(p)
                    self._add_sidebar_item(f"private:{p}", f"👤  {p}", "Private chat")
            return

        if msg.startswith("Online clients:"):
            names = msg.split(":", 1)[1].strip()
            if names and names != "No clients online.":
                users = [u.strip() for u in names.split(",") if u.strip()]
                self.online_users = set(users)
                pretty = "\n".join(users)
                messagebox.showinfo("Online Users", pretty, parent=self)
            else:
                self.online_users = set()
                messagebox.showinfo("Online Users", "No users online.", parent=self)
            return

        if msg.startswith("INFO:"):
            info_text = msg[5:].strip()
            self._system_msg(info_text)
            return

        if ": " in msg and not msg.startswith("Online clients:"):
            sender, text = msg.split(": ", 1)
            sender = sender.strip()
            if sender != self.aliase:
                self._push_message("broadcast", sender, text, False)
            return

        if msg == "you are now connected":
            self._system_msg(msg)
            return

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
                        sender = parts[1].strip()
                        channel = parts[2].strip()

                        if channel == "PRIVATE" or channel == "FILE":
                            self.after(0, self._set_notification, f"private:{sender}")
                        elif channel == "BROADCAST":
                            self.after(0, self._set_notification, "broadcast")
                        elif channel.startswith("GROUP:"):
                            gname = channel.split(":", 1)[1].strip()
                            self.after(0, self._set_notification, f"group:{gname}")
            except Exception:
                break

    def _register_beep_port(self):
        self._safe_send(f"BEEP_UDP_PORT:{self._beep_port}")

    # ──────────────────────────────────────────────────────────────────────
    # FILE TRANSFER
    # ──────────────────────────────────────────────────────────────────────
    def _finalize_transfer(self, sender, transfer_id, total_chunks):
        transfer = self.incoming_transfers.get(transfer_id)
        if not transfer:
            return

        chunks = transfer["chunks"]
        missing = [i for i in range(total_chunks) if i not in chunks]
        if missing:
            self._system_msg(f"Incomplete file from {sender} ({len(missing)} missing chunks)")
            self.incoming_transfers.pop(transfer_id, None)
            return

        data = b"".join(chunks[i] for i in range(total_chunks))
        dl_dir = os.path.join(os.getcwd(), "downloads")
        os.makedirs(dl_dir, exist_ok=True)

        out = os.path.join(dl_dir, transfer["filename"])
        with open(out, "wb") as f:
            f.write(data)

        key = f"private:{sender}"
        self._system_msg(f"📎 File from {sender} saved: {out}", key=key)
        self.incoming_transfers.pop(transfer_id, None)

    def _send_file_to(self, target, path):
        if not os.path.isfile(path):
            self._system_msg("File not found.")
            return

        def _do():
            try:
                with open(path, "rb") as f:
                    data = f.read()

                filename = os.path.basename(path)
                tid = str(uuid.uuid4())
                chunk_size = 400
                total = (len(data) + chunk_size - 1) // chunk_size

                self._safe_send(f"FILE_START|{target}|{filename}|{len(data)}|{tid}")

                for i in range(total):
                    chunk = data[i * chunk_size:(i + 1) * chunk_size]
                    encoded = base64.b64encode(chunk).decode()
                    self._safe_send(f"FILE_CHUNK|{target}|{tid}|{i}|{encoded}")

                self._safe_send(f"FILE_END|{target}|{tid}|{total}")
                self.after(0, self._system_msg, f"📎 Sent {filename} to {target}", f"private:{target}")

            except Exception as ex:
                self.after(0, self._system_msg, f"File send error: {ex}")

        threading.Thread(target=_do, daemon=True).start()

    # ──────────────────────────────────────────────────────────────────────
    # PROMPTS / ACTIONS
    # ──────────────────────────────────────────────────────────────────────
    def _prompt_connect(self):
        name = simpledialog.askstring("Connect", "Enter username to connect to:", parent=self)
        if name:
            self._safe_send(f"connect to {name}")

    def _prompt_create_group(self):
        name = simpledialog.askstring("New Group", "Group name:", parent=self)
        if name:
            self._safe_send(f"create group {name}")

    def _prompt_invite_group(self):
        if not self.current_chat or not self.current_chat.startswith("group:"):
            messagebox.showinfo("Invite", "Open a group chat first.", parent=self)
            return

        gname = self.current_chat[6:]
        user = simpledialog.askstring("Invite", f"Invite user to '{gname}':", parent=self)
        if user:
            self._safe_send(f"invite group {gname} {user}")

    def _prompt_send_file(self):
        if not self.current_chat or not self.current_chat.startswith("private:"):
            messagebox.showinfo("Send File", "Open a private chat to send files.", parent=self)
            return

        partner = self.current_chat[8:]
        path = filedialog.askopenfilename(parent=self, title="Choose a file")
        if path:
            self._send_file_to(partner, path)

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
        if not key:
            return

        if key.startswith("private:"):
            partner = key[8:]
            self._safe_send(f"end private {partner}")

        elif key.startswith("group:"):
            messagebox.showinfo("Leave", "Group leaving is not supported by the server yet.", parent=self)

    def _logout(self):
        try:
            self._safe_send("exit")
        except Exception:
            pass
        self._on_close()

    # ──────────────────────────────────────────────────────────────────────
    # POPUP
    # ──────────────────────────────────────────────────────────────────────
    def _show_popup(self, message, buttons):
        popup = tk.Toplevel(self)
        popup.configure(bg=BG_HEADER)
        popup.title("Notification")
        popup.resizable(False, False)
        popup.grab_set()

        tk.Label(popup, text=message, font=FONT_BODY,
                 bg=BG_HEADER, fg=FG_PRIMARY,
                 wraplength=340, padx=20, pady=16).pack()

        btn_frame = tk.Frame(popup, bg=BG_HEADER, pady=10)
        btn_frame.pack()

        for label, cmd in buttons:
            color = FG_GREEN if label in ("Accept", "Join") else "#FF6B6B"

            def _action(c=cmd, p=popup):
                c()
                if p.winfo_exists():
                    p.destroy()

            RoundedButton(btn_frame, label, _action, bg=color,
                          width=100, height=32).pack(side="left", padx=8)

        popup.after(15000, lambda: popup.destroy() if popup.winfo_exists() else None)


if __name__ == "__main__":
    app = Chat77App()
    app.mainloop()