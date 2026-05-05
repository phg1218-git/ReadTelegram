#!/usr/bin/env python3
# cleanup_pdfs.py
# 보관 기간이 지난 원본 PDF 파일을 정리하는 선택 실행 파일.
# messages.jsonl, pdf_index.jsonl, skipped_pdfs.jsonl, extracted_text 는 삭제하지 않는다.
# 사용법: python cleanup_pdfs.py

import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

from collector.config import load_settings

KST = timezone(timedelta(hours=9))


def find_old_pdfs(data_dir: Path, keep_days: int) -> list[tuple[Path, int]]:
    """
    data/*/selected_pdfs/ 안의 PDF 중 보관 기간이 지난 파일을 찾는다.
    반환: [(파일경로, 파일크기), ...] 목록 (오래된 순 정렬)
    """
    cutoff    = datetime.now(timezone.utc) - timedelta(days=keep_days)
    old_files = []

    for pdf_path in data_dir.glob("*/selected_pdfs/*.pdf"):
        try:
            stat  = pdf_path.stat()
            mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
            if mtime < cutoff:
                old_files.append((pdf_path, stat.st_size))
        except OSError:
            continue  # 접근 불가 파일은 조용히 건너뜀

    # 수정 시각 오래된 순 정렬
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
    settings  = load_settings()
    data_dir  = settings["data_dir"]
    keep_days = settings["keep_pdf_days"]

    print("\n" + "=" * 55)
    print("  PDF 원본 파일 정리")
    print(f"  보관 기간 설정: {keep_days}일")
    print("=" * 55)

    old_files = find_old_pdfs(data_dir, keep_days)

    if not old_files:
        print(f"\n  {keep_days}일이 지난 PDF 파일이 없습니다.\n")
        return

    total_size = sum(sz for _, sz in old_files)

    print(f"\n  삭제 대상: {len(old_files)}개 파일  (총 {format_size(total_size)})\n")
    for path, size in old_files:
        # data/ 이하 상대 경로로 표시
        try:
            rel = path.relative_to(data_dir)
        except ValueError:
            rel = path
        print(f"    {rel}  ({format_size(size)})")

    print()
    answer = input("  위 파일들을 삭제하시겠습니까? (y/N): ").strip().lower()

    if answer != 'y':
        print("  취소됐습니다.\n")
        return

    deleted = 0
    failed  = 0
    for path, _ in old_files:
        try:
            path.unlink()
            deleted += 1
        except OSError as err:
            print(f"  [오류] {path.name} 삭제 실패: {err}")
            failed += 1

    print(f"\n  삭제 완료: {deleted}개 | 실패: {failed}개\n")


if __name__ == "__main__":
    main()
