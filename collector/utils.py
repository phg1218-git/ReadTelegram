# collector/utils.py - 공통 유틸리티 함수 모음

import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

KST = timezone(timedelta(hours=9))

# ── MIME type → 확장자 매핑 ──────────────────────────────
_MIME_TO_EXT: dict[str, str] = {
    "application/pdf":                                                          ".pdf",
    "application/vnd.ms-excel":                                                 ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":        ".xlsx",
    "text/csv":                                                                 ".csv",
    "application/vnd.ms-powerpoint":                                            ".ppt",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/msword":                                                       ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document":  ".docx",
    "application/zip":                                                          ".zip",
    "application/x-zip-compressed":                                             ".zip",
    "application/x-rar-compressed":                                             ".rar",
    "application/x-7z-compressed":                                              ".7z",
    "image/jpeg":                                                               ".jpg",
    "image/png":                                                                ".png",
    "image/gif":                                                                ".gif",
    "image/webp":                                                               ".webp",
    "video/mp4":                                                                ".mp4",
    "video/x-matroska":                                                         ".mkv",
    "text/plain":                                                               ".txt",
    "application/x-hwp":                                                        ".hwp",
}

# 확장자 → 파일 유형 분류
_EXT_TO_TYPE: dict[str, str] = {
    ".pdf":  "pdf",
    ".xls":  "excel",  ".xlsx": "excel",  ".csv": "excel",
    ".ppt":  "powerpoint", ".pptx": "powerpoint",
    ".doc":  "word",   ".docx": "word",   ".hwp": "word",  ".txt": "word",
    ".jpg":  "image",  ".jpeg": "image",  ".png": "image",
    ".gif":  "image",  ".bmp":  "image",  ".webp": "image",
    ".mp4":  "video",  ".avi":  "video",  ".mov": "video",
    ".mkv":  "video",  ".webm": "video",
    ".zip":  "archive", ".rar": "archive", ".7z": "archive",
    ".tar":  "archive", ".gz":  "archive",
}


def get_base_dir() -> Path:
    """
    실행 환경에 따라 프로젝트 루트 경로를 반환한다.

    - exe(PyInstaller --onefile) 실행 시: exe 파일이 있는 폴더
    - Python 스크립트 실행 시: 프로젝트 루트 (collector/ 의 상위 폴더)

    data/, state/, config/, .env 는 이 경로를 기준으로 찾는다.
    """
    if getattr(sys, 'frozen', False):
        # PyInstaller 로 빌드된 exe 실행 중
        return Path(sys.executable).parent
    else:
        # 일반 Python 실행: __file__ = collector/utils.py
        return Path(__file__).parent.parent


def normalize_channel_input(raw: str) -> str:
    """
    다양한 형식의 텔레그램 채널 주소를 username 문자열로 정규화한다.

    지원 형식:
      https://t.me/insidertracking  → insidertracking
      http://t.me/insidertracking   → insidertracking
      t.me/insidertracking          → insidertracking
      @insidertracking              → insidertracking
      insidertracking               → insidertracking
    """
    s = raw.strip()
    s = re.sub(r'^https?://t\.me/', '', s, flags=re.IGNORECASE)
    s = re.sub(r'^t\.me/', '', s, flags=re.IGNORECASE)
    s = s.lstrip('@')
    s = s.split('/')[0]
    s = s.strip()
    if not s:
        raise ValueError("채널 주소가 비어 있습니다. 다시 입력해 주세요.")
    return s


def extract_links(text: str) -> list:
    """메시지 본문에서 http(s):// 로 시작하는 URL을 모두 추출해 리스트로 반환한다."""
    if not text:
        return []
    return re.findall(r'https?://[^\s\]\)\'"<>]+', text)


def sanitize_filename(name: str) -> str:
    """
    Windows 파일명에 사용할 수 없는 문자를 밑줄(_)로 바꾼다.
    금지 문자: \\ / : * ? " < > |
    """
    name = re.sub(r'[\\/:*?"<>|]', '_', name)
    name = name.strip('. ')
    return name if name else "unnamed"


def utc_to_kst(dt_utc: datetime) -> datetime:
    """UTC datetime 을 KST(UTC+9) datetime 으로 변환한다."""
    return dt_utc.astimezone(KST)


def now_utc() -> datetime:
    """현재 UTC 시각을 timezone-aware datetime 으로 반환한다."""
    return datetime.now(timezone.utc)


def parse_int_env(value: str, default: int) -> int:
    """환경변수 문자열을 int 로 변환한다. 실패하면 default 를 반환한다."""
    try:
        return int(str(value).strip())
    except (ValueError, TypeError):
        return default


def get_file_extension(file_name: str, mime_type: str) -> str:
    """
    파일명 또는 MIME type 으로부터 확장자를 반환한다.
    파일명의 확장자를 우선하고, 없으면 MIME type 으로 추측한다.
    """
    if file_name:
        ext = Path(file_name).suffix.lower()
        if ext:
            return ext
    return _MIME_TO_EXT.get(mime_type or "", "")


def classify_file_type(file_name: str, mime_type: str) -> str:
    """
    파일명과 MIME type 으로 파일 유형을 분류한다.
    반환값: "pdf" | "excel" | "powerpoint" | "word" | "image" | "video" | "archive" | "unknown"
    """
    ext = get_file_extension(file_name, mime_type).lower()
    return _EXT_TO_TYPE.get(ext, "unknown")
