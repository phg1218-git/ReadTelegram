#!/usr/bin/env python3
# collect_manual_channel.py
# 실행 시 직접 주소를 입력해서 채널 1개를 수집한다.
# 사용법: python collect_manual_channel.py

import asyncio
import sys

from collector.config import load_settings, get_lookback_hours
from collector.storage import ensure_base_directories
from collector.state_manager import StateManager
from collector.telegram_client import create_client, collect_channel
from collector.utils import normalize_channel_input


async def async_main() -> None:

    # ── 1) 설정 로드 ───────────────────────────────────────
    settings = load_settings()
    lookback = get_lookback_hours(settings)

    # ── 2) 기본 디렉토리 생성 ─────────────────────────────
    ensure_base_directories(settings)

    # ── 3) 사용자 입력 ───────────────────────────────────
    print("\n" + "=" * 55)
    print("  텔레그램 수동 채널 수집")
    print("=" * 55)

    raw_input_str = input("\n수집할 텔레그램 방 주소를 입력하세요: ").strip()

    if not raw_input_str:
        print("[오류] 주소를 입력해야 합니다.")
        sys.exit(1)

    try:
        channel_name = normalize_channel_input(raw_input_str)
    except ValueError as err:
        print(f"[오류] {err}")
        sys.exit(1)

    # ── 4) 상태 로드 ─────────────────────────────────────
    state_manager = StateManager(settings["state_dir"])
    state_manager.migrate_old_state_if_needed()
    state_manager.load_all()

    ch_msg_count = len(
        state_manager.messages_state.get(channel_name, {})
        .get("collected_message_ids", set())
    )
    print(f"  기존 수집 메시지: {ch_msg_count:,}건 (이 채널)")

    print("\n" + "=" * 55)
    print(f"  수집 기준: 최근 {lookback}시간")
    print(f"  대상 채널: {channel_name}")
    print("=" * 55)

    # ── 5) 수집 ──────────────────────────────────────────
    client = create_client(settings)
    stats  = {}

    try:
        await client.start()
        me       = await client.get_me()
        name_str = me.first_name or ''
        user_str = f"@{me.username}" if me.username else "(username 없음)"
        print(f"  로그인 계정: {name_str} {user_str}\n")

        stats = await collect_channel(client, raw_input_str, settings, state_manager)
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

    # ── 6) 결과 출력 ──────────────────────────────────────
    skipped = (
        stats.get("files_already_downloaded", 0) +
        stats.get("files_too_large", 0)
    )
    print("\n" + "=" * 55)
    print("  수집 완료")
    print("=" * 55)
    print(f"  검사 메시지    : {stats.get('checked_messages', 0):,}건")
    print(f"  신규 메시지    : {stats.get('new_messages', 0):,}건")
    print(f"  파일 발견      : {stats.get('files_found', 0):,}건")
    print(f"  파일 다운로드  : {stats.get('files_downloaded', 0):,}건")
    print(f"  파일 건너뜀    : {skipped:,}건")
    print(f"  다운로드 오류  : {stats.get('download_errors', 0):,}건")
    print("=" * 55)

    if settings.get("keep_console_open", True):
        input("\n  Enter 를 누르면 종료합니다...")


def main() -> None:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
