# collector/state_manager.py - 4개 상태 파일 통합 관리
#
# 상태 파일 구조:
#   state/messages_state.json  - 채널별 메시지 수집 이력
#   state/files_state.json     - 파일 다운로드 상태
#   state/failed_downloads.json - 다운로드 실패 목록
#   state/channels_state.json  - 채널별 수집 통계

import json
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path

KST = timezone(timedelta(hours=9))


class StateManager:
    """
    텔레그램 수집기의 모든 상태를 통합 관리하는 클래스.

    메시지 수집 상태와 파일 다운로드 상태를 분리해서 관리한다.
    → 메시지를 이미 읽었어도, 파일이 아직 다운로드 안 됐다면 독립적으로 재시도 가능.
    """

    def __init__(self, state_dir: Path):
        self.state_dir = state_dir
        self.state_dir.mkdir(parents=True, exist_ok=True)

        self._messages_path  = state_dir / "messages_state.json"
        self._files_path     = state_dir / "files_state.json"
        self._failed_path    = state_dir / "failed_downloads.json"
        self._channels_path  = state_dir / "channels_state.json"

        # 메모리 내 상태 (set 으로 관리해 O(1) 조회)
        self.messages_state:   dict = {}   # {ch_name: {"collected_message_ids": set, ...}}
        self.files_state:      dict = {}   # {file_key: {status, path, ...}}
        self.failed_downloads: dict = {}   # {file_key: {reason, retry_count, ...}}
        self.channels_state:   dict = {}   # {ch_name: {통계}}

    # ────────────────────────────────────────────────────────
    # 전체 로드 / 저장
    # ────────────────────────────────────────────────────────

    def load_all(self) -> None:
        """모든 상태 파일을 로드한다."""
        raw_msg = self._load_json(self._messages_path, {})
        # collected_message_ids 를 list → set 으로 변환해서 O(1) 조회 가능하게
        self.messages_state = {}
        for ch, data in raw_msg.items():
            entry = dict(data)
            entry["collected_message_ids"] = set(data.get("collected_message_ids", []))
            self.messages_state[ch] = entry

        self.files_state      = self._load_json(self._files_path,    {})
        self.failed_downloads = self._load_json(self._failed_path,   {})
        self.channels_state   = self._load_json(self._channels_path, {})

    def save_all(self) -> None:
        """모든 상태 파일을 저장한다."""
        # set → sorted list 로 변환해서 JSON 직렬화
        msg_to_save = {}
        for ch, data in self.messages_state.items():
            entry = dict(data)
            ids = data.get("collected_message_ids", set())
            entry["collected_message_ids"] = sorted(ids)
            msg_to_save[ch] = entry

        self._save_json(self._messages_path,  msg_to_save)
        self._save_json(self._files_path,     self.files_state)
        self._save_json(self._failed_path,    self.failed_downloads)
        self._save_json(self._channels_path,  self.channels_state)

    # ────────────────────────────────────────────────────────
    # 메시지 상태
    # ────────────────────────────────────────────────────────

    def is_message_collected(self, channel_name: str, message_id: int) -> bool:
        """해당 메시지가 이미 수집됐는지 확인한다."""
        return message_id in self.messages_state.get(
            channel_name, {}
        ).get("collected_message_ids", set())

    def mark_message_collected(self, channel_name: str, message_id: int) -> None:
        """메시지를 수집 완료 상태로 표시한다."""
        if channel_name not in self.messages_state:
            self.messages_state[channel_name] = {
                "last_checked_at":      None,
                "last_message_id":      None,
                "collected_message_ids": set(),
            }
        ch = self.messages_state[channel_name]
        ch["collected_message_ids"].add(message_id)

        if ch.get("last_message_id") is None or message_id > ch["last_message_id"]:
            ch["last_message_id"] = message_id
        ch["last_checked_at"] = datetime.now(KST).isoformat()

    # ────────────────────────────────────────────────────────
    # 파일 상태
    # ────────────────────────────────────────────────────────

    @staticmethod
    def make_file_key(channel_name: str, message_id: int, file_name: str) -> str:
        """파일 상태 조회에 사용하는 고유 키를 반환한다."""
        return f"{channel_name}:{message_id}:{file_name}"

    def get_file_status(self, file_key: str) -> dict | None:
        """파일 상태 항목을 반환한다. 없으면 None."""
        return self.files_state.get(file_key)

    def update_file_status(
        self,
        file_key:        str,
        channel_name:    str,
        message_id:      int,
        file_name:       str,
        status:          str,
        downloaded_path: str | None = None,
        error_message:   str | None = None,
        mime_type:       str | None = None,
        file_size:       int | None = None,
    ) -> None:
        """파일 상태를 생성하거나 갱신한다."""
        now_kst = datetime.now(KST).isoformat()
        entry   = self.files_state.get(file_key, {})

        entry.update({
            "channel_name":    channel_name,
            "message_id":      message_id,
            "file_name":       file_name,
            "status":          status,
            "error_message":   error_message,
        })
        if status == "downloaded":
            entry["downloaded_at"] = now_kst
        if downloaded_path is not None:
            entry["downloaded_path"] = str(downloaded_path)
        if mime_type is not None:
            entry["mime_type"] = mime_type
        if file_size is not None:
            entry["file_size"] = file_size

        self.files_state[file_key] = entry

    # ────────────────────────────────────────────────────────
    # 실패 다운로드
    # ────────────────────────────────────────────────────────

    def add_failed_download(
        self,
        file_key:      str,
        channel_name:  str,
        message_id:    int,
        file_name:     str,
        reason:        str,
        error_message: str,
    ) -> None:
        """다운로드 실패 항목을 기록한다."""
        entry = self.failed_downloads.get(file_key, {
            "channel_name": channel_name,
            "message_id":   message_id,
            "file_name":    file_name,
            "retry_count":  0,
        })
        entry["reason"]            = reason
        entry["error_message"]     = error_message
        entry["last_attempted_at"] = datetime.now(KST).isoformat()
        entry["retry_count"]       = entry.get("retry_count", 0) + 1
        self.failed_downloads[file_key] = entry

    def mark_failed_as_pending(self) -> int:
        """
        실패 항목의 files_state 상태를 pending 으로 변경한다.
        다음 collect 실행 시 재시도 대상이 된다.
        반환: 변경된 항목 수
        """
        count = 0
        for file_key in list(self.failed_downloads.keys()):
            if file_key in self.files_state:
                self.files_state[file_key]["status"] = "pending"
                count += 1
        self.failed_downloads.clear()
        return count

    # ────────────────────────────────────────────────────────
    # 채널 통계
    # ────────────────────────────────────────────────────────

    def update_channel_stats(
        self,
        channel_name:  str,
        channel_input: str,
        stats:         dict,
    ) -> None:
        """채널별 누적 통계를 갱신한다."""
        now_kst = datetime.now(KST).isoformat()
        entry   = self.channels_state.get(channel_name, {
            "channel_input":     channel_input,
            "first_collected_at": now_kst,
        })
        entry["channel_input"]          = channel_input
        entry["last_collected_at"]      = now_kst
        entry["total_checked_messages"] = entry.get("total_checked_messages", 0) + stats.get("checked_messages", 0)
        entry["total_new_messages"]     = entry.get("total_new_messages",     0) + stats.get("new_messages",     0)
        entry["total_files_found"]      = entry.get("total_files_found",      0) + stats.get("files_found",      0)
        entry["total_files_downloaded"] = entry.get("total_files_downloaded", 0) + stats.get("files_downloaded", 0)
        entry["total_errors"]           = entry.get("total_errors",           0) + stats.get("download_errors",  0)
        self.channels_state[channel_name] = entry

    # ────────────────────────────────────────────────────────
    # 상태 초기화
    # ────────────────────────────────────────────────────────

    def reset_channel(self, channel_name: str) -> None:
        """
        특정 채널의 모든 상태를 초기화한다.
        실제 다운로드 파일은 삭제하지 않는다.
        """
        # messages_state 에서 제거
        self.messages_state.pop(channel_name, None)

        # files_state 에서 해당 채널 항목 제거
        keys_to_remove = [
            k for k in self.files_state
            if k.startswith(f"{channel_name}:")
        ]
        for k in keys_to_remove:
            del self.files_state[k]

        # failed_downloads 에서 해당 채널 항목 제거
        keys_to_remove = [
            k for k in self.failed_downloads
            if k.startswith(f"{channel_name}:")
        ]
        for k in keys_to_remove:
            del self.failed_downloads[k]

        # channels_state 에서 제거
        self.channels_state.pop(channel_name, None)

    def reset_all(self) -> None:
        """모든 상태를 초기화한다. 실제 파일은 삭제하지 않는다."""
        self.messages_state.clear()
        self.files_state.clear()
        self.failed_downloads.clear()
        self.channels_state.clear()

    # ────────────────────────────────────────────────────────
    # 파일 불일치 검사
    # ────────────────────────────────────────────────────────

    def find_missing_files(self) -> list[tuple[str, dict]]:
        """
        files_state 에서 status=downloaded 인데 실제 파일이 없는 항목을 찾는다.
        반환: [(file_key, entry), ...] 목록
        """
        missing = []
        for file_key, entry in self.files_state.items():
            if entry.get("status") == "downloaded":
                path = entry.get("downloaded_path", "")
                if path and not Path(path).exists():
                    missing.append((file_key, entry))
        return missing

    def mark_missing_as_missing_file(self) -> int:
        """
        실제 파일이 없는 downloaded 항목의 상태를 missing_file 로 변경한다.
        반환: 변경된 항목 수
        """
        count = 0
        for file_key, _ in self.find_missing_files():
            self.files_state[file_key]["status"] = "missing_file"
            count += 1
        return count

    # ────────────────────────────────────────────────────────
    # 기존 형식 마이그레이션
    # ────────────────────────────────────────────────────────

    def migrate_old_state_if_needed(self) -> None:
        """
        이전 버전의 collected_messages.json / downloaded_files.json 이 있으면
        새 형식(messages_state.json / files_state.json)으로 변환한다.
        변환 실패 시 기존 파일을 .bak 으로 백업하고 새 파일을 생성한다.
        """
        old_msg_path  = self.state_dir / "collected_messages.json"
        old_file_path = self.state_dir / "downloaded_files.json"

        # messages_state 마이그레이션
        if old_msg_path.exists() and not self._messages_path.exists():
            try:
                old_data = self._load_json(old_msg_path, [])
                if isinstance(old_data, list):
                    new_state: dict = {}
                    for key in old_data:
                        # 형식: "channel_name:message_id"
                        parts = str(key).split(":", 1)
                        if len(parts) == 2:
                            ch, mid = parts
                            try:
                                mid = int(mid)
                            except ValueError:
                                continue
                            if ch not in new_state:
                                new_state[ch] = {
                                    "last_checked_at":       None,
                                    "last_message_id":       None,
                                    "collected_message_ids": set(),
                                }
                            new_state[ch]["collected_message_ids"].add(mid)
                    if new_state:
                        self.messages_state = new_state
                        print(f"  [마이그레이션] collected_messages.json → messages_state.json 변환 완료")
                        shutil.copy2(old_msg_path, old_msg_path.with_suffix(".json.bak"))
            except Exception as err:
                print(f"  [경고] messages 마이그레이션 실패: {err}")

        # files_state 마이그레이션
        if old_file_path.exists() and not self._files_path.exists():
            try:
                old_data = self._load_json(old_file_path, [])
                if isinstance(old_data, list):
                    new_files: dict = {}
                    for key in old_data:
                        # 형식: "channel_name:message_id:file_name"
                        parts = str(key).split(":", 2)
                        if len(parts) == 3:
                            ch, mid, fname = parts
                            new_files[key] = {
                                "channel_name":   ch,
                                "message_id":     int(mid) if mid.isdigit() else mid,
                                "file_name":      fname,
                                "status":         "downloaded",
                                "downloaded_path": None,
                                "downloaded_at":  None,
                                "error_message":  None,
                            }
                    if new_files:
                        self.files_state = new_files
                        print(f"  [마이그레이션] downloaded_files.json → files_state.json 변환 완료")
                        shutil.copy2(old_file_path, old_file_path.with_suffix(".json.bak"))
            except Exception as err:
                print(f"  [경고] files 마이그레이션 실패: {err}")

    # ────────────────────────────────────────────────────────
    # 내부 헬퍼
    # ────────────────────────────────────────────────────────

    def _load_json(self, path: Path, default):
        """JSON 파일 로드. 손상 시 .bak 백업 후 default 반환."""
        if not path.exists():
            return default
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as err:
            backup = path.with_suffix(".json.bak")
            try:
                shutil.copy2(path, backup)
                print(f"  [경고] {path.name} 손상됨. {backup.name} 으로 백업하고 초기화합니다.")
            except OSError:
                pass
            return default

    def _save_json(self, path: Path, data) -> None:
        """JSON 파일 저장."""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except OSError as err:
            print(f"  [경고] {path.name} 저장 실패: {err}")
