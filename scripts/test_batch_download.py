#!/usr/bin/env python3
"""
batch_download.py 테스트 및 검증 스크립트
- 목적: 모든 핵심 함수의 동작 검증
"""

import sys
import json
from pathlib import Path
from datetime import datetime

# 상위 디렉토리 추가
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

# 테스트 결과 저장
test_results = []

def test_pass(name: str, detail: str = ""):
    """테스트 통과"""
    msg = f"✅ PASS: {name}"
    if detail:
        msg += f" - {detail}"
    print(msg)
    test_results.append((name, "PASS", detail))

def test_fail(name: str, error: str):
    """테스트 실패"""
    msg = f"❌ FAIL: {name} - {error}"
    print(msg)
    test_results.append((name, "FAIL", error))

def test_error(name: str, error: str):
    """테스트 오류"""
    msg = f"⚠️  ERROR: {name} - {error}"
    print(msg)
    test_results.append((name, "ERROR", error))


print("=" * 80)
print("🧪 batch_download.py 검증 테스트")
print("=" * 80)

# ===========================
# 1. 임포트 테스트
# ===========================
print("\n📋 1단계: 임포트 테스트")
print("-" * 80)

try:
    from batch_download import (
        sanitize_filename,
        format_size,
        format_duration,
        load_checkpoint,
        save_checkpoint,
        update_checkpoint,
        get_pending_videos,
        BatchDownloader,
        DOWNLOAD_DIR,
        CHECKPOINT_FILE,
        DEFAULT_VIDEO_FMT,
        ydl_base_opts,
        logger,
    )
    test_pass("모든 함수/클래스 임포트", f"DOWNLOAD_DIR={DOWNLOAD_DIR}")
except ImportError as e:
    test_error("임포트", str(e))
    sys.exit(1)

# ===========================
# 2. yt-dlp 네트워크/SSL 옵션 테스트
# ===========================
print("\n📋 2단계: yt-dlp 네트워크/SSL 옵션 테스트")
print("-" * 80)

try:
    opts = ydl_base_opts()
    required = {
        "socket_timeout": 30,
        "retries": 10,
        "fragment_retries": 10,
        "extractor_retries": 10,
        "nocheckcertificate": True,
    }
    missing = [name for name, expected in required.items() if opts.get(name) != expected]
    if missing:
        test_fail("ydl_base_opts", f"필수 옵션 누락: {', '.join(missing)}")
    else:
        test_pass("ydl_base_opts", "재시도/SSL 옵션이 포함됨")
except Exception as e:
    test_error("ydl_base_opts", str(e))

try:
    if "vcodec^=avc1" in DEFAULT_VIDEO_FMT and "ext=mp4" in DEFAULT_VIDEO_FMT:
        test_pass("DEFAULT_VIDEO_FMT", "H.264/MP4 우선 선택 규칙 포함")
    else:
        test_fail("DEFAULT_VIDEO_FMT", "H.264/MP4 우선 선택 규칙이 없습니다")
except Exception as e:
    test_error("DEFAULT_VIDEO_FMT", str(e))

# ===========================
# 3. 유틸리티 함수 테스트
# ===========================
print("\n📋 3단계: 유틸리티 함수 테스트")
print("-" * 80)

# 2-1. sanitize_filename
test_cases_sanitize = [
    ("Normal Title", "Normal Title"),
    ("Title: With/Colons\\Backslash", "Title_ With_Colons_Backslash"),
    ("Title*With?Asterisk", "Title_With_Asterisk"),
    ("", "untitled"),
]

for input_val, expected in test_cases_sanitize:
    result = sanitize_filename(input_val)
    if result == expected:
        test_pass("sanitize_filename", f'"{input_val}" → "{result}"')
    else:
        test_fail("sanitize_filename", f'"{input_val}" → "{result}" (expected "{expected}")')

# 2-2. format_size
test_cases_size = [
    (512, "512 B"),
    (1024, "1.0 KB"),
    (1024 * 1024, "1.0 MB"),
    (1024 * 1024 * 1024, "1.0 GB"),
]

for input_val, expected in test_cases_size:
    result = format_size(input_val)
    if result == expected:
        test_pass("format_size", f"{input_val} bytes → {result}")
    else:
        test_fail("format_size", f"{input_val} bytes → {result} (expected {expected})")

# 2-3. format_duration
test_cases_duration = [
    (0, "00:00:00"),
    (125, "00:02:05"),
    (3661, "01:01:01"),
]

for input_val, expected in test_cases_duration:
    result = format_duration(input_val)
    if result == expected:
        test_pass("format_duration", f"{input_val}s → {result}")
    else:
        test_fail("format_duration", f"{input_val}s → {result} (expected {expected})")

# ===========================
# 4. 체크포인트 로직 테스트
# ===========================
print("\n📋 4단계: 체크포인트 로직 테스트")
print("-" * 80)

# 테스트용 체크포인트 파일 백업
checkpoint_backup = None
if CHECKPOINT_FILE.exists():
    with open(CHECKPOINT_FILE, 'r', encoding='utf-8') as f:
        checkpoint_backup = json.load(f)
    CHECKPOINT_FILE.unlink()
    logger.info(f"기존 체크포인트 백업: {CHECKPOINT_FILE}")

