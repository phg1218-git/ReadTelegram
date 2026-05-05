# main.py - 텔레그램 공개 채널 메시지·PDF 수집기
# 사용법: python main.py

import asyncio
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.errors import (
    UsernameNotOccupiedError,
    UsernameInvalidError,
    ChannelPrivateError,
    FloodWaitError,
)

# ────────────────────────────────────────────────────────
# 기본 경로 설정
# ────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent          # 이 파일이 있는 폴더
DATA_DIR   = BASE_DIR / "data"
STATE_DIR  = BASE_DIR / "state"
STATE_FILE = STATE_DIR / "collected_messages.json"
SESSION_NAME = str(BASE_DIR / "telegram_session")  # .session 파일 경로

KST       = timezone(timedelta(hours=9))    # 한국 표준시 UTC+9
HOURS_BACK = 3                              # 수집할 과거 시간 범위


# ────────────────────────────────────────────────────────
# [1] 환경변수 로드 및 유효성 검사
# ────────────────────────────────────────────────────────
def load_config():
    """
    프로젝트 루트의 .env 파일에서 API 자격증명을 읽는다.
    값이 누락됐으면 안내 메시지를 출력하고 프로그램을 종료한다.
    반환: (api_id: str, api_hash: str)
    """
    load_dotenv()  # .env 파일을 환경변수로 로드

    api_id   = os.getenv("TELEGRAM_API_ID",   "").strip()
    api_hash = os.getenv("TELEGRAM_API_HASH", "").strip()

    if not api_id or not api_hash:
        print("\n" + "=" * 55)
        print("[오류] .env 파일에 API 정보가 없습니다.")
        print("=" * 55)
        print("해결 방법:")
        print("  1. 이 폴더의 .env.example 을 복사해 .env 파일을 만드세요.")
        print("  2. https://my.telegram.org 에서 api_id / api_hash 를 발급받으세요.")
        print("  3. .env 파일에 아래처럼 입력하세요:")
        print("       TELEGRAM_API_ID=12345678")
        print("       TELEGRAM_API_HASH=abcdef1234567890abcdef1234567890")
        print("=" * 55 + "\n")
        sys.exit(1)

    # api_id 는 숫자여야 함
    if not api_id.isdigit():
        print(f"[오류] TELEGRAM_API_ID 는 숫자여야 합니다. (현재 값: {api_id!r})")
        sys.exit(1)

    return api_id, api_hash


# ────────────────────────────────────────────────────────
# [2] 채널 주소 정규화
# ────────────────────────────────────────────────────────
def normalize_channel_input(raw):
    """
    다양한 형식의 텔레그램 채널 주소를 username 문자열로 정규화한다.

    입력 예시 → 출력:
      https://t.me/sunstudy1004  → sunstudy1004
      http://t.me/sunstudy1004   → sunstudy1004
      t.me/sunstudy1004          → sunstudy1004
      @sunstudy1004              → sunstudy1004
      sunstudy1004               → sunstudy1004
    """
    s = raw.strip()

    # https?://t.me/ 제거
    s = re.sub(r'^https?://t\.me/', '', s, flags=re.IGNORECASE)

    # t.me/ 제거 (프로토콜 없는 경우)
    s = re.sub(r'^t\.me/', '', s, flags=re.IGNORECASE)

    # 맨 앞의 @ 제거
    s = s.lstrip('@')

    # 슬래시 이후 부분 제거 (예: 채널명/메시지번호 → 채널명)
    s = s.split('/')[0]

    # 앞뒤 공백 정리
    s = s.strip()

    if not s:
        raise ValueError("채널 주소가 비어 있습니다. 다시 입력해 주세요.")

    return s


# ────────────────────────────────────────────────────────
# [3] 필요한 폴더 일괄 생성
# ────────────────────────────────────────────────────────
def ensure_directories(date_str):
    """
    날짜별 저장 폴더와 하위 폴더를 모두 생성한다.
    반환값: (day_dir, pdfs_dir, logs_dir) — Path 객체
    """
    day_dir  = DATA_DIR / date_str
    pdfs_dir = day_dir / "pdfs"
    logs_dir = day_dir / "logs"

    # parents=True : 상위 폴더도 함께 생성
    # exist_ok=True: 이미 있어도 오류 없음
    day_dir.mkdir(parents=True, exist_ok=True)
    pdfs_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    return day_dir, pdfs_dir, logs_dir


