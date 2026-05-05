#!/usr/bin/env python3
# manage_state.py
# 수집 상태 파일을 검사하고 관리하는 CLI 도구
#
# 사용법:
#   python manage_state.py status                   # 전체 채널 현황
#   python manage_state.py status --channel <name>  # 특정 채널 상세
#   python manage_state.py reset-channel <name>     # 채널 상태 초기화
#   python manage_state.py reset-all                # 전체 상태 초기화
#   python manage_state.py retry-failed             # 실패 항목 재시도 대기열에 등록
#   python manage_state.py verify-files             # 파일 불일치 검사
#   python manage_state.py verify-files --fix       # 파일 불일치 검사 + 상태 수정

import argparse
import sys

from collector.config import load_settings
from collector.state_manager import StateManager


# ────────────────────────────────────────────────────────
# 서브커맨드 핸들러
# ────────────────────────────────────────────────────────

def cmd_status(state_manager: StateManager, channel: str | None) -> None:
    """채널별 수집 현황을 출력한다."""
    channels_state = state_manager.channels_state

    if not channels_state:
        print("  저장된 채널 수집 이력이 없습니다.")
        return

    if channel:
        # 특정 채널 상세 출력
        normalized = channel.lstrip("@")
        entry = channels_state.get(normalized)
        if not entry:
            print(f"  '{normalized}' 채널의 수집 이력이 없습니다.")
            return
        _print_channel_detail(normalized, entry, state_manager)
    else:
        # 전체 채널 목록 출력
        print(f"\n{'채널명':<30} {'마지막 수집':<25} {'총 메시지':>10} {'총 파일':>10} {'오류':>6}")
        print("-" * 90)
        for ch_name, entry in sorted(channels_state.items()):
            last = entry.get("last_collected_at", "")[:19] if entry.get("last_collected_at") else "-"
            msgs = entry.get("total_new_messages", 0)
            files = entry.get("total_files_downloaded", 0)
            errs  = entry.get("total_errors", 0)
            print(f"  {ch_name:<28} {last:<25} {msgs:>10,} {files:>10,} {errs:>6,}")

        total_channels = len(channels_state)
        total_msg_ids  = sum(
            len(v.get("collected_message_ids", set()))
            for v in state_manager.messages_state.values()
        )
        total_files    = sum(
            1 for v in state_manager.files_state.values()
            if v.get("status") == "downloaded"
        )
        total_failed   = len(state_manager.failed_downloads)

        print("-" * 90)
        print(f"\n  총 채널 수          : {total_channels:,}개")
        print(f"  총 수집 메시지 수   : {total_msg_ids:,}건")
        print(f"  총 다운로드 파일 수 : {total_files:,}건")
        print(f"  실패 다운로드 수    : {total_failed:,}건")


def _print_channel_detail(channel_name: str, entry: dict, state_manager: StateManager) -> None:
    """채널 하나의 상세 정보를 출력한다."""
    msg_entry  = state_manager.messages_state.get(channel_name, {})
    msg_ids    = msg_entry.get("collected_message_ids", set())
    file_keys  = [k for k in state_manager.files_state if k.startswith(f"{channel_name}:")]
    dl_ok      = sum(1 for k in file_keys if state_manager.files_state[k].get("status") == "downloaded")
    dl_fail    = sum(1 for k in file_keys if state_manager.files_state[k].get("status") == "download_error")
    dl_large   = sum(1 for k in file_keys if state_manager.files_state[k].get("status") == "file_too_large")
    failed_cnt = sum(1 for k in state_manager.failed_downloads if k.startswith(f"{channel_name}:"))

    print(f"\n  채널명              : {channel_name}")
    print(f"  채널 주소           : {entry.get('channel_input', '-')}")
    print(f"  첫 수집             : {entry.get('first_collected_at', '-')}")
    print(f"  마지막 수집         : {entry.get('last_collected_at', '-')}")
    print(f"  수집 메시지 수      : {len(msg_ids):,}건")
    print(f"  마지막 메시지 ID    : {msg_entry.get('last_message_id', '-')}")
    print(f"  다운로드 성공       : {dl_ok:,}건")
    print(f"  다운로드 실패       : {dl_fail:,}건")
    print(f"  크기 초과 건너뜀    : {dl_large:,}건")
    print(f"  재시도 대기 중      : {failed_cnt:,}건")