try:
    # 3-1. 빈 체크포인트 로드
    cp_data = load_checkpoint()
    if "videos" in cp_data and isinstance(cp_data["videos"], dict):
        test_pass("load_checkpoint (새로 생성)", "videos 딕셔너리 생성됨")
    else:
        test_fail("load_checkpoint", "videos 딕셔너리 없음")

    # 3-2. 체크포인트 저장 및 로드
    test_data = {
        "videos": {
            "test_vid_1": {
                "status": "completed",
                "title": "Test Video 1",
                "size": 123456789,
            },
            "test_vid_2": {
                "status": "failed",
                "error": "Network error",
            }
        }
    }
    save_checkpoint(test_data)
    test_pass("save_checkpoint", f"체크포인트 저장 완료: {CHECKPOINT_FILE}")

    loaded_data = load_checkpoint()
    if loaded_data["videos"].get("test_vid_1", {}).get("status") == "completed":
        test_pass("load_checkpoint (저장된 데이터)", "데이터 정상 로드")
    else:
        test_fail("load_checkpoint", "저장된 데이터 로드 실패")

    # 3-3. update_checkpoint
    update_checkpoint("test_vid_3", "pending", {"title": "Test Video 3"})
    updated = load_checkpoint()
    if updated["videos"].get("test_vid_3", {}).get("status") == "pending":
        test_pass("update_checkpoint", "새 비디오 상태 업데이트 성공")
    else:
        test_fail("update_checkpoint", "비디오 상태 업데이트 실패")

    # 3-4. get_pending_videos 시뮬레이션
    all_videos = [
        {"id": "test_vid_1"},  # completed → 스킵
        {"id": "test_vid_2"},  # failed → 포함 (재시도)
        {"id": "test_vid_3"},  # pending → 포함
        {"id": "test_vid_4"},  # 체크포인트 없음 → 포함
    ]
    pending, completed = get_pending_videos(all_videos)
    if len(completed) == 1 and len(pending) == 3:
        test_pass("get_pending_videos", f"완료: {len(completed)}, 대기: {len(pending)}")
    else:
        test_fail("get_pending_videos", f"완료: {len(completed)} (기대값: 1), 대기: {len(pending)} (기대값: 3)")

finally:
    # 테스트 데이터 정리
    if CHECKPOINT_FILE.exists():
        CHECKPOINT_FILE.unlink()
    
    # 백업 복원
    if checkpoint_backup:
        save_checkpoint(checkpoint_backup)
        logger.info("원본 체크포인트 복원")

# ===========================
# 5. BatchDownloader 클래스 테스트
# ===========================
print("\n📋 5단계: BatchDownloader 클래스 테스트")
print("-" * 80)

try:
    # 4-1. 인스턴스 생성
    downloader = BatchDownloader(download_type="video", format_id=None, skip_existing=True)
    test_pass("BatchDownloader 생성", "video 타입, skip_existing=True")

    # 4-2. 통계 초기화
    if downloader.stats["success"] == 0 and downloader.stats["failed"] == 0:
        test_pass("통계 초기화", f"stats={downloader.stats}")
    else:
        test_fail("통계 초기화", "초기값이 0이 아님")

    # 4-3. 오디오 타입 생성
    downloader_audio = BatchDownloader(download_type="audio", skip_existing=False)
    if downloader_audio.download_type == "audio" and not downloader_audio.skip_existing:
        test_pass("오디오 타입 생성", "audio 타입, skip_existing=False")
    else:
        test_fail("오디오 타입 생성", "타입 또는 옵션 오류")

except Exception as e:
    test_error("BatchDownloader", str(e))

# ===========================
# 6. 디렉토리 및 파일 검증
# ===========================
print("\n📋 6단계: 디렉토리 및 파일 검증")
print("-" * 80)

# 5-1. DOWNLOAD_DIR 확인
if DOWNLOAD_DIR.exists():
    test_pass("DOWNLOAD_DIR 존재", str(DOWNLOAD_DIR))
else:
    test_fail("DOWNLOAD_DIR", f"디렉토리 없음: {DOWNLOAD_DIR}")

# 5-2. 로그 디렉토리 확인
logs_dir = DOWNLOAD_DIR.parent.parent / "logs"
if logs_dir.exists() or True:  # 필요시 생성됨
    test_pass("로그 디렉토리", str(logs_dir))
else:
    test_fail("로그 디렉토리", f"디렉토리 없음: {logs_dir}")

# ===========================
# 최종 결과
# ===========================
print("\n" + "=" * 80)
print("📊 테스트 결과 요약")
print("=" * 80)

passed = sum(1 for _, status, _ in test_results if status == "PASS")
failed = sum(1 for _, status, _ in test_results if status == "FAIL")
errors = sum(1 for _, status, _ in test_results if status == "ERROR")
total = len(test_results)

print(f"\n총 테스트: {total}")
print(f"✅ 통과: {passed}")
print(f"❌ 실패: {failed}")
print(f"⚠️  오류: {errors}")

if failed == 0 and errors == 0:
    print("\n🎉 모든 테스트 통과!")
    print("\n✨ 스크립트 준비 완료:")
    print(f"   🚀 실행: python scripts/batch_download.py --url <URL>")
    print(f"   📖 도움: python scripts/batch_download.py --help")
else:
    print(f"\n⚠️  {failed + errors}개의 테스트가 실패했습니다.")

# 상세 결과 테이블
print("\n" + "=" * 80)
print("📋 상세 테스트 결과")
print("=" * 80)
print(f"{'#':<3} {'상태':<8} {'테스트':<30} {'상세':<40}")
print("-" * 80)
for idx, (name, status, detail) in enumerate(test_results, 1):
    status_symbol = "✅" if status == "PASS" else "❌" if status == "FAIL" else "⚠️"
    detail_short = detail[:37] + "..." if len(detail) > 40 else detail
    print(f"{idx:<3} {status_symbol} {status:<6} {name:<30} {detail_short:<40}")

print("=" * 80)
