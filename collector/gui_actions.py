# collector/gui_actions.py - GUI 버튼 동작에서 사용할 비즈니스 로직 모음

import asyncio
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable

from .state_manager import StateManager
from .storage import ensure_base_directories
from .telegram_client import create_client, collect_channel
from .utils import normalize_channel_input


# ── 수집 실행 ────────────────────────────────────────────

def run_collect_config_channels(
    settings:     dict,
    log_callback: Callable[[str], None],
    stop_event:   threading.Event,
) -> None:
    """설정 채널 전체 수집. 별도 스레드에서 호출한다."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(
            _async_collect_config(settings, log_callback, stop_event)
        )
    finally:
        loop.close()


async def _async_collect_config(
    settings:     dict,
    log_callback: Callable,
    stop_event:   threading.Event,
) -> None:
    channels = settings.get("channels", [])
    if not channels:
        log_callback("[오류] 채널 목록이 없습니다. 환경설정에서 채널을 추가해 주세요.")
        return

    ensure_base_directories(settings)
    state_manager = StateManager(settings["state_dir"])
    state_manager.migrate_old_state_if_needed()
    state_manager.load_all()

    client = create_client(settings)
    total  = len(channels)

    try:
        await client.start()
        me       = await client.get_me()
        name_str = me.first_name or ""
        user_str = f"@{me.username}" if me.username else "(username 없음)"
        log_callback(f"로그인 계정: {name_str} {user_str}")

        for idx, ch in enumerate(channels, 1):
            if stop_event.is_set():
                log_callback("사용자 요청으로 수집 중지됨.")
                break

            log_callback(f"[{idx}/{total}] {ch} 수집 중...")
            try:
                stats = await collect_channel(
                    client, ch, settings, state_manager,
                    log_callback=log_callback, stop_event=stop_event,
                )
                _log_channel_stats(stats, log_callback)
            except Exception as err:
                log_callback(f"  [오류] {ch}: {err}")

        state_manager.save_all()
        if not stop_event.is_set():
            log_callback("전체 수집 완료.")

    except Exception as err:
        log_callback(f"[치명적 오류] {err}")
    finally:
        await client.disconnect()
        log_callback("연결 종료.")


def run_collect_manual_channel(
    channel_input: str,
    settings:      dict,
    log_callback:  Callable[[str], None],
    stop_event:    threading.Event,
) -> None:
    """단일 채널 수집. 별도 스레드에서 호출한다."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(
            _async_collect_manual(channel_input, settings, log_callback, stop_event)
        )
    finally:
        loop.close()


async def _async_collect_manual(
    channel_input: str,
    settings:      dict,
    log_callback:  Callable,
    stop_event:    threading.Event,
) -> None:
    try:
        normalize_channel_input(channel_input)
    except ValueError as err:
        log_callback(f"[오류] 채널 주소 파싱 실패: {err}")
        return

    ensure_base_directories(settings)
    state_manager = StateManager(settings["state_dir"])
    state_manager.migrate_old_state_if_needed()
    state_manager.load_all()

    client = create_client(settings)

    try:
        await client.start()
        me       = await client.get_me()
        name_str = me.first_name or ""
        user_str = f"@{me.username}" if me.username else "(username 없음)"
        log_callback(f"로그인 계정: {name_str} {user_str}")
        log_callback(f"{channel_input} 수집 중...")

        stats = await collect_channel(
            client, channel_input, settings, state_manager,
            log_callback=log_callback, stop_event=stop_event,
        )
        _log_channel_stats(stats, log_callback)
        state_manager.save_all()

        if not stop_event.is_set():
            log_callback("수집 완료.")

    except Exception as err:
        log_callback(f"[치명적 오류] {err}")
    finally:
        await client.disconnect()
        log_callback("연결 종료.")


def _log_channel_stats(stats: dict, log_callback: Callable) -> None:
    ch = stats.get("channel_name") or stats.get("channel_input", "")
    log_callback(
        f"  {ch}: 검사 {stats.get('checked_messages', 0):,}건 "
        f"/ 신규 {stats.get('new_messages', 0):,}건 "
        f"/ 파일발견 {stats.get('files_found', 0):,}건 "
        f"/ 다운로드 {stats.get('files_downloaded', 0):,}건"
        + (f" / 오류 {stats.get('download_errors', 0):,}건"
           if stats.get("download_errors", 0) else "")
    )


# ── Telegram 로그인 테스트 ────────────────────────────────

