# collector/storage.py - 디렉토리 생성 / JSONL 쓰기 / 오류 로그 담당
# 상태 관리(state)는 collector/state_manager.py 에서 처리한다.

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

KST = timezone(timedelta(hours=9))


# ────────────────────────────────────────────────────────
# 디렉토리 생성
# ────────────────────────────────────────────────────────

def ensure_base_directories(settings: dict) -> None:
    """프로젝트 기본 디렉토리들을 생성한다."""
    settings["state_dir"].mkdir(parents=True, exist_ok=True)
    settings["data_dir"].mkdir(parents=True, exist_ok=True)
    settings["config_dir"].mkdir(parents=True, exist_ok=True)


def ensure_daily_directories(settings: dict, date_str: str) -> dict:
    """
    날짜별 데이터 디렉토리를 모두 생성하고 경로 딕셔너리를 반환한다.

    반환:
    {
        "day_dir":   data/YYYY-MM-DD/
        "files_dir": data/YYYY-MM-DD/downloaded_files/
        "logs_dir":  data/YYYY-MM-DD/logs/
    }
    """
    day_dir   = settings["data_dir"] / date_str
    files_dir = day_dir / "downloaded_files"
    logs_dir  = day_dir / "logs"

    day_dir.mkdir(parents=True, exist_ok=True)
    files_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    return {
        "day_dir":   day_dir,
        "files_dir": files_dir,
        "logs_dir":  logs_dir,
    }


# ────────────────────────────────────────────────────────
# JSON 파일 입출력 (storage.py 에서만 사용하는 내부 헬퍼)
# ────────────────────────────────────────────────────────

def load_json_file(path: Path, default):
    """JSON 파일을 읽어 파이썬 객체로 반환한다. 없거나 손상됐으면 default 반환."""
    if not path.exists():
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as err:
        print(f"[경고] {path.name} 읽기 실패 ({err}). 기본값으로 초기화합니다.")
        return default


def save_json_file(path: Path, data) -> None:
    """데이터를 JSON 파일로 저장한다."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError as err:
        print(f"[경고] {path.name} 저장 실패: {err}")


# ────────────────────────────────────────────────────────
# JSONL 파일 쓰기
# ────────────────────────────────────────────────────────

def append_jsonl(file_path: Path, record: dict) -> None:
    """
    JSON Lines 형식으로 레코드를 파일에 한 줄 추가한다.
    ensure_ascii=False 로 한글이 깨지지 않게 저장한다.
    """
    try:
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as err:
        raise OSError(f"{file_path.name} 저장 실패: {err}") from err


# ────────────────────────────────────────────────────────
# 오류 로그
# ────────────────────────────────────────────────────────

def log_error(logs_dir: Path, msg: str) -> None:
    """오류 메시지를 콘솔과 error.log 파일에 동시에 기록한다."""
    print(f"  [오류] {msg}")
    try:
        ts = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
        with open(logs_dir / "error.log", "a", encoding="utf-8") as f:
            f.write(f"[{ts} KST] {msg}\n")
    except OSError:
        pass
