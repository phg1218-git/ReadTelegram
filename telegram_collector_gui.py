#!/usr/bin/env python3
# telegram_collector_gui.py - 텔레그램 수집기 GUI (CustomTkinter 현대화)

import queue
import re
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox
import tkinter as tk
import tkinter.simpledialog as sd

try:
    import customtkinter as ctk
except ImportError:
    print("[오류] customtkinter 가 설치되지 않았습니다.")
    print("  설치: pip install customtkinter")
    sys.exit(1)

from collector.gui_config import (
    load_gui_settings,
    save_gui_settings,
    validate_gui_settings,
    gui_settings_to_collect_settings,
    normalize_extensions,
    channels_text_to_list,
    channels_list_to_text,
)
from collector.gui_actions import (
    run_collect_config_channels,
    run_collect_manual_channel,
    run_test_login,
    reset_channel_download_state,
    reset_channel_all_state,
    reset_all_download_state,
    reset_all_state,
    get_state_summary,
    open_data_folder,
    open_state_folder,
)
from collector.utils import get_base_dir, normalize_channel_input

# ── CustomTkinter 테마 ────────────────────────────────────
ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")

# ── 색상 팔레트 ───────────────────────────────────────────
C_BG        = "#F6F7FB"
C_CARD      = "#FFFFFF"
C_BORDER    = "#E5E7EB"
C_TEXT      = "#111827"
C_MUTED     = "#6B7280"
C_PRIMARY   = "#2563EB"
C_PRIMARY_H = "#1D4ED8"
C_DANGER    = "#EF4444"
C_DANGER_H  = "#DC2626"
C_WARNING   = "#D97706"
C_WARNING_H = "#B45309"
C_SEC       = "#E5E7EB"
C_SEC_H     = "#D1D5DB"
C_BTN_TXT   = "#374151"

# 상태 배지 색상표
_STATUS_COLORS: dict[str, tuple[str, str]] = {
    "대기 중": ("#E5E7EB", "#6B7280"),
    "수집 중": ("#DBEAFE", "#1D4ED8"),
    "연결됨":  ("#D1FAE5", "#065F46"),
    "오류":    ("#FEE2E2", "#991B1B"),
}

# 로그 태그 색상 (터미널 bg #1E1E1E 위)
_LOG_TAG_COLORS: dict[str, str] = {
    "ERROR":   "#F87171",
    "WARNING": "#FACC15",
    "SUCCESS": "#4ADE80",
    "INFO":    "#D4D4D4",
}


# ── 공용 위젯 팩토리 ─────────────────────────────────────

def _card(parent, **kw) -> ctk.CTkFrame:
    """둥근 모서리 + 테두리가 있는 카드 프레임."""
    return ctk.CTkFrame(
        parent,
        fg_color=C_CARD,
        corner_radius=12,
        border_width=1,
        border_color=C_BORDER,
        **kw,
    )


def _hsep(parent) -> ctk.CTkFrame:
    """수평 구분선."""
    return ctk.CTkFrame(parent, fg_color=C_BORDER, height=1, corner_radius=0)


def _btn(
    parent,
    text: str,
    command,
    style: str = "secondary",
    height: int = 32,
    font_size: int = 12,
    **kw,
) -> ctk.CTkButton:
    """스타일별 CTkButton 생성 헬퍼."""
    _STYLES = {
        "primary":   (C_PRIMARY,  C_PRIMARY_H, "white"),
        "danger":    (C_DANGER,   C_DANGER_H,  "white"),
        "warning":   (C_WARNING,  C_WARNING_H, "white"),
        "secondary": (C_SEC,      C_SEC_H,     C_BTN_TXT),
    }
    fg, hover, fg_txt = _STYLES.get(style, _STYLES["secondary"])
    return ctk.CTkButton(
        parent,
        text=text,
        command=command,
        height=height,
        font=ctk.CTkFont(family="Segoe UI", size=font_size),
        fg_color=fg,
        hover_color=hover,
        text_color=fg_txt,
        corner_radius=8,
        **kw,
    )


# ────────────────────────────────────────────────────────
# 로그인 헬퍼 (워커 스레드 → 메인 스레드 입력 요청)
# ────────────────────────────────────────────────────────

class _LoginHelper:
    """워커 스레드에서 메인 스레드로 입력 요청을 전달하는 헬퍼."""

    def __init__(self, root: ctk.CTk) -> None:
        self._root   = root
        self._event  = threading.Event()
        self._result: str | None = None

    def ask(self, title: str, prompt: str, secret: bool = False) -> str:
        """워커 스레드에서 호출 — 메인 스레드에서 다이얼로그를 표시하고 입력값을 반환."""
        self._event.clear()
        self._result = None
        self._root.after(
            0, lambda t=title, p=prompt, s=secret: self._show_dialog(t, p, s)
        )
        if not self._event.wait(timeout=300):
            raise TimeoutError("입력 시간 초과 (5분)")
        if self._result is None:
            raise RuntimeError("입력이 취소됐습니다.")
        return self._result

    def _show_dialog(self, title: str, prompt: str, secret: bool) -> None:
        try:
            if secret:
                value = _ask_secret(self._root, title, prompt)
            else:
                value = sd.askstring(title, prompt, parent=self._root)
            self._result = value
        finally:
            self._event.set()


