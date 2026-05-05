#!/usr/bin/env python3
# telegram_collector_gui.py - 텔레그램 수집기 GUI 메인

import queue
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox
import tkinter as tk
import tkinter.ttk as ttk

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


# ────────────────────────────────────────────────────────
# 로그인 헬퍼 (워커 스레드 → 메인 스레드 입력 요청)
# ────────────────────────────────────────────────────────

class _LoginHelper:
    """워커 스레드에서 메인 스레드로 입력 요청을 전달하는 헬퍼."""

    def __init__(self, root: tk.Tk) -> None:
        self._root   = root
        self._event  = threading.Event()
        self._result: str | None = None

    def ask(self, title: str, prompt: str, secret: bool = False) -> str:
        """워커 스레드에서 호출. 메인 스레드에서 다이얼로그를 표시하고 입력값을 반환."""
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
                import tkinter.simpledialog as sd
                value = sd.askstring(title, prompt, parent=self._root)
            self._result = value
        finally:
            self._event.set()


def _ask_secret(parent: tk.Tk, title: str, prompt: str) -> str | None:
    """비밀번호 마스킹 다이얼로그."""
    dialog  = tk.Toplevel(parent)
    dialog.title(title)
    dialog.transient(parent)
    dialog.grab_set()
    dialog.resizable(False, False)
    result  = [None]

    ttk.Label(dialog, text=prompt, wraplength=300).pack(padx=20, pady=(15, 5))
    entry = ttk.Entry(dialog, show="*", width=35)
    entry.pack(padx=20, pady=5)
    entry.focus()

    def _ok():
        result[0] = entry.get()
        dialog.destroy()

    btn_f = ttk.Frame(dialog)
    btn_f.pack(pady=(5, 15))
    ttk.Button(btn_f, text="확인", command=_ok,            width=10).pack(side="left", padx=5)
    ttk.Button(btn_f, text="취소", command=dialog.destroy, width=10).pack(side="left", padx=5)
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