def run_test_login(
    settings:         dict,
    phone_callback:   Callable[[], str],
    code_callback:    Callable[[], str],
    password_callback: Callable[[], str],
    log_callback:     Callable[[str], None],
) -> None:
    """Telegram 로그인 테스트. 별도 스레드에서 호출한다."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(
            _async_test_login(
                settings, phone_callback, code_callback,
                password_callback, log_callback,
            )
        )
    finally:
        loop.close()


async def _async_test_login(
    settings:         dict,
    phone_callback:   Callable,
    code_callback:    Callable,
    password_callback: Callable,
    log_callback:     Callable,
) -> None:
    client = create_client(settings)
    try:
        await client.start(
            phone=phone_callback,
            code_callback=code_callback,
            password=password_callback,
        )
        me       = await client.get_me()
        name_str = me.first_name or ""
        user_str = f"@{me.username}" if me.username else "(username 없음)"
        log_callback(f"✓ 로그인 성공: {name_str} {user_str}")
        log_callback("세션 파일이 저장됐습니다. 이후 수집 시 자동 로그인됩니다.")
    except RuntimeError as err:
        log_callback(f"로그인 취소됨: {err}")
    except Exception as err:
        log_callback(f"[오류] 연결 실패: {err}")
    finally:
        await client.disconnect()


# ── 상태 초기화 ──────────────────────────────────────────

def reset_channel_download_state(channel_name: str, state_dir: Path) -> str:
    """선택 채널의 파일 다운로드 상태만 초기화한다. (메시지 이력 유지)"""
    sm = StateManager(state_dir)
    sm.load_all()

    file_keys = [k for k in sm.files_state     if k.startswith(f"{channel_name}:")]
    fail_keys = [k for k in sm.failed_downloads if k.startswith(f"{channel_name}:")]

    for k in file_keys:
        del sm.files_state[k]
    for k in fail_keys:
        del sm.failed_downloads[k]

    sm.save_all()
    return f"'{channel_name}' 다운로드 상태 초기화 완료 ({len(file_keys)}건 삭제)"


def reset_channel_all_state(channel_name: str, state_dir: Path) -> str:
    """선택 채널의 메시지·파일·실패·통계 전체 상태를 초기화한다."""
    sm = StateManager(state_dir)
    sm.load_all()
    sm.reset_channel(channel_name)
    sm.save_all()
    return f"'{channel_name}' 전체 상태 초기화 완료"


def reset_all_download_state(state_dir: Path) -> str:
    """모든 채널의 파일 다운로드 상태만 초기화한다. (메시지 이력 유지)"""
    sm = StateManager(state_dir)
    sm.load_all()
    count = len(sm.files_state)
    sm.files_state.clear()
    sm.failed_downloads.clear()
    sm.save_all()
    return f"전체 다운로드 상태 초기화 완료 ({count}건 삭제)"


def reset_all_state(state_dir: Path) -> str:
    """모든 수집·다운로드 상태를 초기화한다."""
    sm = StateManager(state_dir)
    sm.load_all()
    sm.reset_all()
    sm.save_all()
    return "전체 수집/다운로드 상태 초기화 완료"


# ── 상태 요약 ────────────────────────────────────────────

def get_state_summary(state_dir: Path) -> str:
    """상태 요약 문자열을 반환한다."""
    sm = StateManager(state_dir)
    sm.load_all()

    total_msgs = sum(
        len(v.get("collected_message_ids", set()))
        for v in sm.messages_state.values()
    )
    dl_ok      = sum(1 for v in sm.files_state.values() if v.get("status") == "downloaded")
    dl_fail    = sum(1 for v in sm.files_state.values() if v.get("status") == "download_error")
    missing    = len(sm.find_missing_files())
    failed_cnt = len(sm.failed_downloads)

    lines = [
        f"채널 수          : {len(sm.channels_state)}개",
        f"수집 메시지      : {total_msgs:,}건",
        f"다운로드 완료    : {dl_ok:,}건",
        f"다운로드 실패    : {dl_fail:,}건",
        f"파일 불일치      : {missing}건",
        f"재시도 대기      : {failed_cnt}건",
    ]

    if sm.channels_state:
        lines.append("")
        lines.append("── 채널별 마지막 수집 ──")
        for ch, entry in sorted(sm.channels_state.items()):
            last = (
                entry.get("last_collected_at", "")[:19]
                if entry.get("last_collected_at") else "-"
            )
            new_msgs = entry.get("total_new_messages", 0)
            lines.append(f"  {ch:<30} {last}  (신규 누적 {new_msgs:,}건)")

    return "\n".join(lines)


# ── 폴더 열기 ────────────────────────────────────────────

def open_data_folder(data_dir: Path) -> None:
    """data 폴더를 Windows 탐색기로 연다."""
    data_dir.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(["explorer", str(data_dir)])


def open_state_folder(state_dir: Path) -> None:
    """state 폴더를 Windows 탐색기로 연다."""
    state_dir.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(["explorer", str(state_dir)])