def _ask_secret(parent: ctk.CTk, title: str, prompt: str) -> str | None:
    """비밀번호 마스킹 다이얼로그 (tk.Toplevel 사용 — 스레드 안정성 우선)."""
    dialog = tk.Toplevel(parent)
    dialog.title(title)
    dialog.transient(parent)
    dialog.grab_set()
    dialog.resizable(False, False)
    result: list[str | None] = [None]

    tk.Label(dialog, text=prompt, wraplength=300).pack(padx=20, pady=(15, 5))
    entry = tk.Entry(dialog, show="*", width=35)
    entry.pack(padx=20, pady=5)
    entry.focus()

    def _ok():
        result[0] = entry.get()
        dialog.destroy()

    btn_f = tk.Frame(dialog)
    btn_f.pack(pady=(5, 15))
    tk.Button(btn_f, text="확인", command=_ok,            width=10).pack(side="left", padx=5)
    tk.Button(btn_f, text="취소", command=dialog.destroy, width=10).pack(side="left", padx=5)
    dialog.bind("<Return>", lambda e: _ok())
    dialog.bind("<Escape>", lambda e: dialog.destroy())

    parent.update_idletasks()
    x = parent.winfo_x() + (parent.winfo_width()  - 360) // 2
    y = parent.winfo_y() + (parent.winfo_height() - 160) // 2
    dialog.geometry(f"360x160+{x}+{y}")
    parent.wait_window(dialog)
    return result[0]


# ────────────────────────────────────────────────────────
# 메인 GUI 클래스
# ────────────────────────────────────────────────────────