# ────────────────────────────────────────────────────────
# [4] 수집 상태 관리 (중복 방지)
# ────────────────────────────────────────────────────────
def load_state():
    """
    이미 수집한 메시지의 키(채널명:메시지ID) 집합을 파일에서 읽는다.
    파일이 없거나 손상됐으면 빈 집합을 반환한다.
    """
    if not STATE_FILE.exists():
        return set()

    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return set(data)
        # 리스트가 아닌 형식이면 초기화
        print("[경고] state 파일 형식이 올바르지 않습니다. 초기화합니다.")
        return set()
    except (json.JSONDecodeError, OSError) as err:
        print(f"[경고] state 파일 읽기 실패 ({err}). 새로 시작합니다.")
        return set()


def save_state(collected):
    """수집 완료된 메시지 키 집합을 파일에 저장한다."""
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(sorted(collected), f, ensure_ascii=False, indent=2)
    except OSError as err:
        print(f"[경고] state 파일 저장 실패: {err}")


def make_state_key(channel_name, message_id):
    """중복 체크에 사용하는 고유 키를 반환한다."""
    return f"{channel_name}:{message_id}"


# ────────────────────────────────────────────────────────
# [5] URL 추출
# ────────────────────────────────────────────────────────
def extract_links(text):
    """메시지 본문에서 http(s):// 로 시작하는 URL을 모두 추출해 리스트로 반환한다."""
    if not text:
        return []
    pattern = r'https?://[^\s\]\)\'"<>]+'
    return re.findall(pattern, text)


# ────────────────────────────────────────────────────────
# [6] 파일명 안전화 (Windows 금지 문자 제거)
# ────────────────────────────────────────────────────────
def sanitize_filename(name):
    """
    Windows에서 파일명에 사용할 수 없는 문자를 밑줄(_)로 바꾼다.
    금지 문자: \\ / : * ? " < > |
    """
    name = re.sub(r'[\\/:*?"<>|]', '_', name)
    name = name.strip('. ')   # 앞뒤 점·공백 제거
    return name if name else "unnamed"


# ────────────────────────────────────────────────────────
# [7] PDF 여부 판별
# ────────────────────────────────────────────────────────
def is_pdf_message(message):
    """
    메시지 첨부파일이 PDF인지 확인한다.
    - 파일명이 .pdf 로 끝나는 경우
    - MIME type 이 application/pdf 인 경우
    """
    if message.file is None:
        return False
    name      = getattr(message.file, 'name',      '') or ''
    mime_type = getattr(message.file, 'mime_type', '') or ''
    return name.lower().endswith('.pdf') or mime_type == 'application/pdf'


# ────────────────────────────────────────────────────────
# [8] 메시지 레코드 딕셔너리 생성
# ────────────────────────────────────────────────────────
def build_message_record(message, channel_input, channel_name, downloaded_path):
    """
    Telethon 메시지 객체를 JSON 저장용 딕셔너리로 변환한다.
    downloaded_path: PDF 저장 경로(str) 또는 None
    """
    # Telethon 은 UTC aware datetime 을 반환함
    date_utc = message.date.astimezone(timezone.utc)
    date_kst = message.date.astimezone(KST)

    text = message.text or message.message or ""

    # 첨부파일 정보
    has_file  = message.file is not None
    file_name = None
    mime_type = None
    file_size = None
    if has_file:
        file_name = getattr(message.file, 'name',      None)
        mime_type = getattr(message.file, 'mime_type', None)
        file_size = getattr(message.file, 'size',      None)

    return {
        "channel_input":   channel_input,
        "channel_name":    channel_name,
        "message_id":      message.id,
        "date_utc":        date_utc.isoformat(),
        "date_kst":        date_kst.isoformat(),
        "text":            text,
        "links":           extract_links(text),
        "has_file":        has_file,
        "file_name":       file_name,
        "mime_type":       mime_type,
        "file_size":       file_size,
        "is_pdf":          is_pdf_message(message),
        "downloaded_path": downloaded_path,
        "collected_at":    datetime.now(timezone.utc).isoformat(),
    }


# ────────────────────────────────────────────────────────
# [9] JSONL 파일에 한 줄 추가
# ────────────────────────────────────────────────────────
def append_jsonl(file_path, record):
    """
    JSON Lines 형식으로 파일에 레코드를 한 줄 추가한다.
    ensure_ascii=False 로 한글이 깨지지 않게 저장한다.
    """
    try:
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as err:
        raise OSError(f"messages.jsonl 저장 실패: {err}") from err


