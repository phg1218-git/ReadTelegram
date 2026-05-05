# 텔레그램 공개 채널 메시지·파일 수집기

공개 텔레그램 채널에서 메시지와 첨부파일(PDF, 엑셀, 이미지 등)을 수집해 로컬 폴더에 저장하는 Python 프로그램입니다.  
GUI(`TelegramCollector.exe`) 또는 CLI 스크립트로 실행할 수 있습니다.

---

## GUI 빠른 시작 (TelegramCollector.exe)

Python 없이 바로 실행하려면 빌드된 `TelegramCollector.exe`를 사용하세요.

### 실행 순서

1. `TelegramCollector.exe`를 실행한다.
2. **환경설정** 영역에 API ID, API Hash, 채널 목록 등을 입력한다.
3. **설정 저장** 버튼을 클릭해 `settings.json`에 저장한다.
4. **Telegram 로그인/연결 테스트** 버튼을 클릭해 최초 1회 로그인한다.
   - 팝업에 국가코드 포함 전화번호 → 인증코드 → (2FA 사용 시) 비밀번호를 순서대로 입력한다.
   - 로그인 성공 시 `telegram_session.session` 파일이 생성되고, 이후 자동 로그인된다.
5. **수집 시작** 버튼을 클릭한다.
6. **실행 로그** 영역에서 수집 진행 상황을 실시간으로 확인한다.

### 화면 구성

| 영역 | 주요 기능 |
|------|----------|
| 환경설정 | API ID/Hash, 채널 목록, 허용 확장자, 파일 크기 제한 등 설정 |
| 상태 초기화 | 채널별 또는 전체 수집·다운로드 상태 초기화 |
| 데이터 수집 | 수집 시작/중지, 저장 폴더 열기 |
| 실행 로그 | 실시간 진행 로그, 저장 기능 |

### 환경설정 항목 설명

