# collector/gui_config.py - GUI 설정 저장/불러오기 담당

import json
import os
from pathlib import Path

from dotenv import load_dotenv

try:
    from dotenv import set_key as _dotenv_set_key
    _HAS_SET_KEY = True
except ImportError:
    _HAS_SET_KEY = False

from .utils import get_base_dir

SETTINGS_FILENAME = "settings.json"

_DEFAULTS: dict = {
    "api_id":                  "",
    "api_hash":                "",
    "lookback_hours":          12,
    "channels":                [],
    "allowed_extensions":      [],
    "allow_all_extensions":    True,
    "max_file_size_mb":        0,
    "keep_original_file_days": 30,
    "download_file_types":     "all",
}


# ── 불러오기 ─────────────────────────────────────────────

def load_gui_settings() -> dict:
    """settings.json → .env → 기본값 순서로 설정을 읽어 반환한다."""
    base_dir  = get_base_dir()
    json_path = base_dir / SETTINGS_FILENAME

    if json_path.exists():
        try:
            with open(json_path, encoding="utf-8") as f:
                data = json.load(f)
            settings = dict(_DEFAULTS)
            settings.update(data)
            return settings
        except (json.JSONDecodeError, OSError):
            pass

    env_path = base_dir / ".env"
    if env_path.exists():
        return _load_from_env(base_dir)

    return dict(_DEFAULTS)


def _load_from_env(base_dir: Path) -> dict:
    """기존 .env에서 GUI settings 형식으로 변환해 반환한다."""
    load_dotenv(dotenv_path=base_dir / ".env", override=True)

    settings = dict(_DEFAULTS)
    settings["api_id"]   = os.getenv("TELEGRAM_API_ID",   "").strip()
    settings["api_hash"] = os.getenv("TELEGRAM_API_HASH", "").strip()

    try:
        settings["lookback_hours"] = int(os.getenv("TELEGRAM_LOOKBACK_HOURS", "12"))
    except ValueError:
        settings["lookback_hours"] = 12

    channels_raw = os.getenv("TELEGRAM_CHANNELS", "").strip()
    settings["channels"] = channels_text_to_list(channels_raw) if channels_raw else []

    include_raw = os.getenv("INCLUDE_FILE_EXTS", "").strip()
    if include_raw:
        settings["allowed_extensions"]   = normalize_extensions(include_raw)
        settings["allow_all_extensions"] = False
    else:
        settings["allowed_extensions"]   = []
        settings["allow_all_extensions"] = True

    try:
        settings["max_file_size_mb"] = int(os.getenv("MAX_FILE_SIZE_MB", "0"))
    except ValueError:
        settings["max_file_size_mb"] = 0

    try:
        settings["keep_original_file_days"] = int(
            os.getenv("KEEP_ORIGINAL_FILE_DAYS", "30")
        )
    except ValueError:
        settings["keep_original_file_days"] = 30

    settings["download_file_types"] = (
        os.getenv("DOWNLOAD_FILE_TYPES", "all").strip().lower() or "all"
    )
    return settings


# ── 저장 ─────────────────────────────────────────────────

def save_gui_settings(settings: dict) -> None:
    """settings.json에 저장하고 .env도 함께 업데이트한다."""
    base_dir  = get_base_dir()
    json_path = base_dir / SETTINGS_FILENAME

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)

    _sync_to_env(settings, base_dir)


def _sync_to_env(settings: dict, base_dir: Path) -> None:
    """설정값을 .env 파일에도 반영한다."""
    if not _HAS_SET_KEY:
        return

    env_path = base_dir / ".env"

    channels_str = ",".join(settings.get("channels", []))
    if settings.get("allow_all_extensions", True):
        include_exts = ""
    else:
        include_exts = ",".join(settings.get("allowed_extensions", []))

    pairs = {
        "TELEGRAM_API_ID":         str(settings.get("api_id",   "")),
        "TELEGRAM_API_HASH":       str(settings.get("api_hash", "")),
        "TELEGRAM_LOOKBACK_HOURS": str(settings.get("lookback_hours", 12)),
        "TELEGRAM_CHANNELS":       channels_str,
        "INCLUDE_FILE_EXTS":       include_exts,
        "EXCLUDE_FILE_EXTS":       "",
        "MAX_FILE_SIZE_MB":        str(settings.get("max_file_size_mb", 0)),
        "KEEP_ORIGINAL_FILE_DAYS": str(settings.get("keep_original_file_days", 30)),
        "DOWNLOAD_FILE_TYPES":     settings.get("download_file_types", "all"),
        "KEEP_CONSOLE_OPEN":       "true",
    }
    for key, value in pairs.items():
        try:
            _dotenv_set_key(str(env_path), key, value)
        except Exception:
            pass


