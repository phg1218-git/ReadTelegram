#!/usr/bin/env python3
# collect_config_channels.py
# .env 에 미리 등록된 텔레그램 채널들을 한 번에 순서대로 수집한다.
# 사용법: python collect_config_channels.py

import asyncio
import sys
from pathlib import Path

from collector.config import load_settings, get_configured_channels, get_lookback_hours
from collector.storage import ensure_base_directories
from collector.state_manager import StateManager
from collector.telegram_client import create_client, collect_channel


async def async_main() -> None:

    # ── 1) 설정 로드 ───────────────────────────────────────
    settings = load_settings()
    channels = get_configured_channels(settings)
    lookback = get_lookback_hours(settings)

    if not channels:
        print("\n[오류] .env 파일에 TELEGRAM_CHANNELS 가 설정되지 않았습니다.")
        print("  예시 (쉼표로 여러 채널 구분):")
        print("    TELEGRAM_CHANNELS=https://t.me/channel_a,@channel_b,channel_c")
        sys.exit(1)

    total = len(channels)

    # ── 2) 기본 디렉토리 생성 ─────────────────────────────
    ensure_base_directories(settings)

    # ── 3) 상태 로드 ─────────────────────────────────────
    state_manager = StateManager(settings["state_dir"])
    state_manager.migrate_old_state_if_needed()
    state_manager.load_all()

    print("\n" + "=" * 55)
    print("  텔레그램 고정 채널 일괄 수집 시작")
    print(f"  수집 기준: 최근 {lookback}시간")
    print(f"  대상 채널 수: {total}개")
    print("=" * 55)

    # ── 4) 클라이언트 생성 및 수집 ───────────────────────
    all_stats = []
    client    = create_client(settings)

    try:
        await client.start()
        me       = await client.get_me()
        name_str = me.first_name or ''
        user_str = f"@{me.username}" if me.username else "(username 없음)"
        print(f"  로그인 계정: {name_str} {user_str}\n")

        for idx, ch in enumerate(channels, start=1):
            print(f"\n[{idx}/{total}] {ch} 수집 중...")
            try:
                stats = await collect_channel(client, ch, settings, state_manager)
            except Exception as err:
                print(f"  [오류] 수집 중 예외 발생: {err}")
                stats = _failed_stats(ch)

            all_stats.append(stats)
            _print_channel_stats(stats)

        # ── 5) 상태 저장 ──────────────────────────────────
        state_manager.save_all()

    except KeyboardInterrupt:
        print("\n\n  Ctrl+C 로 중단됐습니다.")
        state_manager.save_all()

    except Exception as err:
        print(f"\n[치명적 오류] {err}")
        import traceback
        traceback.print_exc()

    finally:
        await client.disconnect()
        print("\n  연결 종료.")

    # ── 6) 전체 요약 ──────────────────────────────────────
    _print_total_stats(all_stats)

    if settings.get("keep_console_open", True):
        input("\n  Enter 를 누르면 종료합니다...")


def _print_channel_stats(stats: dict) -> None:
    """채널별 수집 결과를 출력한다."""
    skipped = (
        stats.get("files_already_downloaded", 0) +
        stats.get("files_too_large", 0)
    )
    print(f"  검사 메시지    : {stats.get('checked_messages', 0):,}건")
    print(f"  신규 메시지    : {stats.get('new_messages', 0):,}건")
    print(f"  파일 발견      : {stats.get('files_found', 0):,}건")
    print(f"  파일 다운로드  : {stats.get('files_downloaded', 0):,}건")
    print(f"  파일 건너뜀    : {skipped:,}건")
    if stats.get("download_errors", 0):
        print(f"  다운로드 오류  : {stats.get('download_errors', 0):,}건")


def _print_total_stats(all_stats: list) -> None:
    """전체 채널 합산 통계를 출력한다."""
    keys = [
        "checked_messages", "new_messages", "duplicate_messages",
        "files_found", "files_downloaded",
        "files_already_downloaded", "files_too_large", "download_errors",
    ]
    totals = {k: sum(s.get(k, 0) for s in all_stats) for k in keys}

    print("\n" + "=" * 55)
    print("  전체 수집 완료")
    print("=" * 55)
    print(f"  전체 검사 메시지    : {totals['checked_messages']:,}건")
    print(f"  전체 신규 메시지    : {totals['new_messages']:,}건")
    print(f"  전체 파일 발견      : {totals['files_found']:,}건")
    print(f"  전체 파일 다운로드  : {totals['files_downloaded']:,}건")
    print(f"  전체 다운로드 오류  : {totals['download_errors']:,}건")
    print("=" * 55)


def _failed_stats(channel_input: str) -> dict:
    """채널 수집 자체가 예외로 실패했을 때의 기본 통계를 반환한다."""
    return {
        "channel_input":          channel_input,
        "channel_name":           "",
        "checked_messages":       0,
        "new_messages":           0,
        "duplicate_messages":     0,
        "files_found":            0,
        "files_downloaded":       0,
        "files_already_downloaded": 0,
        "files_too_large":        0,
        "download_errors":        1,
    }


def main() -> None:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