# ────────────────────────────────────────────────────────
# [10] 오류 로그 기록
# ────────────────────────────────────────────────────────
def log_error(logs_dir, msg):
    """오류 메시지를 콘솔 출력과 동시에 error.log 파일에 기록한다."""
    print(f"  [오류] {msg}")
    try:
        ts = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
        with open(logs_dir / "error.log", "a", encoding="utf-8") as f:
            f.write(f"[{ts} KST] {msg}\n")
    except OSError:
        pass  # 로그 파일 자체를 열지 못하면 조용히 무시


# ────────────────────────────────────────────────────────
# [11] 핵심 수집 로직 (비동기)
# ────────────────────────────────────────────────────────
async def collect_recent_messages(client, channel_input, channel_name, date_str, collected):
    """
    지정 채널에서 최근 HOURS_BACK 시간 이내 메시지를 수집한다.
    메시지는 messages.jsonl 에, PDF 는 pdfs/ 폴더에 저장된다.
    반환값: 통계 딕셔너리
    """
    day_dir, pdfs_dir, logs_dir = ensure_directories(date_str)
    jsonl_path = day_dir / "messages.jsonl"

    stats = {
        "total_checked":     0,
        "new_saved":         0,
        "pdf_downloaded":    0,
        "skipped_duplicate": 0,
        "errors":            0,
    }

    # 기준 시각: 현재 UTC - HOURS_BACK 시간
    cutoff = datetime.now(timezone.utc) - timedelta(hours=HOURS_BACK)
    cutoff_kst_str = cutoff.astimezone(KST).strftime("%Y-%m-%d %H:%M:%S")

    print(f"\n  채널 주소 : @{channel_name}")
    print(f"  수집 기준 : {cutoff_kst_str} KST 이후 메시지\n")

    # ── 채널 엔티티 조회 ──────────────────────────────────
    try:
        entity = await client.get_entity(channel_name)
    except UsernameNotOccupiedError:
        print(f"[오류] '@{channel_name}' 채널이 존재하지 않습니다.")
        return stats
    except UsernameInvalidError:
        print(f"[오류] '@{channel_name}' 는 유효한 채널명이 아닙니다.")
        return stats
    except ChannelPrivateError:
        print(f"[오류] '@{channel_name}' 는 비공개이거나 접근 권한이 없습니다.")
        return stats
    except Exception as err:
        print(f"[오류] 채널 접근 실패: {err}")
        return stats

    # ── 메시지 순회 (최신 → 과거 순, 기본값) ─────────────
    async for message in client.iter_messages(entity):
        try:
            # 기준 시각보다 오래된 메시지에 도달하면 중단
            msg_utc = message.date.astimezone(timezone.utc)
            if msg_utc < cutoff:
                break

            stats["total_checked"] += 1
            key = make_state_key(channel_name, message.id)

            # 이미 수집한 메시지는 건너뜀
            if key in collected:
                stats["skipped_duplicate"] += 1
                continue

            # ── PDF 다운로드 ──────────────────────────────
            downloaded_path = None
            if is_pdf_message(message):
                try:
                    orig_name = getattr(message.file, 'name', None)
                    if orig_name:
                        safe_name    = sanitize_filename(orig_name)
                        pdf_filename = f"{channel_name}_{message.id}_{safe_name}"
                    else:
                        pdf_filename = f"{channel_name}_{message.id}.pdf"

                    pdf_path = pdfs_dir / pdf_filename

                    if pdf_path.exists():
                        # 이미 파일이 있으면 재다운로드 안 함
                        print(f"  [건너뜀] 이미 존재: {pdf_filename}")
                    else:
                        print(f"  [다운로드] {pdf_filename} ...")
                        await client.download_media(message, file=str(pdf_path))
                        stats["pdf_downloaded"] += 1
                        print(f"  [완료]    저장됨 → {pdf_path}")

                    downloaded_path = str(pdf_path)

                except Exception as err:
                    log_error(logs_dir, f"PDF 다운로드 실패 (ID {message.id}): {err}")
                    stats["errors"] += 1

            # ── 메시지 레코드 저장 ────────────────────────
            record = build_message_record(
                message, channel_input, channel_name, downloaded_path
            )
            append_jsonl(jsonl_path, record)

            collected.add(key)
            stats["new_saved"] += 1

        except FloodWaitError as err:
            # 텔레그램 서버 속도 제한: 지정된 시간만큼 대기 후 계속
            wait = err.seconds
            print(f"  [대기] 텔레그램 속도 제한 → {wait}초 후 재개...")
            await asyncio.sleep(wait)

        except OSError as err:
            log_error(
                logs_dir,
                f"파일 저장 오류 (ID {getattr(message, 'id', '?')}): {err}",
            )
            stats["errors"] += 1

        except Exception as err:
            log_error(
                logs_dir,
                f"메시지 처리 오류 (ID {getattr(message, 'id', '?')}): {err}",
            )
            stats["errors"] += 1

    return stats


