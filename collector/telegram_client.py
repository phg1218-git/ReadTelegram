# collector/telegram_client.py - Telethon 수집 로직 담당

import asyncio
import random
import threading
from datetime import datetime, timezone, timedelta
from typing import Callable

from telethon import TelegramClient
from telethon.errors import (
    UsernameNotOccupiedError,
    UsernameInvalidError,
    ChannelPrivateError,
    FloodWaitError,
)

from .utils import (
    normalize_channel_input,
    extract_links,
    sanitize_filename,
    utc_to_kst,
    now_utc,
    get_file_extension,
    classify_file_type,
)
from .storage import (
    ensure_daily_directories,
    append_jsonl,
    log_error,
)
from .rules import should_download_file
from .state_manager import StateManager

KST = timezone(timedelta(hours=9))

_DL_WAIT_MIN      = 0.5
_DL_WAIT_MAX      = 2.0
_FLOOD_ABORT_SECONDS = 300


def create_client(settings: dict) -> TelegramClient:
    """Telethon TelegramClient 를 생성해서 반환한다."""
    return TelegramClient(
        settings["session_path"],
        int(settings["api_id"]),
        settings["api_hash"],
    )


# ────────────────────────────────────────────────────────
# 레코드 빌더
# ────────────────────────────────────────────────────────

def build_message_record(message, channel_input: str, channel_name: str) -> dict:
    """Telethon 메시지 객체를 messages.jsonl 저장용 딕셔너리로 변환한다."""
    date_utc = message.date.astimezone(timezone.utc)
    date_kst = utc_to_kst(date_utc)
    text     = message.text or message.message or ""

    has_file  = message.file is not None
    file_name = None
    mime_type = None
    file_size = None
    if has_file:
        file_name = getattr(message.file, "name",      None)
        mime_type = getattr(message.file, "mime_type", None)
        file_size = getattr(message.file, "size",      None)

    return {
        "channel_input": channel_input,
        "channel_name":  channel_name,
        "message_id":    message.id,
        "date_utc":      date_utc.isoformat(),
        "date_kst":      date_kst.isoformat(),
        "text":          text,
        "links":         extract_links(text),
        "has_file":      has_file,
        "file_name":     file_name,
        "mime_type":     mime_type,
        "file_size":     file_size,
        "collected_at":  now_utc().isoformat(),
    }


def build_file_index_record(
    message,
    channel_input:   str,
    channel_name:    str,
    download_status: str,
    safe_file_name:  str | None,
    downloaded_path: str | None,
    error_message:   str | None,
) -> dict:
    """file_index.jsonl 에 저장할 파일 메타데이터 레코드를 생성한다."""
    date_utc  = message.date.astimezone(timezone.utc)
    date_kst  = utc_to_kst(date_utc)
    text      = (message.text or message.message or "")[:500]
    file_name = getattr(message.file, "name",      None)
    mime_type = getattr(message.file, "mime_type", None)
    file_size = getattr(message.file, "size",      None)
    file_ext  = get_file_extension(file_name or "", mime_type or "")

    return {
        "channel_input":   channel_input,
        "channel_name":    channel_name,
        "message_id":      message.id,
        "date_utc":        date_utc.isoformat(),
        "date_kst":        date_kst.isoformat(),
        "message_text":    text,
        "file_name":       file_name,
        "safe_file_name":  safe_file_name,
        "mime_type":       mime_type,
        "file_ext":        file_ext,
        "file_size":       file_size,
        "download_status": download_status,
        "downloaded_path": downloaded_path,
        "error_message":   error_message,
        "collected_at":    now_utc().isoformat(),
    }


# ────────────────────────────────────────────────────────
# 핵심 수집 함수
# ────────────────────────────────────────────────────────

