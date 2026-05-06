#!/usr/bin/env python3
# build_exe.py - PyInstaller 로 모든 exe 파일을 빌드한다.
#
# 빌드 결과: dist/telegram_collector_package/
#   TelegramCollector.exe          ← GUI (콘솔 없음)
#   TelegramCollector_debug.exe    ← GUI (콘솔 있음, 디버깅용)
#   collect_config_channels.exe    ← CLI 고정채널 수집
#   collect_manual_channel.exe     ← CLI 수동채널 수집
#   manage_state.exe               ← 상태 관리 CLI
#   cleanup_files.exe              ← 오래된 파일 정리 CLI
#
# 사용법:
#   python build_exe.py            ← 전체 빌드
#   python build_exe.py --gui-only ← GUI exe 만 빌드
#   python build_exe.py --cli-only ← CLI exe 만 빌드

import shutil
import subprocess
import sys
from pathlib import Path

_DIST_DIR = Path("dist") / "telegram_collector_package"

# GUI 빌드 대상
_GUI_TARGETS = [
    {
        "script": "telegram_collector_gui.py",
        "name":   "TelegramCollector",
        "console": False,
    },
    {
        "script": "telegram_collector_gui.py",
        "name":   "TelegramCollector_debug",
        "console": True,
    },
]

# CLI 빌드 대상
_CLI_TARGETS = [
    ("collect_config_channels.py", "collect_config_channels"),
    ("collect_manual_channel.py",  "collect_manual_channel"),
    ("manage_state.py",            "manage_state"),
    ("cleanup_files.py",           "cleanup_files"),
]

_COMMON_FLAGS = [
    "--noconfirm",
    f"--distpath={_DIST_DIR}",
    "--workpath=build",
    "--specpath=build",
    "--clean",
]


def check_pyinstaller() -> str:
    """PyInstaller 설치 여부를 확인하고 버전 문자열을 반환한다."""
    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--version"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print("\n[오류] PyInstaller 가 설치되지 않았습니다.")
        print("  설치: pip install pyinstaller")
        sys.exit(1)
    return result.stdout.strip()


def build_gui(target: dict) -> bool:
    name    = target["name"]
    script  = target["script"]
    console = target["console"]

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        *_COMMON_FLAGS,
        f"--name={name}",
        *([] if console else ["--noconsole"]),
        "--collect-all", "customtkinter",   # CTk 테마/이미지 리소스 포함
        script,
    ]
    print(f"\n  빌드 중: {name}.exe  ({'콘솔' if console else 'GUI'})")
    result = subprocess.run(cmd, check=False)
    ok = result.returncode == 0
    if ok:
        exe = _DIST_DIR / f"{name}.exe"
        size_mb = exe.stat().st_size / 1_048_576 if exe.exists() else 0
        print(f"  [완료] {name}.exe  ({size_mb:.1f} MB)")
    else:
        print(f"  [실패] {name}.exe 빌드 실패 (코드 {result.returncode})")
    return ok


def build_cli(script: str, name: str) -> bool:
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        *_COMMON_FLAGS,
        f"--name={name}",
        script,
    ]
    print(f"\n  빌드 중: {name}.exe")
    result = subprocess.run(cmd, check=False)
    ok = result.returncode == 0
    if ok:
        exe = _DIST_DIR / f"{name}.exe"
        size_mb = exe.stat().st_size / 1_048_576 if exe.exists() else 0
        print(f"  [완료] {name}.exe  ({size_mb:.1f} MB)")
    else:
        print(f"  [실패] {name}.exe 빌드 실패 (코드 {result.returncode})")
    return ok


def copy_dist_assets() -> None:
    """배포에 필요한 설정 파일 및 폴더를 dist 디렉토리에 복사한다."""
    assets = [
        (".env.example", ".env.example"),
        ("README.md",    "README.md"),
    ]
    for src, dst in assets:
        src_path = Path(src)
        dst_path = _DIST_DIR / dst
        if src_path.exists():
            shutil.copy2(src_path, dst_path)
            print(f"  복사: {src} → dist/{dst}")

    # config/ 폴더
    config_src = Path("config")
    config_dst = _DIST_DIR / "config"
    if config_src.exists():
        shutil.copytree(config_src, config_dst, dirs_exist_ok=True)
        print("  복사: config/")

    # data/, state/ 빈 폴더 생성
    for folder in ["data", "state", "logs"]:
        (_DIST_DIR / folder).mkdir(exist_ok=True)
    print("  생성: data/, state/, logs/")


def main() -> None:
    gui_only = "--gui-only" in sys.argv
    cli_only = "--cli-only" in sys.argv

    print("\n" + "=" * 60)
    print("  텔레그램 수집기 exe 빌드")
    print(f"  출력 디렉토리: {_DIST_DIR.resolve()}")
    print("=" * 60)

    version = check_pyinstaller()
    print(f"\n  PyInstaller 버전: {version}")

    _DIST_DIR.mkdir(parents=True, exist_ok=True)

    results: list[tuple[str, bool]] = []

    if not cli_only:
        print("\n── GUI exe 빌드 ──")
        for target in _GUI_TARGETS:
            if not Path(target["script"]).exists():
                print(f"  [건너뜀] {target['script']} 없음")
                results.append((target["name"], False))
                continue
            ok = build_gui(target)
            results.append((target["name"], ok))

    if not gui_only:
        print("\n── CLI exe 빌드 ──")
        for script, name in _CLI_TARGETS:
            if not Path(script).exists():
                print(f"  [건너뜀] {script} 없음")
                results.append((name, False))
                continue
            ok = build_cli(script, name)
            results.append((name, ok))

    print("\n── 배포 파일 복사 ──")
    copy_dist_assets()

    # 결과 요약
    print("\n" + "=" * 60)
    print("  빌드 결과")
    print("=" * 60)
    success_count = 0
    for name, ok in results:
        status = "OK  " if ok else "FAIL"
        print(f"  [{status}] {name}.exe")
        if ok:
            success_count += 1

    print(f"\n  성공: {success_count}/{len(results)}")
    if success_count == len(results):
        print(f"  출력 폴더: {_DIST_DIR.resolve()}")
    print()


if __name__ == "__main__":
    main()