# ────────────────────────────────────────────────────────
# [12] 비동기 메인 함수
# ────────────────────────────────────────────────────────
async def async_main():
    """프로그램의 실제 진입점 (비동기)"""

    # 1) 설정 로드
    api_id, api_hash = load_config()

    # 2) 사용자 입력
    print("\n" + "=" * 55)
    print("   텔레그램 공개 채널 메시지·PDF 수집기")
    print("=" * 55)

    raw_input_str = input("\n수집할 텔레그램 방 주소를 입력하세요: ").strip()

    if not raw_input_str:
        print("[오류] 주소를 입력해야 합니다.")
        sys.exit(1)

    # 3) 채널명 정규화
    try:
        channel_name = normalize_channel_input(raw_input_str)
    except ValueError as err:
        print(f"[오류] {err}")
        sys.exit(1)

    print(f"\n  정규화 결과: {raw_input_str!r}  →  @{channel_name}")

    # 4) 오늘 날짜 (KST 기준으로 폴더명 결정)
    today_str = datetime.now(KST).strftime("%Y-%m-%d")

    # 5) 폴더 미리 생성
    ensure_directories(today_str)

    # 6) 중복 방지 상태 로드
    collected = load_state()
    print(f"  기존 수집 기록: {len(collected):,}건")

    # 7) Telethon 클라이언트 생성
    #    SESSION_NAME.session 파일이 없으면 자동으로 로그인 프롬프트를 띄움
    client = TelegramClient(SESSION_NAME, int(api_id), api_hash)

    try:
        print("\n  텔레그램 서버에 연결 중...")
        await client.start()  # 첫 실행 시 전화번호·인증코드 입력 요청

        me = await client.get_me()
        name_str = me.first_name or ''
        user_str = f"@{me.username}" if me.username else "(username 없음)"
        print(f"  로그인 계정: {name_str} {user_str}")

        # 8) 메시지 수집
        stats = await collect_recent_messages(
            client        = client,
            channel_input = raw_input_str,
            channel_name  = channel_name,
            date_str      = today_str,
            collected     = collected,
        )

        # 9) 상태 저장 (다음 실행 때 중복 방지에 사용)
        save_state(collected)

        # 10) 결과 요약 출력
        print("\n" + "=" * 55)
        print("   수집 완료 요약")
        print("=" * 55)
        print(f"  채널        : @{channel_name}")
        print(f"  검사 메시지  : {stats['total_checked']:,}건")
        print(f"  새로 저장   : {stats['new_saved']:,}건")
        print(f"  PDF 다운로드 : {stats['pdf_downloaded']:,}건")
        print(f"  중복 건너뜀  : {stats['skipped_duplicate']:,}건")
        print(f"  오류 발생   : {stats['errors']:,}건")
        print(f"  저장 경로   : data/{today_str}/")
        print("=" * 55 + "\n")

    except KeyboardInterrupt:
        print("\n\n  Ctrl+C 로 중단됐습니다.")
    except Exception as err:
        print(f"\n[치명적 오류] {err}")
        import traceback
        traceback.print_exc()
    finally:
        await client.disconnect()
        print("  연결 종료.")


# ────────────────────────────────────────────────────────
# [13] 프로그램 시작점
# ────────────────────────────────────────────────────────
def main():
    """
    Windows 에서 asyncio 이벤트 루프 호환성 설정 후 비동기 메인을 실행한다.
    WindowsSelectorEventLoopPolicy 를 설정하지 않으면
    일부 Windows 환경에서 Proactor 루프 관련 오류가 발생할 수 있다.
    """
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