class TelegramCollectorGUI(ctk.CTk):

    def __init__(self) -> None:
        super().__init__()
        self.title("Telegram Collector")
        self.geometry("1720x1040")
        self.minsize(1100, 720)
        self.configure(fg_color=C_BG)

        self._log_queue:      queue.Queue             = queue.Queue()
        self._stop_event:     threading.Event         = threading.Event()
        self._collect_thread: threading.Thread | None = None

        # ── tkinter 변수 ──────────────────────────────
        self._var_api_id         = tk.StringVar()
        self._var_api_hash       = tk.StringVar()
        self._var_show_hash      = tk.BooleanVar(value=False)
        self._var_lookback       = tk.StringVar(value="12")
        self._var_allow_all_ext  = tk.BooleanVar(value=True)
        self._var_extensions     = tk.StringVar()
        self._var_max_size       = tk.StringVar(value="0")
        self._var_keep_days      = tk.StringVar(value="30")
        self._var_collect_mode   = tk.StringVar(value="config")
        self._var_manual_channel = tk.StringVar()
        self._var_save_path      = tk.StringVar()

        self._build_layout()
        self._start_log_processor()
        self.on_load_settings()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ────────────────────────────────────────────────────
    # 레이아웃 골격
    # ────────────────────────────────────────────────────

    def _build_layout(self) -> None:
        self.grid_rowconfigure(0, weight=0)   # 헤더
        self.grid_rowconfigure(1, weight=3)   # 본문 (설정 | 우측)
        self.grid_rowconfigure(2, weight=2)   # 로그
        self.grid_columnconfigure(0, weight=1)

        self.build_header()
        self._build_content()
        self.build_log_card()

    # ────────────────────────────────────────────────────
    # [Header] 앱 이름 + 상태 배지
    # ────────────────────────────────────────────────────

    def build_header(self) -> None:
        hdr = ctk.CTkFrame(
            self, fg_color=C_CARD, corner_radius=0,
            border_width=1, border_color=C_BORDER,
        )
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.grid_columnconfigure(1, weight=1)

        # 좌측: 아이콘 + 타이틀
        left = ctk.CTkFrame(hdr, fg_color="transparent")
        left.grid(row=0, column=0, sticky="w", padx=20, pady=14)

        ctk.CTkLabel(
            left, text="✈",
            font=ctk.CTkFont(size=20),
            text_color=C_PRIMARY,
            fg_color="#DBEAFE",
            corner_radius=16,
            width=36, height=36,
        ).pack(side="left", padx=(0, 14))

        title_col = ctk.CTkFrame(left, fg_color="transparent")
        title_col.pack(side="left")
        ctk.CTkLabel(
            title_col, text="Telegram Collector",
            font=ctk.CTkFont(family="Segoe UI", size=17, weight="bold"),
            text_color=C_TEXT,
        ).pack(anchor="w")
        ctk.CTkLabel(
            title_col,
            text="공개 채널/그룹의 메시지와 첨부파일을 수집합니다.",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=C_MUTED,
        ).pack(anchor="w")

        # 우측: 상태 배지
        right = ctk.CTkFrame(hdr, fg_color="transparent")
        right.grid(row=0, column=2, sticky="e", padx=20, pady=14)

        ctk.CTkLabel(
            right, text="상태",
            font=ctk.CTkFont(family="Segoe UI", size=10),
            text_color=C_MUTED,
        ).pack(anchor="e")

        self._status_badge = ctk.CTkLabel(
            right, text="  대기 중  ",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            fg_color="#E5E7EB",
            text_color="#6B7280",
            corner_radius=10,
        )
        self._status_badge.pack(anchor="e", pady=(3, 0))

    # ────────────────────────────────────────────────────
    # 본문 컨테이너 (설정 카드 + 우측 패널)
    # ────────────────────────────────────────────────────

    def _build_content(self) -> None:
        content = ctk.CTkFrame(self, fg_color=C_BG)
        content.grid(row=1, column=0, sticky="nsew", padx=16, pady=(12, 0))
        content.grid_columnconfigure(0, weight=1)
        content.grid_columnconfigure(1, weight=0, minsize=400)
        content.grid_rowconfigure(0, weight=1)

        self.build_settings_card(content).grid(
            row=0, column=0, sticky="nsew", padx=(0, 8)
        )

        right = ctk.CTkFrame(content, fg_color=C_BG)
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_rowconfigure(0, weight=0)
        right.grid_rowconfigure(1, weight=0)
        right.grid_columnconfigure(0, weight=1)

        self.build_reset_card(right).grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.build_collect_card(right).grid(row=1, column=0, sticky="ew")

    # ────────────────────────────────────────────────────
    # [1] 환경설정 카드
    # ────────────────────────────────────────────────────

    def build_settings_card(self, parent) -> ctk.CTkFrame:
        card = _card(parent)

        ctk.CTkLabel(
            card, text="환경설정",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color=C_TEXT,
        ).pack(anchor="w", padx=20, pady=(18, 0))

        g = ctk.CTkFrame(card, fg_color="transparent")
        g.pack(fill="both", expand=True, padx=20, pady=(10, 0))
        g.grid_columnconfigure(1, weight=1)
        g.grid_rowconfigure(3, weight=1)   # 채널 목록 영역 세로 확장

        FLBL = ctk.CTkFont(family="Segoe UI", size=12)
        FENT = ctk.CTkFont(family="Segoe UI", size=12)
        LW   = 112

        def _lbl(row: int, text: str, anchor: str = "e"):
            ctk.CTkLabel(
                g, text=text, font=FLBL,
                text_color=C_MUTED, anchor=anchor, width=LW,
            ).grid(row=row, column=0, sticky=anchor, padx=(0, 10), pady=4)

        def _ent(row: int, var: tk.Variable, **kw) -> ctk.CTkEntry:
            e = ctk.CTkEntry(
                g, textvariable=var, font=FENT,
                height=32, border_color=C_BORDER, **kw,
            )
            e.grid(row=row, column=1, sticky="ew", pady=4)
            return e

        # API ID
        _lbl(0, "API ID")
        _ent(0, self._var_api_id)

        # API Hash + 표시 체크박스
        _lbl(1, "API Hash")
        hash_row = ctk.CTkFrame(g, fg_color="transparent")
        hash_row.grid(row=1, column=1, sticky="ew", pady=4)
        hash_row.grid_columnconfigure(0, weight=1)

        self._entry_hash = ctk.CTkEntry(
            hash_row, textvariable=self._var_api_hash,
            show="*", font=FENT, height=32, border_color=C_BORDER,
        )
        self._entry_hash.grid(row=0, column=0, sticky="ew")

        ctk.CTkCheckBox(
            hash_row, text="표시",
            variable=self._var_show_hash,
            command=self._on_toggle_hash,
            font=FLBL, text_color=C_MUTED,
            checkbox_width=18, checkbox_height=18,
        ).grid(row=0, column=1, padx=(10, 0))

        # 수집 시간 범위
        _lbl(2, "수집 시간")
        time_row = ctk.CTkFrame(g, fg_color="transparent")
        time_row.grid(row=2, column=1, sticky="w", pady=4)
        ctk.CTkEntry(
            time_row, textvariable=self._var_lookback,
            width=80, font=FENT, height=32, border_color=C_BORDER,
        ).pack(side="left")
        ctk.CTkLabel(
            time_row, text=" 시간", font=FLBL, text_color=C_MUTED,
        ).pack(side="left")

        # 채널 목록 (tk.Text 유지 — 스크롤·태그 완전 지원)
        ctk.CTkLabel(
            g, text="채널 목록", font=FLBL,
            text_color=C_MUTED, anchor="ne", width=LW,
        ).grid(row=3, column=0, sticky="ne", padx=(0, 10), pady=(8, 4))

        ch_wrap = ctk.CTkFrame(
            g, fg_color=C_CARD, corner_radius=8,
            border_width=1, border_color=C_BORDER,
        )
        ch_wrap.grid(row=3, column=1, sticky="nsew", pady=4)

        self._channels_text = tk.Text(
            ch_wrap, height=5, wrap="none",
            font=("Segoe UI", 10), bg=C_CARD, fg=C_TEXT,
            relief="flat", bd=0, padx=6, pady=6,
            insertbackground=C_TEXT,
        )
        ch_sb = tk.Scrollbar(ch_wrap, command=self._channels_text.yview)
        self._channels_text.configure(yscrollcommand=ch_sb.set)
        self._channels_text.pack(side="left", fill="both", expand=True)
        ch_sb.pack(side="right", fill="y")

        ctk.CTkLabel(
            g, text="(한 줄에 채널 하나)",
            font=ctk.CTkFont(size=10), text_color=C_MUTED,
        ).grid(row=4, column=1, sticky="w")

        # 허용 확장자
        _lbl(5, "허용 확장자")
        ext_row = ctk.CTkFrame(g, fg_color="transparent")
        ext_row.grid(row=5, column=1, sticky="ew", pady=4)
        ext_row.grid_columnconfigure(0, weight=1)

        self._entry_ext = ctk.CTkEntry(
            ext_row, textvariable=self._var_extensions,
            font=FENT, height=32, border_color=C_BORDER,
        )
        self._entry_ext.grid(row=0, column=0, sticky="ew")

        ctk.CTkCheckBox(
            ext_row, text="전체 허용",
            variable=self._var_allow_all_ext,
            command=self._on_toggle_ext,
            font=FLBL, text_color=C_MUTED,
            checkbox_width=18, checkbox_height=18,
        ).grid(row=0, column=1, padx=(10, 0))

        # 최대 파일 크기
        _lbl(6, "최대 파일 크기")
        sz_row = ctk.CTkFrame(g, fg_color="transparent")
        sz_row.grid(row=6, column=1, sticky="w", pady=4)
        ctk.CTkEntry(
            sz_row, textvariable=self._var_max_size,
            width=80, font=FENT, height=32, border_color=C_BORDER,
        ).pack(side="left")
        ctk.CTkLabel(
            sz_row, text=" MB  (0 = 제한 없음)", font=FLBL, text_color=C_MUTED,
        ).pack(side="left")

        # 파일 보관 기간
        _lbl(7, "파일 보관 기간")
        kd_row = ctk.CTkFrame(g, fg_color="transparent")
        kd_row.grid(row=7, column=1, sticky="w", pady=4)
        ctk.CTkEntry(
            kd_row, textvariable=self._var_keep_days,
            width=80, font=FENT, height=32, border_color=C_BORDER,
        ).pack(side="left")
        ctk.CTkLabel(
            kd_row, text=" 일  (cleanup_files.py 에서 사용)", font=FLBL, text_color=C_MUTED,
        ).pack(side="left")

        # 저장 경로
        _lbl(8, "저장 경로")
        path_row = ctk.CTkFrame(g, fg_color="transparent")
        path_row.grid(row=8, column=1, sticky="ew", pady=4)
        path_row.grid_columnconfigure(0, weight=1)

        self._entry_save_path = ctk.CTkEntry(
            path_row, textvariable=self._var_save_path,
            font=FENT, height=32, border_color=C_BORDER,
            placeholder_text="저장 폴더를 선택해주세요...",
        )
        self._entry_save_path.grid(row=0, column=0, sticky="ew")

        _btn(path_row, "📁 찾아보기", self._on_browse_save_path,
             "secondary", height=32).grid(row=0, column=1, padx=(6, 0))
        _btn(path_row, "열기", self._on_open_save_path,
             "secondary", height=32).grid(row=0, column=2, padx=(4, 0))

        # 구분선
        _hsep(g).grid(row=9, column=0, columnspan=2, sticky="ew", pady=10)

        # 버튼 영역
        btn_area = ctk.CTkFrame(g, fg_color="transparent")
        btn_area.grid(row=10, column=0, columnspan=2, sticky="ew", pady=(0, 16))

        for text, cmd in [
            ("설정 불러오기", self.on_load_settings),
            ("설정 저장",     self.on_save_settings),
            ("설정 테스트",   self.on_test_settings),
        ]:
            _btn(btn_area, text, cmd).pack(side="left", padx=(0, 6))

        _btn(
            btn_area, "Telegram 로그인/연결 테스트",
            self.on_test_connection, style="primary",
        ).pack(side="left", padx=(6, 0))

        return card

    # ────────────────────────────────────────────────────
    # [2] 상태 초기화 카드
    # ────────────────────────────────────────────────────

    def build_reset_card(self, parent) -> ctk.CTkFrame:
        card = _card(parent)

        ctk.CTkLabel(
            card, text="상태 초기화",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color=C_TEXT,
        ).pack(anchor="w", padx=20, pady=(18, 0))

        ctk.CTkLabel(
            card,
            text="실제 파일은 삭제하지 않고 수집/다운로드 기록만 초기화합니다.",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=C_MUTED, wraplength=360, justify="left",
        ).pack(anchor="w", padx=20, pady=(4, 10))

        # 채널 선택 콤보박스
        combo_row = ctk.CTkFrame(card, fg_color="transparent")
        combo_row.pack(fill="x", padx=20, pady=(0, 12))
        ctk.CTkLabel(
            combo_row, text="채널:",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=C_MUTED,
        ).pack(side="left")
        self._channel_combo = ctk.CTkComboBox(
            combo_row, values=[""],
            font=ctk.CTkFont(family="Segoe UI", size=12),
            height=32, border_color=C_BORDER,
        )
        self._channel_combo.pack(side="left", padx=(8, 0), fill="x", expand=True)

        # 버튼 2열 그리드
        bg = ctk.CTkFrame(card, fg_color="transparent")
        bg.pack(fill="x", padx=20, pady=(0, 18))
        bg.grid_columnconfigure(0, weight=1)
        bg.grid_columnconfigure(1, weight=1)

        _btn(bg, "채널 다운로드 초기화", self.on_reset_channel_download,
             "secondary", height=34, font_size=11).grid(
            row=0, column=0, sticky="ew", padx=(0, 4), pady=(0, 6))

        _btn(bg, "채널 전체 초기화", self.on_reset_channel_all,
             "warning", height=34, font_size=11).grid(
            row=0, column=1, sticky="ew", padx=(4, 0), pady=(0, 6))

        _btn(bg, "전체 다운로드 초기화", self.on_reset_all_download,
             "warning", height=34, font_size=11).grid(
            row=1, column=0, sticky="ew", padx=(0, 4), pady=(0, 6))

        _btn(bg, "전체 수집 초기화", self.on_reset_all_state,
             "danger", height=34, font_size=11).grid(
            row=1, column=1, sticky="ew", padx=(4, 0), pady=(0, 6))

        _btn(bg, "상태 요약", self.on_show_status,
             "secondary", height=30, font_size=11).grid(
            row=2, column=0, sticky="ew", padx=(0, 4))

        return card

    # ────────────────────────────────────────────────────
    # [3] 데이터 수집 카드
    # ────────────────────────────────────────────────────

    def build_collect_card(self, parent) -> ctk.CTkFrame:
        card = _card(parent)

        ctk.CTkLabel(
            card, text="데이터 수집",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color=C_TEXT,
        ).pack(anchor="w", padx=20, pady=(18, 0))

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=20, pady=(10, 18))

        # 수집 모드 라디오
        mode_row = ctk.CTkFrame(inner, fg_color="transparent")
        mode_row.pack(fill="x", pady=(0, 8))
        for text, val in [
            ("환경설정 채널 전체 수집", "config"),
            ("직접 입력 채널",          "manual"),
        ]:
            ctk.CTkRadioButton(
                mode_row, text=text,
                variable=self._var_collect_mode, value=val,
                command=self._on_toggle_collect_mode,
                font=ctk.CTkFont(family="Segoe UI", size=12),
                text_color=C_TEXT,
            ).pack(side="left", padx=(0, 18))

        # 직접 입력 채널 엔트리
        manual_row = ctk.CTkFrame(inner, fg_color="transparent")
        manual_row.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(
            manual_row, text="채널:",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=C_MUTED,
        ).pack(side="left")
        self._entry_manual = ctk.CTkEntry(
            manual_row, textvariable=self._var_manual_channel,
            font=ctk.CTkFont(family="Segoe UI", size=12),
            height=32, border_color=C_BORDER,
        )
        self._entry_manual.pack(side="left", padx=(8, 0), fill="x", expand=True)

        _hsep(inner).pack(fill="x", pady=8)

        # ▶ 수집 시작 (Primary — 가장 눈에 띄게)
        self._btn_start = ctk.CTkButton(
            inner, text="▶  수집 시작",
            command=self.on_start_collect, height=44,
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            fg_color=C_PRIMARY, hover_color=C_PRIMARY_H,
            text_color="white", corner_radius=10,
        )
        self._btn_start.pack(fill="x", pady=(0, 6))

        # ■ 수집 중지
        self._btn_stop = ctk.CTkButton(
            inner, text="■  수집 중지",
            command=self.on_stop_collect, height=34,
            font=ctk.CTkFont(family="Segoe UI", size=12),
            fg_color=C_SEC, hover_color=C_SEC_H,
            text_color=C_BTN_TXT, corner_radius=8, state="disabled",
        )
        self._btn_stop.pack(fill="x")

        _hsep(inner).pack(fill="x", pady=10)

        # 진행률 표시
        self._progress_bar = ctk.CTkProgressBar(
            inner, mode="determinate",
            fg_color="#E5E7EB", progress_color=C_PRIMARY,
            corner_radius=4, height=8,
        )
        self._progress_bar.pack(fill="x", pady=(0, 6))
        self._progress_bar.set(0)

        self._progress_label = ctk.CTkLabel(
            inner,
            text="현재 채널: -   |   다운로드: -   |   진행률: 0%",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=C_MUTED, anchor="w",
        )
        self._progress_label.pack(anchor="w")

        _hsep(inner).pack(fill="x", pady=10)

        # 폴더 열기 버튼
        folder_row = ctk.CTkFrame(inner, fg_color="transparent")
        folder_row.pack(fill="x")
        for text, cmd in [
            ("저장 폴더 열기", self.on_open_data_folder),
            ("상태 폴더 열기", self.on_open_state_folder),
        ]:
            _btn(folder_row, text, cmd, height=30).pack(side="left", padx=(0, 6))

        self._on_toggle_collect_mode()
        return card

    # ────────────────────────────────────────────────────
    # [4] 실행 로그 카드
    # ────────────────────────────────────────────────────

    def build_log_card(self) -> None:
        card = _card(self)
        card.grid(row=2, column=0, sticky="nsew", padx=16, pady=(8, 16))

        # 헤더 행
        hdr_row = ctk.CTkFrame(card, fg_color="transparent")
        hdr_row.pack(fill="x", padx=20, pady=(16, 0))

        ctk.CTkLabel(
            hdr_row, text="실행 로그",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color=C_TEXT,
        ).pack(side="left")

        for text, cmd in [("로그 저장", self.on_save_log), ("로그 지우기", self.on_clear_log)]:
            _btn(hdr_row, text, cmd, height=28).pack(side="right", padx=(6, 0))

        # 다크 터미널 배경 프레임
        log_outer = ctk.CTkFrame(card, fg_color="#1E1E1E", corner_radius=8)
        log_outer.pack(fill="both", expand=True, padx=20, pady=(10, 16))
        log_outer.grid_columnconfigure(0, weight=1)
        log_outer.grid_rowconfigure(0, weight=1)

        self._log_text = tk.Text(
            log_outer, state="disabled", wrap="none",
            font=("Consolas", 9), bg="#1E1E1E", fg="#D4D4D4",
            insertbackground="white", relief="flat", bd=0, padx=8, pady=6,
        )
        log_sb_y = tk.Scrollbar(log_outer, command=self._log_text.yview)
        log_sb_x = tk.Scrollbar(log_outer, orient="horizontal",
                                 command=self._log_text.xview)
        self._log_text.configure(
            yscrollcommand=log_sb_y.set, xscrollcommand=log_sb_x.set,
        )
        self._log_text.grid(row=0, column=0, sticky="nsew")
        log_sb_y.grid(row=0, column=1, sticky="ns")
        log_sb_x.grid(row=1, column=0, sticky="ew")

        for tag, color in _LOG_TAG_COLORS.items():
            self._log_text.tag_configure(tag, foreground=color)

    # ────────────────────────────────────────────────────
    # 상태 배지 / 진행률 업데이트
    # ────────────────────────────────────────────────────

    def update_status(self, status: str) -> None:
        bg, fg = _STATUS_COLORS.get(status, ("#E5E7EB", "#6B7280"))
        self._status_badge.configure(
            text=f"  {status}  ", fg_color=bg, text_color=fg,
        )

    def update_progress(self, value: float, label: str = "") -> None:
        self._progress_bar.set(max(0.0, min(1.0, value)))
        if label:
            self._progress_label.configure(text=label)

    # ────────────────────────────────────────────────────
    # 이벤트 핸들러 — 환경설정
    # ────────────────────────────────────────────────────

    def on_load_settings(self) -> None:
        settings = load_gui_settings()
        self._var_api_id.set(str(settings.get("api_id", "")))
        self._var_api_hash.set(str(settings.get("api_hash", "")))
        self._var_lookback.set(str(settings.get("lookback_hours", 12)))

        self._channels_text.delete("1.0", tk.END)
        self._channels_text.insert(
            "1.0", channels_list_to_text(settings.get("channels", []))
        )

        allow_all = settings.get("allow_all_extensions", True)
        self._var_allow_all_ext.set(allow_all)
        self._var_extensions.set(", ".join(settings.get("allowed_extensions", [])))
        self._on_toggle_ext()

        self._var_max_size.set(str(settings.get("max_file_size_mb", 0)))
        self._var_keep_days.set(str(settings.get("keep_original_file_days", 30)))
        self._var_save_path.set(str(settings.get("save_path", "")))

        self._update_channel_combobox()
        self.log("설정 불러오기 완료")

    def on_save_settings(self, *, silent: bool = False) -> bool:
        settings = self._get_gui_settings()
        errors   = validate_gui_settings(settings)

        if errors:
            messagebox.showerror("저장 실패", "\n".join(errors))
            self.log("[오류] 설정 저장 실패: " + " / ".join(errors))
            return False

        try:
            save_gui_settings(settings)
            self._update_channel_combobox()
            self.log("설정 저장 완료")
            if not silent:
                messagebox.showinfo("저장 완료", "설정이 저장됐습니다.")
            return True
        except Exception as err:
            messagebox.showerror("저장 오류", str(err))
            self.log(f"[오류] 설정 저장 오류: {err}")
            return False

    def on_test_settings(self) -> None:
        settings = self._get_gui_settings()
        errors   = validate_gui_settings(settings)

        if errors:
            messagebox.showwarning(
                "설정 테스트",
                "설정 검사 결과 — 오류 발견:\n\n" + "\n".join(f"• {e}" for e in errors),
            )
            self.log("[경고] 설정 테스트 실패: " + " / ".join(errors))
        else:
            info_lines = [
                f"API ID     : {settings['api_id']}",
                f"API Hash   : {'*' * min(len(settings['api_hash']), 8)}... ({len(settings['api_hash'])}자)",
                f"수집 시간  : {settings['lookback_hours']}시간",
                f"채널 수    : {len(settings['channels'])}개",
                f"허용 확장자: {'모두 허용' if settings['allow_all_extensions'] else ', '.join(settings['allowed_extensions']) or '없음'}",
                f"최대 크기  : {'제한 없음' if not settings['max_file_size_mb'] else str(settings['max_file_size_mb']) + ' MB'}",
                f"보관 기간  : {settings['keep_original_file_days']}일",
            ]
            self.log("설정 테스트 통과:\n  " + "\n  ".join(info_lines))
            messagebox.showinfo(
                "설정 테스트",
                "설정에 문제가 없습니다.\n\n" + "\n".join(info_lines),
            )

    def on_test_connection(self) -> None:
        if self._collect_thread and self._collect_thread.is_alive():
            messagebox.showwarning("경고", "수집 중에는 연결 테스트를 할 수 없습니다.")
            return

        if not self.on_save_settings(silent=True):
            return

        base_dir = get_base_dir()
        session  = Path(str(base_dir / "telegram_session") + ".session")
        if not session.exists():
            self.log("세션 파일이 없습니다. 로그인 절차를 시작합니다.")
            self.log("팝업에 전화번호 → 인증코드 → (필요 시) 2FA 비밀번호를 입력하세요.")
        else:
            self.log("세션 파일이 존재합니다. 연결 상태를 확인합니다.")

        settings = gui_settings_to_collect_settings(self._get_gui_settings())
        helper   = _LoginHelper(self)

        t = threading.Thread(
            target=run_test_login,
            args=(
                settings,
                lambda: helper.ask("전화번호 입력", "국가코드 포함 전화번호\n예: +821012345678"),
                lambda: helper.ask("인증코드 입력", "텔레그램으로 받은 인증코드"),
                lambda: helper.ask("2FA 비밀번호", "2단계 인증 비밀번호", secret=True),
                self._thread_log,
            ),
            daemon=True,
        )
        t.start()

    # ────────────────────────────────────────────────────
    # 이벤트 핸들러 — 상태 초기화
    # ────────────────────────────────────────────────────

    def _get_selected_channel(self) -> str | None:
        ch = self._channel_combo.get().strip()
        if not ch:
            messagebox.showwarning("채널 미선택", "채널을 선택하거나 직접 입력하세요.")
            return None
        try:
            return normalize_channel_input(ch)
        except ValueError:
            return ch

    def on_reset_channel_download(self) -> None:
        ch = self._get_selected_channel()
        if not ch:
            return
        if not messagebox.askyesno(
            "확인",
            f"'{ch}' 채널의 다운로드 상태만 초기화합니다.\n"
            "메시지 수집 이력은 유지됩니다.\n실제 파일은 삭제하지 않습니다.\n\n계속할까요?",
        ):
            return
        try:
            self.log(reset_channel_download_state(ch, get_base_dir() / "state"))
        except Exception as err:
            self.log(f"[오류] {err}")

    def on_reset_channel_all(self) -> None:
        ch = self._get_selected_channel()
        if not ch:
            return
        if not messagebox.askyesno(
            "확인",
            f"'{ch}' 채널의 메시지·파일·통계 상태를 전부 초기화합니다.\n"
            "실제 파일은 삭제하지 않습니다.\n\n계속할까요?",
        ):
            return
        try:
            self.log(reset_channel_all_state(ch, get_base_dir() / "state"))
        except Exception as err:
            self.log(f"[오류] {err}")

    def on_reset_all_download(self) -> None:
        if not messagebox.askyesno(
            "확인",
            "모든 채널의 파일 다운로드 상태를 초기화합니다.\n"
            "메시지 수집 이력은 유지됩니다.\n실제 파일은 삭제하지 않습니다.\n\n계속할까요?",
        ):
            return
        try:
            self.log(reset_all_download_state(get_base_dir() / "state"))
        except Exception as err:
            self.log(f"[오류] {err}")

    def on_reset_all_state(self) -> None:
        if not messagebox.askyesno(
            "전체 초기화 확인",
            "전체 수집/다운로드 상태 기록을 초기화합니다.\n"
            "다음 수집 시 기존 메시지·파일을 다시 처리할 수 있습니다.\n"
            "실제 파일은 삭제하지 않습니다.\n\n정말 계속할까요?",
            icon="warning",
        ):
            return
        try:
            self.log(reset_all_state(get_base_dir() / "state"))
        except Exception as err:
            self.log(f"[오류] {err}")

    def on_show_status(self) -> None:
        try:
            summary = get_state_summary(get_base_dir() / "state")
            self.log("── 상태 요약 ──\n" + summary + "\n──────────────")
        except Exception as err:
            self.log(f"[오류] 상태 요약 실패: {err}")

    # ────────────────────────────────────────────────────
    # 이벤트 핸들러 — 수집
    # ────────────────────────────────────────────────────

    def on_start_collect(self) -> None:
        if self._collect_thread and self._collect_thread.is_alive():
            messagebox.showwarning("경고", "이미 수집 중입니다.")
            return

        if not self.on_save_settings(silent=True):
            return

        if not self._var_save_path.get().strip():
            messagebox.showerror(
                "저장 경로 미설정",
                "환경설정에서 저장 경로를 먼저 선택해주세요.\n"
                "'저장 경로' 항목의 '📁 찾아보기' 버튼을 클릭하세요.",
            )
            return

        base_dir = get_base_dir()
        session  = Path(str(base_dir / "telegram_session") + ".session")
        if not session.exists():
            messagebox.showwarning(
                "로그인 필요",
                "세션 파일이 없습니다.\n"
                "'Telegram 로그인/연결 테스트' 버튼으로 먼저 로그인해 주세요.",
            )
            return

        gui_s     = self._get_gui_settings()
        collect_s = gui_settings_to_collect_settings(gui_s)

        if self._var_collect_mode.get() == "manual":
            ch_input = self._var_manual_channel.get().strip()
            if not ch_input:
                messagebox.showerror("오류", "수집할 채널 주소를 입력하세요.")
                return
            target = lambda: run_collect_manual_channel(
                ch_input, collect_s, self._thread_log, self._stop_event
            )
            self.log(f"수집 시작: {ch_input}")
        else:
            if not collect_s.get("channels"):
                messagebox.showerror("오류", "환경설정에 채널이 없습니다.")
                return
            target = lambda: run_collect_config_channels(
                collect_s, self._thread_log, self._stop_event
            )
            self.log(
                f"수집 시작: 최근 {collect_s['lookback_hours']}시간 / "
                f"채널 {len(collect_s['channels'])}개"
            )

        self._stop_event.clear()
        self._collect_thread = threading.Thread(target=target, daemon=True)
        self._collect_thread.start()

        self._btn_start.configure(state="disabled")
        self._btn_stop.configure(state="normal")
        self.update_status("수집 중")
        self._progress_bar.configure(mode="indeterminate")
        self._progress_bar.start()
        self._progress_label.configure(text="수집 준비 중...")
        self._poll_collect_thread()

    def on_stop_collect(self) -> None:
        self._stop_event.set()
        self.log("사용자 요청으로 수집 중지 예약됨. 현재 작업 완료 후 중지됩니다.")

    def on_open_data_folder(self) -> None:
        open_data_folder(get_base_dir() / "data")

    def on_open_state_folder(self) -> None:
        open_state_folder(get_base_dir() / "state")

    def _poll_collect_thread(self) -> None:
        if self._collect_thread and self._collect_thread.is_alive():
            self.after(500, self._poll_collect_thread)
        else:
            self._btn_start.configure(state="normal")
            self._btn_stop.configure(state="disabled")
            self.update_status("대기 중")
            self._progress_bar.stop()
            self._progress_bar.configure(mode="determinate")
            self._progress_bar.set(0)
            self._progress_label.configure(
                text="현재 채널: -   |   다운로드: -   |   진행률: 0%"
            )

    # ────────────────────────────────────────────────────
    # 이벤트 핸들러 — 로그
    # ────────────────────────────────────────────────────

    def on_clear_log(self) -> None:
        self._log_text.config(state="normal")
        self._log_text.delete("1.0", tk.END)
        self._log_text.config(state="disabled")

    def on_save_log(self) -> None:
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("텍스트 파일", "*.txt"), ("모든 파일", "*.*")],
            initialfile=f"collector_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
        )
        if not path:
            return
        content = self._log_text.get("1.0", tk.END)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            self.log(f"로그 저장됨: {path}")
        except OSError as err:
            messagebox.showerror("저장 오류", str(err))

    # ────────────────────────────────────────────────────
    # 로그 출력
    # ────────────────────────────────────────────────────

    def log(self, msg: str) -> None:
        """메인 스레드에서 로그창에 메시지 출력."""
        ts   = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}\n"
        tag  = _log_tag(msg)

        self._log_text.config(state="normal")
        self._log_text.insert(tk.END, line, tag)
        self._log_text.see(tk.END)
        self._log_text.config(state="disabled")

        self._parse_progress_hint(msg)

    def _thread_log(self, msg: str) -> None:
        """워커 스레드에서 호출 — 큐에 메시지를 넣는다."""
        self._log_queue.put(msg)

    def _start_log_processor(self) -> None:
        def _process() -> None:
            while not self._log_queue.empty():
                try:
                    self.log(self._log_queue.get_nowait())
                except queue.Empty:
                    break
            self.after(100, _process)
        self.after(100, _process)

    def _parse_progress_hint(self, msg: str) -> None:
        """로그 메시지에서 채널 진행 정보를 파싱해 진행률 레이블 갱신."""
        m = re.match(r'\[(\d+)/(\d+)\]\s+(\S+)\s+수집', msg)
        if m:
            self._progress_label.configure(
                text=f"수집 중: {m.group(3)}   ({m.group(1)}/{m.group(2)} 채널)"
            )

    # ────────────────────────────────────────────────────
    # 내부 헬퍼
    # ────────────────────────────────────────────────────

    def _get_gui_settings(self) -> dict:
        channels_text = self._channels_text.get("1.0", tk.END).strip()
        allow_all     = self._var_allow_all_ext.get()

        def _int(var: tk.Variable, default: int) -> int:
            try:
                return int(var.get() or default)
            except ValueError:
                return default

        return {
            "api_id":                  self._var_api_id.get().strip(),
            "api_hash":                self._var_api_hash.get().strip(),
            "lookback_hours":          _int(self._var_lookback, 12),
            "channels":                channels_text_to_list(channels_text),
            "allow_all_extensions":    allow_all,
            "allowed_extensions":      (
                [] if allow_all
                else normalize_extensions(self._var_extensions.get())
            ),
            "max_file_size_mb":        _int(self._var_max_size, 0),
            "keep_original_file_days": _int(self._var_keep_days, 30),
            "download_file_types":     "all",
            "save_path":               self._var_save_path.get().strip(),
        }

    def _update_channel_combobox(self) -> None:
        channels = channels_text_to_list(self._channels_text.get("1.0", tk.END))
        names: list[str] = []
        for ch in channels:
            try:
                names.append(normalize_channel_input(ch))
            except ValueError:
                names.append(ch)
        self._channel_combo.configure(values=names if names else [""])
        if names:
            self._channel_combo.set(names[0])
        else:
            self._channel_combo.set("")

    def _on_browse_save_path(self) -> None:
        """저장 폴더 선택 다이얼로그."""
        current = self._var_save_path.get().strip()
        initial = current if current and Path(current).exists() else None
        folder  = filedialog.askdirectory(title="저장 폴더 선택", initialdir=initial)
        if folder:
            self._var_save_path.set(folder)
            self.on_save_settings(silent=True)
            self.log(f"저장 경로 설정: {folder}")

    def _on_open_save_path(self) -> None:
        """저장 폴더를 탐색기로 열기."""
        import subprocess
        path_str = self._var_save_path.get().strip()
        if not path_str:
            messagebox.showwarning("저장 경로 없음", "먼저 저장 경로를 선택해주세요.")
            return
        p = Path(path_str)
        if not p.exists():
            if messagebox.askyesno("폴더 없음", f"'{path_str}'\n폴더가 없습니다. 생성할까요?"):
                p.mkdir(parents=True, exist_ok=True)
            else:
                return
        subprocess.Popen(["explorer", str(p)])

    def _on_toggle_hash(self) -> None:
        self._entry_hash.configure(show="" if self._var_show_hash.get() else "*")

    def _on_toggle_ext(self) -> None:
        self._entry_ext.configure(
            state="disabled" if self._var_allow_all_ext.get() else "normal"
        )

    def _on_toggle_collect_mode(self) -> None:
        self._entry_manual.configure(
            state="normal" if self._var_collect_mode.get() == "manual" else "disabled"
        )

    def _on_close(self) -> None:
        if self._collect_thread and self._collect_thread.is_alive():
            if not messagebox.askyesno(
                "종료 확인",
                "수집이 진행 중입니다. 종료하면 수집이 중단됩니다.\n종료할까요?",
            ):
                return
            self._stop_event.set()
        self.destroy()


