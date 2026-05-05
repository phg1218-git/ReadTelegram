# collector/rules.py - 파일 다운로드 여부 판단 로직
# keywords.txt 는 이제 다운로드 여부 결정에 사용하지 않는다.
# 모든 첨부파일을 기본 다운로드하며, 크기 제한과 중복만 확인한다.

from pathlib import Path
from .utils import get_file_extension, classify_file_type

# ── 파일 유형 분류 기준 ──────────────────────────────────
_DOCUMENT_EXTS = {
    ".pdf", ".xls", ".xlsx", ".csv",
    ".ppt", ".pptx", ".doc", ".docx", ".hwp", ".txt",
}
_MEDIA_EXTS = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp",
    ".mp4", ".avi", ".mov", ".mkv", ".webm",
}


def load_keywords(config_dir: Path) -> list:
    """
    config/keywords.txt 에서 키워드를 로드한다.
    현재는 다운로드 여부 판단에 사용하지 않고, 향후 태깅/분류용으로만 남겨둔다.
    """
    kw_file = config_dir / "keywords.txt"
    if not kw_file.exists():
        return []
    keywords = []
    try:
        with open(kw_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    keywords.append(line)
    except OSError as err:
        print(f"[경고] keywords.txt 읽기 실패: {err}")
    return keywords


def is_downloadable_file(message, settings: dict) -> bool:
    """
    메시지에 첨부파일이 있고, 설정에서 허용하는 파일 유형인지 확인한다.

    DOWNLOAD_FILE_TYPES:
      - "all"           : 모든 첨부파일 허용
      - "document_only" : PDF/엑셀/파워포인트/워드/텍스트 등 문서형만 허용
      - "media_only"    : 이미지/영상만 허용
    """
    if message.file is None:
        return False

    download_types = settings.get("download_file_types", "all").lower()
    if download_types == "all":
        return True

    file_name = getattr(message.file, 'name', '') or ''
    mime_type = getattr(message.file, 'mime_type', '') or ''
    ext = get_file_extension(file_name, mime_type).lower()

    if download_types == "document_only":
        return ext in _DOCUMENT_EXTS
    if download_types == "media_only":
        return ext in _MEDIA_EXTS

    return True  # 알 수 없는 설정은 전체 허용으로 처리


def should_download_file(
    message,
    settings: dict,
    file_state_entry: dict | None,
) -> tuple[bool, str]:
    """
    파일을 다운로드해야 하는지 결정한다.

    반환: (download: bool, reason: str)
      reason:
        "ok"               → 다운로드 진행
        "no_file"          → 첨부파일 없음
        "ext_not_included" → INCLUDE_FILE_EXTS 에 없는 확장자 (allowlist)
        "ext_excluded"     → EXCLUDE_FILE_EXTS 에 포함된 확장자 (blocklist)
        "type_not_allowed" → DOWNLOAD_FILE_TYPES 설정으로 제외됨
        "file_too_large"   → MAX_FILE_SIZE_MB 초과
        "already_downloaded" → 이미 다운로드됐고 파일도 존재함
        "manually_ignored" → 사용자가 수동으로 무시 처리함
    """
    # 1) 첨부파일 없음
    if message.file is None:
        return False, "no_file"

    file_name = getattr(message.file, 'name', '') or ''
    mime_type = getattr(message.file, 'mime_type', '') or ''
    ext       = get_file_extension(file_name, mime_type).lower()

    # 2) 허용 확장자 필터 (allowlist) — 설정 시 여기 없으면 건너뜀
    include_exts = settings.get("include_file_exts", set())
    if include_exts and ext not in include_exts:
        return False, "ext_not_included"

    # 3) 제외 확장자 필터 (blocklist)
    exclude_exts = settings.get("exclude_file_exts", set())
    if exclude_exts and ext in exclude_exts:
        return False, "ext_excluded"

    # 4) 파일 유형 필터 (DOWNLOAD_FILE_TYPES) — allowlist 미설정 시에만 의미 있음
    if not include_exts and not is_downloadable_file(message, settings):
        return False, "type_not_allowed"

    # 4) 이미 처리된 파일 상태 확인
    if file_state_entry:
        status = file_state_entry.get("status", "")

        if status == "manually_ignored":
            return False, "manually_ignored"

        if status == "downloaded":
            # 파일이 실제로 존재하면 재다운로드 안 함
            path = file_state_entry.get("downloaded_path", "")
            if path and Path(path).exists():
                return False, "already_downloaded"
            # 파일이 없으면 (삭제됐으면) 다시 다운로드

        if status == "file_too_large":
            # 이전 실행에서 크기 초과였어도 설정이 바뀔 수 있으므로 다시 확인
            pass

    # 5) 크기 제한 확인 (0 = 제한 없음)
    max_mb = settings.get("max_file_size_mb", 0)
    if max_mb > 0:
        file_size = getattr(message.file, 'size', 0) or 0
        if file_size > max_mb * 1024 * 1024:
            return False, "file_too_large"

    return True, "ok"
