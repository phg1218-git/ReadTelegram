# collector/config.py - 환경변수 / settings.json 로드 및 설정 관리
#
# 우선순위: settings.json → .env → 기본값

import json
import os
import sys

from dotenv import load_dotenv

from .utils import get_base_dir, parse_int_env


def load_settings() -> dict:
    """
    설정을 읽어 딕셔너리로 반환한다.

    우선순위:
      1. config/settings.json  (GUI 저장 파일)
      2. .env
      3. 기본값 (필수값 누락 시 오류 출력 후 종료)

    exe / Python 실행 환경 모두에서 경로를 올바르게 찾는다.
    """
    base_dir  = get_base_dir()
    json_path = base_dir / "settings.json"

    if json_path.exists():
        try:
            with open(json_path, encoding="utf-8") as f:
                data = json.load(f)
            return _json_to_collect_settings(data, base_dir)
        except (json.JSONDecodeError, OSError) as err:
            print(f"[경고] settings.json 읽기 실패 ({err}). .env 로 대체합니다.")

    # ── .env fallback ─────────────────────────────────────
    load_dotenv(dotenv_path=base_dir / ".env")

    api_id   = os.getenv("TELEGRAM_API_ID",   "").strip()
    api_hash = os.getenv("TELEGRAM_API_HASH", "").strip()

    if not api_id or not api_hash:
        print("\n" + "=" * 60)
        print("[오류] .env 파일에 API 정보가 없습니다.")
        print("=" * 60)
        print("해결 방법:")
        print("  1. .env.example 파일을 복사해서 .env 파일을 만드세요.")
        print("     cmd:        copy .env.example .env")
        print("     PowerShell: Copy-Item .env.example .env")
        print("  2. https://my.telegram.org 에서 api_id 와 api_hash 를 발급받으세요.")
        print("  3. .env 파일에 실제 값을 입력하세요:")
        print("       TELEGRAM_API_ID=12345678")
        print("       TELEGRAM_API_HASH=abcdef1234567890abcdef1234567890")
        print("=" * 60 + "\n")
        sys.exit(1)

    if not api_id.isdigit():
        print(f"\n[오류] TELEGRAM_API_ID 는 숫자여야 합니다. 현재 값: {api_id!r}\n")
        sys.exit(1)

    lookback_hours      = parse_int_env(os.getenv("TELEGRAM_LOOKBACK_HOURS", ""),   default=12)
    max_file_size_mb    = parse_int_env(os.getenv("MAX_FILE_SIZE_MB",         ""),   default=0)
    keep_file_days      = parse_int_env(os.getenv("KEEP_ORIGINAL_FILE_DAYS",  ""),   default=30)
    download_file_types = os.getenv("DOWNLOAD_FILE_TYPES", "all").strip().lower() or "all"
    keep_console_open   = os.getenv("KEEP_CONSOLE_OPEN", "true").strip().lower() == "true"

    channels_raw = os.getenv("TELEGRAM_CHANNELS", "").strip()
    channels = (
        [ch.strip() for ch in channels_raw.split(",") if ch.strip()]
        if channels_raw else []
    )

    include_raw = os.getenv("INCLUDE_FILE_EXTS", "").strip()
    include_file_exts: set = set()
    for ext in include_raw.split(","):
        ext = ext.strip().lower()
        if ext:
            include_file_exts.add(ext if ext.startswith(".") else f".{ext}")

    exclude_raw = os.getenv("EXCLUDE_FILE_EXTS", "").strip()
    exclude_file_exts: set = set()
    for ext in exclude_raw.split(","):
        ext = ext.strip().lower()
        if ext:
            exclude_file_exts.add(ext if ext.startswith(".") else f".{ext}")

    return {
        "api_id":              api_id,
        "api_hash":            api_hash,
        "lookback_hours":      lookback_hours,
        "channels":            channels,
        "max_file_size_mb":    max_file_size_mb,
        "keep_file_days":      keep_file_days,
        "download_file_types": download_file_types,
        "include_file_exts":   include_file_exts,
        "exclude_file_exts":   exclude_file_exts,
        "keep_console_open":   keep_console_open,
        "base_dir":            base_dir,
        "data_dir":            base_dir / "data",
        "state_dir":           base_dir / "state",
        "config_dir":          base_dir / "config",
        "session_path":        str(base_dir / "telegram_session"),
    }


def _json_to_collect_settings(data: dict, base_dir) -> dict:
    """settings.json 형식의 dict를 collect_channel이 사용하는 settings로 변환한다."""
    from pathlib import Path
    base_dir = Path(base_dir)

    api_id   = str(data.get("api_id",   "")).strip()
    api_hash = str(data.get("api_hash", "")).strip()

    if not api_id or not api_hash:
        print("\n" + "=" * 60)
        print("[오류] settings.json 에 API 정보가 없습니다.")
        print("  GUI 에서 API ID 와 API Hash 를 입력하고 '설정 저장'을 눌러 주세요.")
        print("=" * 60 + "\n")
        sys.exit(1)

    if not api_id.isdigit():
        print(f"\n[오류] API ID 는 숫자여야 합니다. 현재 값: {api_id!r}\n")
        sys.exit(1)

    if data.get("allow_all_extensions", True):
        include_file_exts: set = set()
    else:
        exts = data.get("allowed_extensions", [])
        include_file_exts = set(
            ext if ext.startswith(".") else f".{ext}"
            for ext in exts if str(ext).strip()
        )

    def _int(key, default):
        try:
            return int(data.get(key, default))
        except (TypeError, ValueError):
            return default

    return {
        "api_id":              api_id,
        "api_hash":            api_hash,
        "lookback_hours":      _int("lookback_hours", 12),
        "channels":            data.get("channels", []),
        "max_file_size_mb":    _int("max_file_size_mb", 0),
        "keep_file_days":      _int("keep_original_file_days", 30),
        "download_file_types": data.get("download_file_types", "all"),
        "include_file_exts":   include_file_exts,
        "exclude_file_exts":   set(),
        "keep_console_open":   True,
        "base_dir":            base_dir,
        "data_dir":            base_dir / "data",
        "state_dir":           base_dir / "state",
        "config_dir":          base_dir / "config",
        "session_path":        str(base_dir / "telegram_session"),
    }


def get_configured_channels(settings: dict) -> list:
    return settings.get("channels", [])


def get_lookback_hours(settings: dict) -> int:
    return settings.get("lookback_hours", 12)