# ────────────────────────────────────────────────────────
# 로그 태그 결정 (모듈 수준 순수 함수)
# ────────────────────────────────────────────────────────

def _log_tag(msg: str) -> str:
    if "[오류]" in msg or "[치명적 오류]" in msg:
        return "ERROR"
    if "[경고]" in msg:
        return "WARNING"
    if any(k in msg for k in ("완료", "성공", "통과", "✓", "저장됨")):
        return "SUCCESS"
    return "INFO"


# ────────────────────────────────────────────────────────
# 오류 로깅 (--noconsole exe 빌드 대응)
# ────────────────────────────────────────────────────────

def _setup_error_logging() -> None:
    base_dir = get_base_dir()
    log_dir  = base_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "gui_error.log"

    original_hook = sys.excepthook

    def _hook(exc_type, exc_val, exc_tb):
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"\n[{datetime.now()}] 미처리 예외:\n")
            traceback.print_exception(exc_type, exc_val, exc_tb, file=f)
        original_hook(exc_type, exc_val, exc_tb)

    sys.excepthook = _hook

    if getattr(sys, "frozen", False) and sys.stderr is None:
        sys.stderr = open(log_path, "a", encoding="utf-8")


# ────────────────────────────────────────────────────────
# 진입점
# ────────────────────────────────────────────────────────

def main() -> None:
    _setup_error_logging()
    try:
        app = TelegramCollectorGUI()
        app.mainloop()
    except Exception as err:
        base_dir = get_base_dir()
        log_path = base_dir / "logs" / "gui_error.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"\n[{datetime.now()}] 시작 오류:\n")
            traceback.print_exc(file=f)
        try:
            messagebox.showerror(
                "시작 오류",
                f"프로그램 시작 중 오류가 발생했습니다:\n{err}\n\n"
                f"logs/gui_error.log 를 확인하세요.",
            )
        except Exception:
            pass


if __name__ == "__main__":
    main()