def cmd_reset_channel(state_manager: StateManager, channel_name: str) -> None:
    """특정 채널의 상태를 초기화한다."""
    normalized = channel_name.lstrip("@")

    if normalized not in state_manager.channels_state and \
       normalized not in state_manager.messages_state:
        print(f"  '{normalized}' 채널의 수집 이력이 없습니다.")
        return

    confirm = input(f"  '{normalized}' 채널의 모든 상태를 초기화합니다. 계속할까요? [y/N] ").strip().lower()
    if confirm != "y":
        print("  취소됐습니다.")
        return

    state_manager.reset_channel(normalized)
    state_manager.save_all()
    print(f"  '{normalized}' 채널 상태 초기화 완료.")
    print("  (실제 다운로드된 파일은 삭제되지 않았습니다.)")


def cmd_reset_all(state_manager: StateManager) -> None:
    """모든 상태를 초기화한다."""
    total_ch  = len(state_manager.channels_state)
    total_msg = sum(
        len(v.get("collected_message_ids", set()))
        for v in state_manager.messages_state.values()
    )
    total_files = len(state_manager.files_state)

    print(f"  현재 상태: 채널 {total_ch}개, 메시지 {total_msg:,}건, 파일 {total_files:,}건")
    confirm = input("  모든 수집 상태를 초기화합니다. 계속할까요? [y/N] ").strip().lower()
    if confirm != "y":
        print("  취소됐습니다.")
        return

    state_manager.reset_all()
    state_manager.save_all()
    print("  전체 상태 초기화 완료.")
    print("  (실제 다운로드된 파일은 삭제되지 않았습니다.)")


def cmd_retry_failed(state_manager: StateManager) -> None:
    """실패한 다운로드를 pending 상태로 변경해 다음 수집 시 재시도하게 한다."""
    count = len(state_manager.failed_downloads)
    if count == 0:
        print("  재시도할 실패 항목이 없습니다.")
        return

    print(f"  실패 항목 {count:,}건을 재시도 대기열에 등록합니다.")
    changed = state_manager.mark_failed_as_pending()
    state_manager.save_all()
    print(f"  {changed:,}건이 pending 상태로 변경됐습니다.")
    print("  다음 수집 실행 시 재시도됩니다.")


def cmd_verify_files(state_manager: StateManager, fix: bool) -> None:
    """files_state 에 downloaded 로 기록됐지만 실제로 없는 파일을 찾는다."""
    missing = state_manager.find_missing_files()

    if not missing:
        print("  파일 불일치 없음. 모든 downloaded 파일이 정상입니다.")
        return

    print(f"\n  파일 불일치 발견: {len(missing)}건")
    print(f"  {'파일 키':<60} {'경로'}")
    print("-" * 120)
    for file_key, entry in missing:
        path = entry.get("downloaded_path", "")
        print(f"  {file_key[:58]:<60} {path}")

    if fix:
        count = state_manager.mark_missing_as_missing_file()
        state_manager.save_all()
        print(f"\n  {count}건의 상태를 'missing_file' 로 변경했습니다.")
        print("  다음 수집 실행 시 재다운로드를 시도합니다.")
    else:
        print("\n  --fix 옵션을 추가하면 상태를 자동으로 수정합니다.")


# ────────────────────────────────────────────────────────
# 진입점
# ────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="manage_state",
        description="텔레그램 수집기 상태 관리 CLI",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # status
    p_status = subparsers.add_parser("status", help="채널별 수집 현황 출력")
    p_status.add_argument(
        "--channel", "-c", metavar="CHANNEL",
        help="특정 채널 상세 출력 (채널명 또는 @채널명)",
    )

    # reset-channel
    p_reset_ch = subparsers.add_parser("reset-channel", help="특정 채널 상태 초기화")
    p_reset_ch.add_argument("channel", metavar="CHANNEL", help="초기화할 채널명")

    # reset-all
    subparsers.add_parser("reset-all", help="전체 상태 초기화")

    # retry-failed
    subparsers.add_parser("retry-failed", help="실패 항목 재시도 등록")

    # verify-files
    p_verify = subparsers.add_parser("verify-files", help="파일 존재 여부 검사")
    p_verify.add_argument(
        "--fix", action="store_true",
        help="불일치 항목 상태를 missing_file 로 자동 수정",
    )

    args = parser.parse_args()

    settings      = load_settings()
    state_manager = StateManager(settings["state_dir"])
    state_manager.load_all()

    print("\n" + "=" * 55)
    print("  텔레그램 수집기 상태 관리")
    print("=" * 55)

    if args.command == "status":
        cmd_status(state_manager, getattr(args, "channel", None))
    elif args.command == "reset-channel":
        cmd_reset_channel(state_manager, args.channel)
    elif args.command == "reset-all":
        cmd_reset_all(state_manager)
    elif args.command == "retry-failed":
        cmd_retry_failed(state_manager)
    elif args.command == "verify-files":
        cmd_verify_files(state_manager, args.fix)

    print()


if __name__ == "__main__":
    main()