async def collect_channel(
    client:        TelegramClient,
    channel_input: str,
    settings:      dict,
    state_manager: StateManager,
    log_callback:  Callable[[str], None] | None = None,
    stop_event:    threading.Event | None       = None,
) -> dict:
    """
    채널 하나에서 최근 LOOKBACK_HOURS 시간 이내 메시지를 수집한다.

    log_callback: GUI 로그창 출력 함수. None 이면 print() 만 사용.
    stop_event:   수집 중지 요청 플래그. 설정 시 다음 메시지 처리 전에 중단.
    """
    def _log(msg: str) -> None:
        print(msg)
        if log_callback:
            log_callback(msg)

    try:
        channel_name = normalize_channel_input(channel_input)
    except ValueError as err:
        _log(f"  [오류] 채널 주소 파싱 실패: {err}")
        return _empty_stats(channel_input, "")

    today_str = datetime.now(KST).strftime("%Y-%m-%d")
    dirs      = ensure_daily_directories(settings, today_str)
    files_dir = dirs["files_dir"]
    logs_dir  = dirs["logs_dir"]

    messages_jsonl   = dirs["day_dir"] / "messages.jsonl"
    file_index_jsonl = dirs["day_dir"] / "file_index.jsonl"

    lookback_hours = settings.get("lookback_hours", 12)
    cutoff         = now_utc() - timedelta(hours=lookback_hours)
    cutoff_kst_str = utc_to_kst(cutoff).strftime("%Y-%m-%d %H:%M:%S")
    _log(f"  수집 기준: {cutoff_kst_str} KST 이후 메시지")

    stats = _empty_stats(channel_input, channel_name)

    # ── 채널 엔티티 조회 ──────────────────────────────────
    try:
        entity = await client.get_entity(channel_name)
    except UsernameNotOccupiedError:
        _log(f"  [오류] '@{channel_name}' 채널이 존재하지 않습니다.")
        return stats
    except UsernameInvalidError:
        _log(f"  [오류] '@{channel_name}' 는 유효한 채널명이 아닙니다.")
        return stats
    except ChannelPrivateError:
        _log(f"  [오류] '@{channel_name}' 는 비공개이거나 접근 권한이 없습니다.")
        return stats
    except Exception as err:
        _log(f"  [오류] 채널 접근 실패: {err}")
        return stats

    # ── 메시지 순회 (최신 → 과거) ────────────────────────
    async for message in client.iter_messages(entity):
        # 중지 요청 확인
        if stop_event and stop_event.is_set():
            _log("  수집 중지 요청됨.")
            break

        try:
            msg_utc = message.date.astimezone(timezone.utc)

            if msg_utc < cutoff:
                break

            stats["checked_messages"] += 1

            # ── 메시지 수집 ────────────────────────────────
            is_new = not state_manager.is_message_collected(channel_name, message.id)
            if is_new:
                record = build_message_record(message, channel_input, channel_name)
                append_jsonl(messages_jsonl, record)
                state_manager.mark_message_collected(channel_name, message.id)
                stats["new_messages"] += 1
            else:
                stats["duplicate_messages"] += 1

            # ── 파일 다운로드 ──────────────────────────────
            if message.file is None:
                continue

            stats["files_found"] += 1

            file_name  = getattr(message.file, "name",      "") or ""
            mime_type  = getattr(message.file, "mime_type", "") or ""
            file_size  = getattr(message.file, "size",      None)
            file_type  = classify_file_type(file_name, mime_type)
            file_ext   = get_file_extension(file_name, mime_type)
            file_key   = StateManager.make_file_key(channel_name, message.id, file_name)
            file_state = state_manager.get_file_status(file_key)

            do_download, reason = should_download_file(message, settings, file_state)

            if not do_download:
                if reason == "already_downloaded":
                    stats["files_already_downloaded"] += 1

                elif reason == "file_too_large":
                    stats["files_too_large"] += 1
                    state_manager.update_file_status(
                        file_key, channel_name, message.id, file_name,
                        "file_too_large", mime_type=mime_type, file_size=file_size,
                    )
                    append_jsonl(file_index_jsonl, build_file_index_record(
                        message, channel_input, channel_name,
                        "file_too_large", None, None,
                        f"파일 크기 {file_size:,}B > 제한 {settings.get('max_file_size_mb', 0)}MB",
                    ))

                elif reason in ("ext_not_included", "ext_excluded"):
                    stats["files_ext_excluded"] += 1
                    append_jsonl(file_index_jsonl, build_file_index_record(
                        message, channel_input, channel_name,
                        "extension_not_allowed", None, None,
                        f"확장자 제외: {file_ext or '(알 수 없음)'}",
                    ))

                continue

            # ── 실제 다운로드 ──────────────────────────────
            if file_name:
                safe_name     = sanitize_filename(file_name)
                save_filename = f"{channel_name}_{message.id}_{safe_name}"
            else:
                save_filename = f"{channel_name}_{message.id}_{file_type}{file_ext}"

            save_path = files_dir / save_filename

            try:
                if save_path.exists():
                    _log(f"    [이미 존재] {save_filename}")
                    state_manager.update_file_status(
                        file_key, channel_name, message.id, file_name,
                        "downloaded",
                        downloaded_path=str(save_path),
                        mime_type=mime_type, file_size=file_size,
                    )
                    stats["files_already_downloaded"] += 1
                else:
                    _log(f"    [{file_type.upper()}] {save_filename}")
                    await client.download_media(message, file=str(save_path))

                    state_manager.update_file_status(
                        file_key, channel_name, message.id, file_name,
                        "downloaded",
                        downloaded_path=str(save_path),
                        mime_type=mime_type, file_size=file_size,
                    )
                    state_manager.failed_downloads.pop(file_key, None)
                    stats["files_downloaded"] += 1
                    _log(f"    [완료] → {save_path}")

                    append_jsonl(file_index_jsonl, build_file_index_record(
                        message, channel_input, channel_name,
                        "downloaded", save_filename, str(save_path), None,
                    ))

                    await asyncio.sleep(random.uniform(_DL_WAIT_MIN, _DL_WAIT_MAX))

            except Exception as err:
                error_msg = str(err)
                log_error(logs_dir, f"파일 다운로드 실패 (ID {message.id}, {file_name}): {error_msg}")
                stats["download_errors"] += 1

                state_manager.update_file_status(
                    file_key, channel_name, message.id, file_name,
                    "download_error",
                    error_message=error_msg, mime_type=mime_type, file_size=file_size,
                )
                state_manager.add_failed_download(
                    file_key, channel_name, message.id, file_name,
                    "download_error", error_msg,
                )
                append_jsonl(file_index_jsonl, build_file_index_record(
                    message, channel_input, channel_name,
                    "download_error", save_filename, None, error_msg,
                ))

        except FloodWaitError as err:
            wait = err.seconds
            _log(f"  [대기] 텔레그램 속도 제한 → {wait}초")
            if wait > _FLOOD_ABORT_SECONDS:
                _log(f"  [경고] 대기 시간({wait}초) 초과. 이 채널 수집을 중단합니다.")
                break
            await asyncio.sleep(wait)

        except OSError as err:
            log_error(logs_dir, f"파일 저장 오류 (ID {getattr(message, 'id', '?')}): {err}")
            stats["download_errors"] += 1

        except Exception as err:
            log_error(logs_dir, f"메시지 처리 오류 (ID {getattr(message, 'id', '?')}): {err}")
            stats["download_errors"] += 1

    state_manager.update_channel_stats(channel_name, channel_input, stats)
    return stats


def _empty_stats(channel_input: str, channel_name: str) -> dict:
    return {
        "channel_input":            channel_input,
        "channel_name":             channel_name,
        "checked_messages":         0,
        "new_messages":             0,
        "duplicate_messages":       0,
        "files_found":              0,
        "files_downloaded":         0,
        "files_already_downloaded": 0,
        "files_too_large":          0,
        "files_ext_excluded":       0,
        "download_errors":          0,
    }