class TelegramCollectorGUI(tk.Tk):

    def __init__(self) -> None:
        super().__init__()
        self.title("Telegram Collector")
        self.geometry("920x780")
        self.minsize(820, 660)

        self._log_queue:     queue.Queue = queue.Queue()
        self._stop_event:    threading.Event = threading.Event()
        self._collect_thread: threading.Thread | None = None

        # ── tkinter 변수 ──────────────────────────────────
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

        self.create_widgets()
        self._start_log_processor()
        self.on_load_settings()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ────────────────────────────────────────────────────
    # UI 구성
    # ────────────────────────────────────────────────────

    def create_widgets(self) -> None:
        # 제목
        title_f = ttk.Frame(self)
        title_f.pack(fill="x", padx=8, pady=(8, 0))
        ttk.Label(
            title_f, text="텔레그램 자료 수집기",
            font=("", 14, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            title_f,
            text="공개 채널/그룹의 메시지와 첨부파일을 수집합니다. "
                 "본인이 접근 가능한 채널만 사용하세요.",
            foreground="#555",
        ).pack(anchor="w")
        ttk.Separator(self).pack(fill="x", padx=8, pady=6)

        # 콘텐츠 영역 (설정 ← | → 초기화 + 수집)
        content_f = ttk.Frame(self)
        content_f.pack(fill="x", padx=8)

        self.create_settings_frame(content_f).pack(
            side="left", fill="both", expand=True, padx=(0, 6)
        )

        right_f = ttk.Frame(content_f)
        right_f.pack(side="right", fill="both")
        self.create_reset_frame(right_f).pack(fill="x", pady=(0, 6))
        self.create_collect_frame(right_f).pack(fill="x")

        ttk.Separator(self).pack(fill="x", padx=8, pady=6)

        # 로그 영역 (나머지 공간 전부)
        self.create_log_frame(self).pack(
            fill="both", expand=True, padx=8, pady=(0, 8)
        )

    # ── [1] 환경설정 ──────────────────────────────────────

    def create_settings_frame(self, parent) -> ttk.LabelFrame:
        lf = ttk.LabelFrame(parent, text="환경설정", padding=8)

        def row(r, label, widget_factory, extra=None):
            ttk.Label(lf, text=label, width=13, anchor="e").grid(
                row=r, column=0, sticky="e", pady=3, padx=(0, 4)
            )
            w = widget_factory(lf)
            w.grid(row=r, column=1, sticky="ew", pady=3,
                   columnspan=2 if extra is None else 1)
            if extra:
                extra(lf).grid(row=r, column=2, sticky="w", padx=(4, 0))

        lf.columnconfigure(1, weight=1)

        # API ID
        row(0, "API ID",
            lambda p: ttk.Entry(p, textvariable=self._var_api_id, width=20))

        # API Hash + 표시 토글
        self._entry_hash = ttk.Entry(
            lf, textvariable=self._var_api_hash, show="*", width=32
        )
        ttk.Label(lf, text="API Hash", width=13, anchor="e").grid(
            row=1, column=0, sticky="e", pady=3, padx=(0, 4)
        )
        self._entry_hash.grid(row=1, column=1, sticky="ew", pady=3)
        ttk.Checkbutton(
            lf, text="표시", variable=self._var_show_hash,
            command=self._on_toggle_hash,
        ).grid(row=1, column=2, sticky="w", padx=(4, 0))

        # 수집 시간 범위
        ttk.Label(lf, text="수집 시간", width=13, anchor="e").grid(
            row=2, column=0, sticky="e", pady=3, padx=(0, 4)
        )
        hr_f = ttk.Frame(lf)
        hr_f.grid(row=2, column=1, sticky="w", pady=3, columnspan=2)
        ttk.Spinbox(
            hr_f, from_=1, to=720, textvariable=self._var_lookback, width=6
        ).pack(side="left")
        ttk.Label(hr_f, text=" 시간").pack(side="left")

        # 채널 목록
        ttk.Label(lf, text="채널 목록", width=13, anchor="ne").grid(
            row=3, column=0, sticky="ne", pady=3, padx=(0, 4)
        )
        ch_f = ttk.Frame(lf)
        ch_f.grid(row=3, column=1, sticky="nsew", pady=3, columnspan=2)
        ch_f.columnconfigure(0, weight=1)
        self._channels_text = tk.Text(ch_f, height=5, width=32, wrap="none")
        ch_sb = ttk.Scrollbar(ch_f, command=self._channels_text.yview)
        self._channels_text.config(yscrollcommand=ch_sb.set)
        self._channels_text.grid(row=0, column=0, sticky="nsew")
        ch_sb.grid(row=0, column=1, sticky="ns")
        ttk.Label(ch_f, text="(한 줄에 채널 하나)", foreground="#888",
                  font=("", 8)).grid(row=1, column=0, sticky="w")
        lf.rowconfigure(3, weight=1)

        # 허용 확장자
        ttk.Label(lf, text="허용 확장자", width=13, anchor="e").grid(
            row=4, column=0, sticky="e", pady=3, padx=(0, 4)
        )
        ext_f = ttk.Frame(lf)
        ext_f.grid(row=4, column=1, sticky="ew", pady=3, columnspan=2)
        self._entry_ext = ttk.Entry(
            ext_f, textvariable=self._var_extensions, width=24
        )
        self._entry_ext.pack(side="left", fill="x", expand=True)
        ttk.Checkbutton(
            ext_f, text="전체 허용", variable=self._var_allow_all_ext,
            command=self._on_toggle_ext,
        ).pack(side="left", padx=(6, 0))

        # 최대 파일 크기
        ttk.Label(lf, text="최대 파일 크기", width=13, anchor="e").grid(
            row=5, column=0, sticky="e", pady=3, padx=(0, 4)
        )
        sz_f = ttk.Frame(lf)
        sz_f.grid(row=5, column=1, sticky="w", pady=3, columnspan=2)
        ttk.Entry(sz_f, textvariable=self._var_max_size, width=7).pack(side="left")
        ttk.Label(sz_f, text=" MB  (0 = 제한 없음)", foreground="#666").pack(side="left")

        # 파일 보관 기간
        ttk.Label(lf, text="파일 보관 기간", width=13, anchor="e").grid(
            row=6, column=0, sticky="e", pady=3, padx=(0, 4)
        )
        kd_f = ttk.Frame(lf)
        kd_f.grid(row=6, column=1, sticky="w", pady=3, columnspan=2)
        ttk.Entry(kd_f, textvariable=self._var_keep_days, width=7).pack(side="left")
        ttk.Label(kd_f, text=" 일  (cleanup_files.py 에서 사용)", foreground="#666").pack(side="left")

        ttk.Separator(lf).grid(row=7, column=0, columnspan=3, sticky="ew", pady=6)

        # 버튼 행 1
        btn1 = ttk.Frame(lf)
        btn1.grid(row=8, column=0, columnspan=3, sticky="ew")
        for text, cmd in [
            ("설정 불러오기",  self.on_load_settings),
            ("설정 저장",      self.on_save_settings),
            ("설정 테스트",    self.on_test_settings),
        ]:
            ttk.Button(btn1, text=text, command=cmd, width=12).pack(
                side="left", padx=2
            )

        # 버튼 행 2
        btn2 = ttk.Frame(lf)
        btn2.grid(row=9, column=0, columnspan=3, sticky="ew", pady=(4, 0))
        ttk.Button(
            btn2, text="Telegram 로그인/연결 테스트",
            command=self.on_test_connection, width=28,
        ).pack(side="left", padx=2)

        return lf

    # ── [2] 상태 초기화 ───────────────────────────────────

    def create_reset_frame(self, parent) -> ttk.LabelFrame:
        lf = ttk.LabelFrame(parent, text="상태 초기화", padding=8)

        ttk.Label(
            lf,
            text="초기화는 실제 파일을 삭제하지 않고 수집/다운로드 기록만 초기화합니다.",
            wraplength=320, foreground="#555", font=("", 8),
        ).pack(anchor="w", pady=(0, 6))

        # 채널 선택
        ch_f = ttk.Frame(lf)
        ch_f.pack(fill="x", pady=(0, 6))
        ttk.Label(ch_f, text="채널:").pack(side="left")
        self._channel_combo = ttk.Combobox(ch_f, width=22)
        self._channel_combo.pack(side="left", padx=(4, 0))

        # 버튼 행 1
        row1 = ttk.Frame(lf)
        row1.pack(fill="x", pady=2)
        ttk.Button(
            row1, text="선택 채널 다운로드 초기화",
            command=self.on_reset_channel_download, width=22,
        ).pack(side="left", padx=(0, 4))
        ttk.Button(
            row1, text="선택 채널 전체 초기화",
            command=self.on_reset_channel_all, width=18,
        ).pack(side="left")

        # 버튼 행 2
        row2 = ttk.Frame(lf)
        row2.pack(fill="x", pady=2)
        ttk.Button(
            row2, text="전체 다운로드 초기화",
            command=self.on_reset_all_download, width=18,
        ).pack(side="left", padx=(0, 4))
        ttk.Button(
            row2, text="전체 수집 초기화",
            command=self.on_reset_all_state, width=14,
        ).pack(side="left", padx=(0, 4))
        ttk.Button(
            row2, text="상태 요약",
            command=self.on_show_status, width=8,
        ).pack(side="left")

        return lf

    # ── [3] 데이터 수집 ───────────────────────────────────

    def create_collect_frame(self, parent) -> ttk.LabelFrame:
        lf = ttk.LabelFrame(parent, text="데이터 수집", padding=8)

        # 수집 방식 RadioButton
        mode_f = ttk.Frame(lf)
        mode_f.pack(anchor="w")
        ttk.Radiobutton(
            mode_f, text="환경설정 채널 전체 수집",
            variable=self._var_collect_mode, value="config",
            command=self._on_toggle_collect_mode,
        ).pack(side="left")
        ttk.Radiobutton(
            mode_f, text="직접 입력 채널",
            variable=self._var_collect_mode, value="manual",
            command=self._on_toggle_collect_mode,
        ).pack(side="left", padx=(12, 0))

        # 직접 입력 채널 Entry
        manual_f = ttk.Frame(lf)
        manual_f.pack(fill="x", pady=4)
        ttk.Label(manual_f, text="채널:").pack(side="left")
        self._entry_manual = ttk.Entry(
            manual_f, textvariable=self._var_manual_channel, width=26
        )
        self._entry_manual.pack(side="left", padx=(4, 0), fill="x", expand=True)

        ttk.Separator(lf).pack(fill="x", pady=4)

        # 버튼 행 1
        row1 = ttk.Frame(lf)
        row1.pack(fill="x", pady=2)
        self._btn_start = ttk.Button(
            row1, text="▶  수집 시작", command=self.on_start_collect, width=14
        )
        self._btn_start.pack(side="left", padx=(0, 4))
        self._btn_stop = ttk.Button(
            row1, text="■  수집 중지", command=self.on_stop_collect,
            width=14, state="disabled"
        )
        self._btn_stop.pack(side="left")

        # 버튼 행 2
        row2 = ttk.Frame(lf)
        row2.pack(fill="x", pady=2)
        ttk.Button(
            row2, text="저장 폴더 열기",
            command=self.on_open_data_folder, width=14,
        ).pack(side="left", padx=(0, 4))
        ttk.Button(
            row2, text="상태 폴더 열기",
            command=self.on_open_state_folder, width=14,
        ).pack(side="left")

        self._on_toggle_collect_mode()
        return lf

    # ── [4] 실행 로그 ─────────────────────────────────────

    def create_log_frame(self, parent) -> ttk.LabelFrame:
        lf = ttk.LabelFrame(parent, text="실행 로그", padding=8)

        log_f = ttk.Frame(lf)
        log_f.pack(fill="both", expand=True)
        log_f.columnconfigure(0, weight=1)
        log_f.rowconfigure(0, weight=1)

        self._log_text = tk.Text(
            log_f, state="disabled", wrap="none",
            font=("Consolas", 9), bg="#1e1e1e", fg="#d4d4d4",
            insertbackground="white",
        )
        log_sb_y = ttk.Scrollbar(log_f, command=self._log_text.yview)
        log_sb_x = ttk.Scrollbar(log_f, orient="horizontal",
                                  command=self._log_text.xview)
        self._log_text.configure(
            yscrollcommand=log_sb_y.set, xscrollcommand=log_sb_x.set
        )
        self._log_text.grid(row=0, column=0, sticky="nsew")
        log_sb_y.grid(row=0, column=1, sticky="ns")
        log_sb_x.grid(row=1, column=0, sticky="ew")

        btn_f = ttk.Frame(lf)
        btn_f.pack(fill="x", pady=(6, 0))
        ttk.Button(btn_f, text="로그 지우기",
                   command=self.on_clear_log, width=12).pack(side="left", padx=(0, 4))
        ttk.Button(btn_f, text="로그 저장",
                   command=self.on_save_log, width=10).pack(side="left")

        return lf

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
        self._var_extensions.set(
            ", ".join(settings.get("allowed_extensions", []))
        )
        self._on_toggle_ext()

        self._var_max_size.set(str(settings.get("max_file_size_mb", 0)))
        self._var_keep_days.set(str(settings.get("keep_original_file_days", 30)))

        self._update_channel_combobox()
        self.log("설정 불러오기 완료")

    def on_save_settings(self, *, silent: bool = False) -> bool:
        """설정을 저장한다. silent=True 이면 성공 팝업을 띄우지 않는다."""
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
            result = "설정 검사 결과 — 오류 발견:\n\n" + "\n".join(f"• {e}" for e in errors)
            messagebox.showwarning("설정 테스트", result)
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
            messagebox.showinfo("설정 테스트", "설정에 문제가 없습니다.\n\n" + "\n".join(info_lines))

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
            msg = reset_channel_download_state(ch, get_base_dir() / "state")
            self.log(msg)
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
            msg = reset_channel_all_state(ch, get_base_dir() / "state")
            self.log(msg)
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
            msg = reset_all_download_state(get_base_dir() / "state")
            self.log(msg)
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
            msg = reset_all_state(get_base_dir() / "state")
            self.log(msg)
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

        base_dir = get_base_dir()
        session  = Path(str(base_dir / "telegram_session") + ".session")
        if not session.exists():
            messagebox.showwarning(
                "로그인 필요",
                "세션 파일이 없습니다.\n"
                "'Telegram 로그인/연결 테스트' 버튼으로 먼저 로그인해 주세요.",
            )
            return

        gui_s    = self._get_gui_settings()
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
            self.log(f"수집 시작: 최근 {collect_s['lookback_hours']}시간 / "
                     f"채널 {len(collect_s['channels'])}개")

        self._stop_event.clear()
        self._collect_thread = threading.Thread(target=target, daemon=True)
        self._collect_thread.start()

        self._btn_start.config(state="disabled")
        self._btn_stop.config(state="normal")
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
            self._btn_start.config(state="normal")
            self._btn_stop.config(state="disabled")

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
        """메인 스레드에서 로그창에 메시지를 출력한다."""
        ts   = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}\n"
        self._log_text.config(state="normal")
        self._log_text.insert(tk.END, line)
        self._log_text.see(tk.END)
        self._log_text.config(state="disabled")

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

    # ────────────────────────────────────────────────────
    # 내부 헬퍼
    # ────────────────────────────────────────────────────

    def _get_gui_settings(self) -> dict:
        channels_text = self._channels_text.get("1.0", tk.END).strip()
        allow_all     = self._var_allow_all_ext.get()

        try:
            lookback = int(self._var_lookback.get() or 12)
        except ValueError:
            lookback = 12
        try:
            max_size = int(self._var_max_size.get() or 0)
        except ValueError:
            max_size = 0
        try:
            keep_days = int(self._var_keep_days.get() or 30)
        except ValueError:
            keep_days = 30

        return {
            "api_id":                  self._var_api_id.get().strip(),
            "api_hash":                self._var_api_hash.get().strip(),
            "lookback_hours":          lookback,
            "channels":                channels_text_to_list(channels_text),
            "allow_all_extensions":    allow_all,
            "allowed_extensions":      (
                [] if allow_all
                else normalize_extensions(self._var_extensions.get())
            ),
            "max_file_size_mb":        max_size,
            "keep_original_file_days": keep_days,
            "download_file_types":     "all",
        }

    def _update_channel_combobox(self) -> None:
        channels = channels_text_to_list(
            self._channels_text.get("1.0", tk.END)
        )
        names = []
        for ch in channels:
            try:
                names.append(normalize_channel_input(ch))
            except ValueError:
                names.append(ch)
        self._channel_combo["values"] = names
        if names and not self._channel_combo.get():
            self._channel_combo.set(names[0])

    def _on_toggle_hash(self) -> None:
        self._entry_hash.config(show="" if self._var_show_hash.get() else "*")

    def _on_toggle_ext(self) -> None:
        state = "disabled" if self._var_allow_all_ext.get() else "normal"
        self._entry_ext.config(state=state)

    def _on_toggle_collect_mode(self) -> None:
        state = "normal" if self._var_collect_mode.get() == "manual" else "disabled"
        self._entry_manual.config(state=state)

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

    # --noconsole 빌드에서 stderr 가 없으면 파일로 리다이렉트
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