| 항목 | 설명 |
|------|------|
| API ID | my.telegram.org 에서 발급한 숫자 ID |
| API Hash | my.telegram.org 에서 발급한 해시 문자열 |
| 수집 시간 | 최근 몇 시간 이내 메시지를 수집할지 (기본 12시간) |
| 채널 목록 | 한 줄에 채널 하나씩 입력 (https://t.me/..., @채널명 등 모두 가능) |
| 허용 확장자 | 비워두거나 "전체 허용" 체크 시 모든 파일 다운로드. `.pdf, .pptx`처럼 입력 시 해당 확장자만 다운로드 |
| 최대 파일 크기 | MB 단위. 0이면 제한 없음 |
| 파일 보관 기간 | cleanup_files.py 또는 cli에서 오래된 파일 정리 시 기준 (일 단위) |

### 직접 입력 채널 수집

"데이터 수집" 영역에서 **직접 입력 채널** 라디오버튼을 선택하고 채널 주소를 입력하면 해당 채널만 수집합니다.

### 초기화 기능

| 버튼 | 동작 |
|------|------|
| 선택 채널 다운로드 초기화 | 해당 채널의 파일 다운로드 상태만 삭제 (메시지 이력 유지) |
| 선택 채널 전체 초기화 | 해당 채널의 메시지·파일·통계 전체 삭제 |
| 전체 다운로드 초기화 | 모든 채널의 파일 다운로드 상태 삭제 (메시지 이력 유지) |
| 전체 수집 초기화 | 모든 상태 삭제 (다음 수집 시 처음부터 재수집) |

> **주의:** 초기화는 수집 상태 기록만 삭제합니다. 실제 다운로드된 파일은 삭제되지 않습니다.

### 보안 주의사항

- **`telegram_session.session`** 파일에는 내 텔레그램 계정 인증 정보가 담겨 있습니다.  
  이 파일을 타인에게 공유하거나 공개 저장소에 올리지 마세요.  
  유출 시 텔레그램 앱 → 설정 → 기기 목록에서 해당 세션을 즉시 종료하세요.
- **`settings.json`**, **`.env`** 에는 API ID와 API Hash가 포함됩니다.  
  배포 시 이 파일들을 반드시 제거하거나 본인 정보를 삭제하세요.
- API ID/Hash는 코드에 하드코딩하지 않습니다. GUI 설정 화면 또는 `.env` 파일을 통해서만 입력하세요.

### Windows Defender 오탐 안내

PyInstaller로 빌드한 exe는 Windows Defender 등 일부 백신에서 오탐(false positive)으로 탐지될 수 있습니다.  
이는 PyInstaller 특성상 발생하는 현상이며, 소스코드를 직접 확인하거나 신뢰하는 경우에만 실행하세요.  
오탐 시 백신 예외 처리 후 실행하거나, Python에서 직접 `python telegram_collector_gui.py`로 실행하세요.

### 수집 자료 사용 안내

수집한 자료는 **본인이 접근 가능한 공개 채널 또는 권한 있는 채널**에서만 수집하고,  
**개인 분석 목적**으로만 사용하세요. 타인의 저작물을 무단 배포하거나 상업적으로 이용하지 마세요.

---

## 목차

1. [프로그램 목적](#1-프로그램-목적)
2. [Bot API가 아닌 Telethon을 쓰는 이유](#2-bot-api가-아닌-telethon을-쓰는-이유)
3. [API 키 발급 방법](#3-api-키-발급-방법)
4. [환경 설정 — .env 파일 작성](#4-환경-설정--env-파일-작성)
5. [패키지 설치](#5-패키지-설치)
6. [첫 실행 — 텔레그램 로그인](#6-첫-실행--텔레그램-로그인)
7. [실행 방법](#7-실행-방법)
8. [파일 다운로드 정책](#8-파일-다운로드-정책)
9. [저장 폴더 구조](#9-저장-폴더-구조)
10. [상태 관리 CLI](#10-상태-관리-cli)
11. [오래된 파일 정리](#11-오래된-파일-정리)
12. [exe 파일 빌드](#12-exe-파일-빌드)
13. [주의 사항](#13-주의-사항)
14. [파일 구성](#14-파일-구성)

---

## 1. 프로그램 목적

- 공개 텔레그램 채널에서 **최근 N시간** 동안의 메시지와 첨부파일을 자동으로 수집합니다.
- 수집한 메시지는 `messages.jsonl`에, 파일 메타데이터는 `file_index.jsonl`에 저장합니다.
- PDF, 엑셀, 파워포인트, 워드, 이미지, 동영상 등 **모든 첨부파일 유형**을 다운로드합니다.
- 한 번 수집한 메시지·파일은 다시 저장하지 않습니다 (중복 방지).
- **메시지 수집 상태**와 **파일 다운로드 상태**를 독립적으로 관리해 파일만 따로 재시도할 수 있습니다.

---

## 2. Bot API가 아닌 Telethon을 쓰는 이유

| 구분 | Bot API | Telethon (MTProto) |
|------|---------|-------------------|
| 접근 방식 | 봇 계정 사용 | 개인 계정 사용 |
| 채널 접근 | 봇을 채널 관리자로 추가해야 함 | 공개 채널은 별도 추가 없이 접근 가능 |
| 제약 | 채널에 봇을 넣을 수 없으면 사용 불가 | 내가 접근 권한을 가진 채널이면 수집 가능 |

이 프로그램은 **내 텔레그램 계정**으로 로그인해서 수집하므로,  
채널에 봇을 추가하지 않아도 공개 채널의 내용을 읽을 수 있습니다.

---

## 3. API 키 발급 방법

Telegram MTProto API 를 쓰려면 **개인 API ID와 API Hash**가 필요합니다.

### 발급 절차

1. 브라우저에서 [https://my.telegram.org](https://my.telegram.org) 에 접속합니다.
2. 본인의 텔레그램 **전화번호(국가코드 포함)** 를 입력하고 로그인합니다.  
   예) `+821012345678`
3. 메인 메뉴에서 **"API development tools"** 를 클릭합니다.
4. 앱 정보를 입력합니다. (App title, Short name 은 임의로 작성 가능)
5. 페이지 하단의 **`App api_id`** 와 **`App api_hash`** 를 복사해 둡니다.

> **주의:** API 키는 외부에 공개하지 마세요. `.env` 파일은 `.gitignore` 에 추가하세요.

---

## 4. 환경 설정 — .env 파일 작성

`.env.example` 파일을 복사해서 `.env` 파일을 만든 뒤 실제 값을 입력합니다.

**Windows cmd:**
```cmd
copy .env.example .env
```

**Windows PowerShell:**
```powershell
Copy-Item .env.example .env
```

`.env` 파일을 메모장이나 VS Code 로 열어 아래처럼 수정하세요.

```
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=abcdef1234567890abcdef1234567890

TELEGRAM_LOOKBACK_HOURS=12
TELEGRAM_CHANNELS=https://t.me/channel_a,@channel_b

DOWNLOAD_FILE_TYPES=all
MAX_FILE_SIZE_MB=0
KEEP_ORIGINAL_FILE_DAYS=30
KEEP_CONSOLE_OPEN=true
```

### 변수 설명

| 변수 | 필수 | 기본값 | 설명 |
|------|------|--------|------|
| `TELEGRAM_API_ID` | 필수 | — | my.telegram.org 에서 발급한 숫자 ID |
| `TELEGRAM_API_HASH` | 필수 | — | my.telegram.org 에서 발급한 해시 문자열 |
| `TELEGRAM_LOOKBACK_HOURS` | 선택 | `12` | 수집할 과거 시간 범위 |
| `TELEGRAM_CHANNELS` | 선택* | — | 고정 채널 목록 (쉼표 구분) |
| `DOWNLOAD_FILE_TYPES` | 선택 | `all` | 다운로드 파일 유형: `all` / `document_only` / `media_only` |
| `MAX_FILE_SIZE_MB` | 선택 | `0` | 다운로드 최대 크기 (MB). `0` = 제한 없음 |
| `KEEP_ORIGINAL_FILE_DAYS` | 선택 | `30` | 파일 보관 기간 (일). `cleanup_files.py` 에서 사용 |
| `KEEP_CONSOLE_OPEN` | 선택 | `true` | exe 실행 후 콘솔 창 유지 여부 |

> `*` `collect_config_channels.py` 실행 시 필수

### DOWNLOAD_FILE_TYPES 옵션

| 값 | 다운로드 대상 |
|----|-------------|
| `all` | 모든 첨부파일 |
| `document_only` | PDF, Excel, PPT, Word, TXT, HWP 등 문서류 |
| `media_only` | 이미지(JPG, PNG, GIF 등), 동영상(MP4, AVI 등) |

### TELEGRAM_CHANNELS 작성법

쉼표로 구분해서 여러 방 주소를 입력합니다. 다음 형식 모두 사용 가능합니다.

```
TELEGRAM_CHANNELS=https://t.me/channel_a,t.me/channel_b,@channel_c,channel_d
```

---

## 5. 패키지 설치

Python **3.10 이상**이 설치돼 있어야 합니다.

```cmd
pip install -r requirements.txt
```

---

## 6. 첫 실행 — 텔레그램 로그인

처음 실행하면 텔레그램 계정 로그인 과정이 자동으로 진행됩니다.

```
Please enter your phone (or bot token): +821012345678
Please enter the code you received: 12345
```

1. **국가 코드 포함** 전화번호를 입력합니다. (한국: `+82` 로 시작)
2. 텔레그램 앱 또는 SMS 로 받은 **인증 코드**를 입력합니다.
3. 2단계 인증(2FA) 사용 중이면 **비밀번호**도 입력합니다.

로그인 성공 시 `telegram_session.session` 파일이 생성됩니다.  
**이후 실행에서는 로그인 없이 바로 시작됩니다.**

---

## 7. 실행 방법

### 방식 1 — 고정 채널 전체 수집

`.env` 의 `TELEGRAM_CHANNELS` 에 등록된 채널들을 한 번에 수집합니다.

```cmd
python collect_config_channels.py
```

```
=======================================================
  텔레그램 고정 채널 일괄 수집 시작
  수집 기준: 최근 12시간
  대상 채널 수: 2개
=======================================================

[1/2] https://t.me/channel_a 수집 중...
  검사 메시지    : 300건
  신규 메시지    : 280건
  파일 발견      : 45건
  파일 다운로드  : 38건
  파일 건너뜀    : 7건
```

### 방식 2 — 직접 입력한 채널 1개 수집

실행 후 주소를 직접 입력합니다.

```cmd
python collect_manual_channel.py
```

```
수집할 텔레그램 방 주소를 입력하세요: https://t.me/channel_a
```

지원하는 주소 형식:

| 입력값 | 인식 결과 |
|--------|-----------|
| `https://t.me/channel_a` | `channel_a` |
| `t.me/channel_a` | `channel_a` |
| `@channel_a` | `channel_a` |
| `channel_a` | `channel_a` |

---

## 8. 파일 다운로드 정책

모든 메시지의 **메타데이터는 항상 저장**됩니다.  
실제 파일 다운로드는 아래 조건을 확인합니다.

| 조건 | 동작 |
|------|------|
| 파일 유형 필터 (`DOWNLOAD_FILE_TYPES`) | 설정에 맞지 않는 유형은 건너뜀 |
| 용량 제한 (`MAX_FILE_SIZE_MB` > 0) | 초과 파일은 건너뜀, `file_index.jsonl` 에 기록 |
| 중복 제외 | 이미 다운로드한 파일은 건너뜀 |
| 파일 삭제 후 재수집 | 파일이 삭제됐으면 자동으로 재다운로드 |

다운로드된 파일명 형식: `{채널명}_{메시지ID}_{원본파일명}`

---

## 9. 저장 폴더 구조

```
ReadTelegram/
├── collect_config_channels.py  ← 고정 채널 수집 실행 파일
├── collect_manual_channel.py   ← 직접 입력 수집 실행 파일
├── manage_state.py             ← 상태 관리 CLI
├── cleanup_files.py            ← 오래된 파일 정리
├── build_exe.py                ← exe 빌드 스크립트
│
├── collector/                  ← 공통 수집 모듈
│   ├── __init__.py
│   ├── config.py               ← 설정 로드
│   ├── utils.py                ← 공통 유틸리티
│   ├── storage.py              ← 파일 입출력
│   ├── rules.py                ← 다운로드 조건 판단
│   ├── state_manager.py        ← 4개 상태 파일 통합 관리
│   └── telegram_client.py      ← Telethon 수집 로직
│
├── config/
│   └── keywords.txt            ← 향후 태깅 목적 키워드 (현재 미사용)
│
├── .env                        ← 직접 만들어야 함 (API 키, .gitignore 에 추가)
├── .env.example                ← .env 템플릿
├── requirements.txt
├── telegram_session.session    ← 로그인 세션 (자동 생성)
│
├── state/
│   ├── messages_state.json     ← 채널별 메시지 수집 이력
│   ├── files_state.json        ← 파일 다운로드 상태
│   ├── failed_downloads.json   ← 다운로드 실패 목록
│   └── channels_state.json     ← 채널별 누적 통계
│
└── data/
    └── 2025-01-15/             ← 수집 날짜별 폴더 (KST 기준)
        ├── messages.jsonl      ← 전체 메시지 (JSON Lines)
        ├── file_index.jsonl    ← 다운로드한 파일 메타데이터
        ├── downloaded_files/   ← 실제 다운로드된 파일
        └── logs/
            └── error.log       ← 오류 로그
```

---

## 10. 상태 관리 CLI

`manage_state.py` 로 수집 상태를 검사하고 초기화할 수 있습니다.

### 전체 채널 현황 보기

```cmd
python manage_state.py status
```

### 특정 채널 상세 보기

```cmd
python manage_state.py status --channel channel_a
python manage_state.py status -c @channel_a
```

### 특정 채널 상태 초기화

```cmd
python manage_state.py reset-channel channel_a
```

> 실제 다운로드 파일은 삭제되지 않습니다. 다음 실행 시 해당 채널 메시지를 처음부터 다시 수집합니다.

### 전체 상태 초기화

```cmd
python manage_state.py reset-all
```

### 실패한 다운로드 재시도 등록

```cmd
python manage_state.py retry-failed
```

다음 수집 실행 시 실패했던 파일들을 다시 시도합니다.

### 파일 존재 여부 검사

```cmd
python manage_state.py verify-files         # 불일치 목록만 출력
python manage_state.py verify-files --fix   # 상태도 자동 수정
```

`files_state.json` 에 downloaded 로 기록됐지만 실제로 없는 파일을 찾습니다.  
`--fix` 옵션을 쓰면 상태를 `missing_file` 로 변경해 다음 수집 시 재다운로드합니다.

---

## 11. 오래된 파일 정리

`KEEP_ORIGINAL_FILE_DAYS` 일이 지난 다운로드 파일을 정리합니다.  
메시지·인덱스 파일(`messages.jsonl`, `file_index.jsonl`)은 삭제하지 않습니다.

```cmd
python cleanup_files.py
```

```
=======================================================
  다운로드 파일 정리
  보관 기간 설정: 30일
=======================================================

  삭제 대상: 15개 파일  (총 87.3 MB)

    2025-01-08/downloaded_files/channel_a_12345_보고서.pdf  (3.2 MB)
    ...

  위 파일들을 삭제하시겠습니까? (y/N): y
  삭제 완료: 15개 | 실패: 0개
  파일 상태 갱신: 15건 (deleted 로 변경)
```

삭제 후 `files_state.json` 의 해당 항목 상태가 `deleted` 로 갱신됩니다.

---

## 12. exe 파일 빌드

Python 없이 실행할 수 있는 exe 파일을 빌드합니다.

```cmd
pip install pyinstaller
python build_exe.py
```

빌드 결과는 `dist/telegram_collector_package/` 폴더에 생성됩니다.

```
dist/telegram_collector_package/
├── collect_config_channels.exe
├── collect_manual_channel.exe
├── manage_state.exe
└── cleanup_files.exe
```

exe 파일을 배포할 때는 `.env` 파일과 `telegram_session.session` 파일을 함께 복사해야 합니다.

---

## 13. 주의 사항

### 접근 가능한 채널
- **공개 채널** 은 가입 없이 누구나 접근할 수 있습니다.
- **비공개 채널/그룹** 은 본인이 **이미 가입돼 있어야** 수집 가능합니다.
- 가입하지 않은 비공개 방의 내용은 수집할 수 없습니다.

### 속도 제한
- 너무 짧은 간격으로 반복 실행하면 텔레그램이 요청을 일시 차단합니다.
- 동일 채널을 반복 수집할 때는 **최소 5~10분 간격**을 권장합니다.
- 속도 제한이 걸리면 프로그램이 자동으로 대기 후 재개하거나, 300초 초과 시 해당 채널만 건너뜁니다.

### 사용 목적
- 수집한 데이터는 **개인 분석 목적**으로만 사용하세요.
- 타인의 저작물, 개인정보 등을 무단 배포하거나 상업적으로 이용하지 마세요.
- 텔레그램 이용 약관([Terms of Service](https://telegram.org/tos))을 준수하세요.

### 이 프로그램이 하지 않는 것
- DM(개인 메시지) 자동 발송
- 채널 가입자 목록 수집
- 다른 계정 정보 수집
- 비공개 방 우회 접근

### 세션 파일 보안
- `telegram_session.session` 파일에는 내 계정 로그인 정보가 담겨 있습니다.
- 이 파일을 타인에게 공유하거나 공개 저장소에 올리지 마세요.
- 유출된 경우 텔레그램 앱 → 설정 → 기기 목록에서 해당 세션을 종료하세요.

---

## 14. 파일 구성

| 파일 | 역할 |
|------|------|
| `collect_config_channels.py` | `.env` 의 `TELEGRAM_CHANNELS` 채널들을 일괄 수집 |
| `collect_manual_channel.py` | 실행 시 주소를 입력해 채널 1개 수집 |
| `manage_state.py` | 수집 상태 조회·초기화·검증 CLI |
| `cleanup_files.py` | 보관 기간 지난 다운로드 파일 삭제 |
| `build_exe.py` | PyInstaller 로 4개 exe 파일 빌드 |
| `collector/config.py` | `.env` 설정 로드 |
| `collector/utils.py` | 채널명 정규화, 링크 추출, 파일 분류 등 유틸리티 |
| `collector/storage.py` | 디렉토리 생성, JSONL 저장, 오류 로그 |
| `collector/rules.py` | 파일 다운로드 조건 판단 |
| `collector/state_manager.py` | 4개 상태 파일 통합 관리 |
| `collector/telegram_client.py` | Telethon 메시지·파일 수집 로직 |
