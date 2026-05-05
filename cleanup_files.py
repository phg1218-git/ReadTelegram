#!/usr/bin/env python3
# cleanup_files.py
# 보관 기간이 지난 다운로드 파일을 정리하는 선택 실행 파일.
# messages.jsonl, file_index.jsonl 등 메타데이터는 삭제하지 않는다.
# 삭제 후 files_state.json 의 상태를 deleted 로 갱신한다.
# 사용법: python cleanup_files.py

import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

from collector.config import load_settings
from collector.state_manager import StateManager

KST = timezone(timedelta(hours=9))


def find_old_files(data_dir: Path, keep_days: int) -> list[tuple[Path, int]]:
    """
    data/*/downloaded_files/ 안의 파일 중 보관 기간이 지난 것을 찾는다.
    반환: [(파일경로, 파일크기), ...] 목록 (오래된 순 정렬)
    """
    cutoff    = datetime.now(timezone.utc) - timedelta(days=keep_days)
    old_files = []

    for file_path in data_dir.glob("*/downloaded_files/*"):
        if not file_path.is_file():
            continue
        try:
            stat  = file_path.stat()
            mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
            if mtime < cutoff:
                old_files.append((file_path, stat.st_size))
        except OSError:
            continue

    old_files.sort(key=lambda x: x[0])
    return old_files


def format_size(size_bytes: int) -> str:
    """파일 크기를 사람이 읽기 쉬운 단위 문자열로 변환한다."""
    if size_bytes < 1_024:
        return f"{size_bytes} B"
    if size_bytes < 1_024 ** 2:
        return f"{size_bytes / 1_024:.1f} KB"
    if size_bytes < 1_024 ** 3:
        return f"{size_bytes / 1_024 ** 2:.1f} MB"
    return f"{size_bytes / 1_024 ** 3:.1f} GB"


def main() -> None:
    settings      = load_settings()
    data_dir      = settings["data_dir"]
    keep_days     = settings.get("keep_file_days", 30)
    state_manager = StateManager(settings["state_dir"])
    state_manager.load_all()

    print("\n" + "=" * 55)
    print("  다운로드 파일 정리")
    print(f"  보관 기간 설정: {keep_days}일")
    print("=" * 55)

    old_files = find_old_files(data_dir, keep_days)

    if not old_files:
        print(f"\n  {keep_days}일이 지난 파일이 없습니다.\n")
        return

    total_size = sum(sz for _, sz in old_files)

    print(f"\n  삭제 대상: {len(old_files):,}개 파일  (총 {format_size(total_size)})\n")
    for file_path, size in old_files:
        try:
            rel = file_path.relative_to(data_dir)
        except ValueError:
            rel = file_path
        print(f"    {rel}  ({format_size(size)})")

    print()
    answer = input("  위 파일들을 삭제하시겠습니까? (y/N): ").strip().lower()

    if answer != "y":
        print("  취소됐습니다.\n")
        return

    deleted = 0
    failed  = 0
    deleted_paths: set[str] = set()

    for file_path, _ in old_files:
        try:
            file_path.unlink()
            deleted_paths.add(str(file_path))
            deleted += 1
        except OSError as err:
            print(f"  [오류] {file_path.name} 삭제 실패: {err}")
            failed += 1

    # files_state.json 에서 삭제된 파일 상태를 deleted 로 갱신
    updated = 0
    for file_key, entry in state_manager.files_state.items():
        path = entry.get("downloaded_path", "")
        if path and path in deleted_paths:
            entry["status"] = "deleted"
            entry["deleted_at"] = datetime.now(KST).isoformat()
            updated += 1

    if updated:
        state_manager.save_all()

    print(f"\n  삭제 완료: {deleted:,}개 | 실패: {failed:,}개")
    if updated:
        print(f"  파일 상태 갱신: {updated:,}건 (deleted 로 변경)")
    print()


if __name__ == "__main__":
    main()