# ── 검증 ─────────────────────────────────────────────────

def validate_gui_settings(settings: dict) -> list[str]:
    """유효성 검사. 오류 메시지 리스트 반환 (빈 리스트 = 유효)."""
    errors: list[str] = []

    api_id = str(settings.get("api_id", "")).strip()
    if not api_id:
        errors.append("API ID 를 입력해 주세요.")
    elif not api_id.isdigit():
        errors.append("API ID 는 숫자만 입력할 수 있습니다.")

    if not str(settings.get("api_hash", "")).strip():
        errors.append("API Hash 를 입력해 주세요.")

    try:
        if int(settings.get("lookback_hours", 0)) <= 0:
            errors.append("수집 시간 범위는 1 이상이어야 합니다.")
    except (TypeError, ValueError):
        errors.append("수집 시간 범위는 숫자여야 합니다.")

    try:
        if int(settings.get("max_file_size_mb", 0)) < 0:
            errors.append("최대 파일 크기는 0 이상이어야 합니다.")
    except (TypeError, ValueError):
        errors.append("최대 파일 크기는 숫자여야 합니다.")

    try:
        if int(settings.get("keep_original_file_days", 1)) < 1:
            errors.append("파일 보관 기간은 1 이상이어야 합니다.")
    except (TypeError, ValueError):
        errors.append("파일 보관 기간은 숫자여야 합니다.")

    return errors


# ── GUI → collect settings 변환 ───────────────────────────

def gui_settings_to_collect_settings(
    gui_settings: dict,
    base_dir: Path | None = None,
) -> dict:
    """GUI settings dict를 collect_channel 등이 사용하는 settings dict로 변환한다."""
    if base_dir is None:
        base_dir = get_base_dir()

    if gui_settings.get("allow_all_extensions", True):
        include_exts: set = set()
    else:
        exts = gui_settings.get("allowed_extensions", [])
        include_exts = set(
            ext if ext.startswith(".") else f".{ext}"
            for ext in exts if str(ext).strip()
        )

    def _int(key, default):
        try:
            return int(gui_settings.get(key, default))
        except (TypeError, ValueError):
            return default

    return {
        "api_id":              str(gui_settings.get("api_id",   "")).strip(),
        "api_hash":            str(gui_settings.get("api_hash", "")).strip(),
        "lookback_hours":      _int("lookback_hours", 12),
        "channels":            gui_settings.get("channels", []),
        "max_file_size_mb":    _int("max_file_size_mb", 0),
        "keep_file_days":      _int("keep_original_file_days", 30),
        "download_file_types": gui_settings.get("download_file_types", "all"),
        "include_file_exts":   include_exts,
        "exclude_file_exts":   set(),
        "keep_console_open":   False,
        "base_dir":            base_dir,
        "data_dir":            base_dir / "data",
        "state_dir":           base_dir / "state",
        "config_dir":          base_dir / "config",
        "session_path":        str(base_dir / "telegram_session"),
    }


# ── 변환 헬퍼 ────────────────────────────────────────────

def normalize_extensions(text_or_list) -> list[str]:
    """확장자 입력을 정규화해서 리스트로 반환한다."""
    if isinstance(text_or_list, list):
        items = text_or_list
    else:
        items = str(text_or_list).replace("\n", ",").split(",")

    result: list[str] = []
    seen:   set[str]  = set()
    for item in items:
        ext = item.strip().lower()
        if not ext:
            continue
        if not ext.startswith("."):
            ext = f".{ext}"
        if ext not in seen:
            seen.add(ext)
            result.append(ext)
    return result


def channels_text_to_list(text: str) -> list[str]:
    """여러 줄 또는 쉼표 구분 채널 텍스트를 리스트로 변환한다."""
    channels = []
    for line in text.replace(",", "\n").splitlines():
        ch = line.strip()
        if ch:
            channels.append(ch)
    return channels


def channels_list_to_text(channels: list) -> str:
    """채널 리스트를 여러 줄 텍스트로 변환한다."""
    return "\n".join(str(ch) for ch in channels)
