#!/usr/bin/env python3
"""
YouTube 채널 배치 다운로드 스크립트
- 목적: YouTube 채널의 전체 동영상을 MP4/MP3로 일괄 다운로드
- 사용법: python batch_download.py [--url URL] [--type video|audio] [--format-id ID]
"""

import os
import sys
import re
import json
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional
import logging

# yt-dlp 임포트
try:
    import yt_dlp
except ImportError:
    print("❌ yt-dlp가 설치되지 않았습니다. 다음 명령어를 실행하세요:")
    print("   pip install yt-dlp")
    sys.exit(1)


# ===========================
# 기본 설정
# ===========================

BASE_DIR = Path(__file__).resolve().parent.parent
DOWNLOAD_DIR = BASE_DIR / "downloads" / "batch"
LOG_DIR = BASE_DIR / "logs"

# yt-dlp 기본 포맷 규칙(영상/오디오)
# 최고 해상도 우선: bestvideo(720p 이상 선호) + bestaudio(최고음질)
DEFAULT_VIDEO_FMT = "bestvideo[ext=mp4][vcodec^=avc1][height>=720]+bestaudio[ext=m4a]/bestvideo[ext=mp4][vcodec^=avc1]+bestaudio[ext=m4a]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best"
DEFAULT_AUDIO_FMT = "bestaudio/best"

# 체크포인트 파일 경로
CHECKPOINT_FILE = DOWNLOAD_DIR / ".checkpoint.json"

# 로그 설정
LOG_DIR.mkdir(exist_ok=True, parents=True)
DOWNLOAD_DIR.mkdir(exist_ok=True, parents=True)

log_filename = LOG_DIR / f"batch_download_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

logger = logging.getLogger("batch_downloader")
logger.setLevel(logging.DEBUG)

# 핸들러: 파일 + 콘솔
fh = logging.FileHandler(log_filename, encoding='utf-8')
fh.setLevel(logging.DEBUG)

ch = logging.StreamHandler()
ch.setLevel(logging.INFO)

formatter = logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s")
fh.setFormatter(formatter)
ch.setFormatter(formatter)

logger.addHandler(fh)
logger.addHandler(ch)


# ===========================
# 유틸리티 함수
# ===========================

def sanitize_filename(name: str) -> str:
    """파일명에 사용할 문자열을 정제"""
    if not name:
        return "untitled"
    # 위험 문자 제거
    sanitized = re.sub(r'[\\/\n\r\t\0\x0B:*?"<>|]', "_", name).strip()[:180]
    return sanitized


def ydl_base_opts() -> Dict[str, Any]:
    """yt-dlp 공통 옵션 생성(네트워크/SSL 회복력 강화)"""
    return {
        "quiet": False,
        "noprogress": False,
        "ignoreerrors": True,  # 채널 다운로드 시 일부 오류 무시
        "no_warnings": False,
        "cachedir": False,
        "socket_timeout": 30,
        "retries": 10,
        "fragment_retries": 10,
        "extractor_retries": 10,
        "nocheckcertificate": True,
        "sleep_interval": 1,
        "max_sleep_interval": 10,
    }


def format_size(bytes_size: int) -> str:
    """바이트 크기를 보기 좋은 단위로 변환"""
    if bytes_size < 1024:
        return f"{bytes_size} B"
    elif bytes_size < 1024 * 1024:
        return f"{bytes_size / 1024:.1f} KB"
    elif bytes_size < 1024 * 1024 * 1024:
        return f"{bytes_size / (1024 * 1024):.1f} MB"
    else:
        return f"{bytes_size / (1024 * 1024 * 1024):.1f} GB"


def format_duration(seconds: int) -> str:
    """초를 HH:MM:SS 형식으로 변환"""
    if seconds is None:
        return "N/A"
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


# ===========================
# 체크포인트 관리 함수 (재개 로직)
# ===========================

def load_checkpoint() -> Dict[str, Any]:
    """저장된 체크포인트 파일 로드"""
    if CHECKPOINT_FILE.exists():
        try:
            with open(CHECKPOINT_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                logger.info(f"📋 체크포인트 로드 완료: {CHECKPOINT_FILE}")
                logger.info(f"   완료: {len([v for v in data.get('videos', {}).values() if v['status'] == 'completed'])} 개")
                logger.info(f"   실패: {len([v for v in data.get('videos', {}).values() if v['status'] == 'failed'])} 개")
                logger.info(f"   대기: {len([v for v in data.get('videos', {}).values() if v['status'] == 'pending'])} 개")
                return data
        except Exception as e:
            logger.warning(f"⚠️  체크포인트 로드 실패: {e}")
    
    return {"videos": {}, "start_time": datetime.now().isoformat()}


def save_checkpoint(data: Dict[str, Any]) -> None:
    """체크포인트 파일 저장"""
    try:
        with open(CHECKPOINT_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"❌ 체크포인트 저장 실패: {e}")


def update_checkpoint(video_id: str, status: str, info: Dict[str, Any] = None) -> None:
    """체크포인트에 비디오 상태 업데이트"""
    data = load_checkpoint()
    
    if video_id not in data["videos"]:
        data["videos"][video_id] = {}
    
    data["videos"][video_id].update({
        "status": status,  # "pending", "completed", "failed"
        "updated_at": datetime.now().isoformat(),
        **(info or {})
    })
    
    save_checkpoint(data)


def get_pending_videos(all_videos: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], List[str]]:
    """체크포인트를 기반으로 대기 중인 비디오 필터링"""
    checkpoint = load_checkpoint()
    video_statuses = checkpoint.get("videos", {})
    
    completed_ids = [vid for vid, v in video_statuses.items() if v.get("status") == "completed"]
    failed_ids = [vid for vid, v in video_statuses.items() if v.get("status") == "failed"]
    
    pending = [v for v in all_videos if v.get("id") not in completed_ids]
    
    logger.info(f"\n📊 진행 상태:")
    logger.info(f"   ✅ 이미 완료: {len(completed_ids)} 개")
    logger.info(f"   ❌ 이전 실패: {len(failed_ids)} 개 (재시도 예정)")
    logger.info(f"   ⏳ 대기 중: {len(pending)} 개")
    
    return pending, completed_ids


# ===========================
# 배치 다운로드 구현
# ===========================

class BatchDownloader:
    """YouTube 채널/재생목록 배치 다운로드 관리자"""

    def __init__(self, download_type: str = "video", format_id: str = None, skip_existing: bool = True):
        """
        Args:
            download_type: "video" 또는 "audio"
            format_id: 특정 포맷 ID (None이면 최적값 사용)
            skip_existing: True면 기존 파일 스킵, False면 재다운로드
        """
        self.download_type = download_type
        self.format_id = format_id
        self.skip_existing = skip_existing
        self.stats = {
            "total": 0,
            "success": 0,
            "failed": 0,
            "skipped": 0,
            "total_size": 0,
        }
        self.failed_videos = []
        self.skipped_videos = []

    def get_channel_videos(self, channel_url: str) -> List[Dict[str, Any]]:
        """채널의 모든 동영상 정보 추출"""
        logger.info(f"📺 채널 정보 추출: {channel_url}")
        try:
            opts = {
                **ydl_base_opts(),
                "extract_flat": "in_playlist",  # 플레이리스트/채널 구조만 추출
                "skip_download": True,
            }
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(channel_url, download=False)

            # 채널명 + 항목 수
            channel_name = info.get("title", "Unknown Channel")
            entries = info.get("entries", [])

            logger.info(f"✅ 채널명: {channel_name}")
            logger.info(f"📊 총 동영상 수: {len(entries)}")

            self.stats["total"] = len(entries)
            return entries

        except Exception as e:
            logger.error(f"❌ 채널 정보 추출 실패: {e}")
            return []

    def download_video(self, video_url: str, video_id: str, index: int, total: int) -> bool:
        """단일 동영상 다운로드"""
        try:
            logger.info(f"\n⏳ [{index}/{total}] 다운로드 시작: {video_url}")

            # 기본 메타데이터 추출
            base_opts = ydl_base_opts()
            with yt_dlp.YoutubeDL(base_opts) as ydl:
                info = ydl.extract_info(video_url, download=False)

            title = sanitize_filename(info.get("title", "unknown"))
            video_id_actual = info.get("id", video_id)
            duration = info.get("duration", 0)

            logger.info(f"📹 제목: {title}")
            logger.info(f"⏱️  길이: {format_duration(duration)}")

            # ===== 중복 파일 확인 로직 =====
            if self.skip_existing:
                # 모든 가능한 파일 확장자 확인 (mp4, mp3, mkv, webm 등)
                existing_files = list(DOWNLOAD_DIR.glob(f"{title}_{video_id_actual}_*.*"))
                if existing_files:
                    file_info = []
                    total_size = 0
                    for f in existing_files:
                        size = f.stat().st_size
                        total_size += size
                        file_info.append(f"{f.name} ({format_size(size)})")
                    
                    logger.info(f"✅ 이미 다운로드됨: {', '.join(file_info)}")
                    logger.info(f"   💾 총 크기: {format_size(total_size)}")
                    self.stats["skipped"] += 1
                    self.stats["total_size"] += total_size
                    self.skipped_videos.append((video_url, title, total_size))
                    
                    # 체크포인트 업데이트 (완료)
                    update_checkpoint(video_id_actual, "completed", {
                        "title": title,
                        "url": video_url,
                        "size": total_size,
                        "reason": "already_exists"
                    })
                    return True
            # ================================

            # 파일명 템플릿: title_id_type.ext
            if self.download_type == "video":
                output_template = str(DOWNLOAD_DIR / f"{title}_{video_id}_video.%(ext)s")
                fmt = self.format_id or DEFAULT_VIDEO_FMT
                dl_opts = {
                    **base_opts,
                    "format": fmt,
                    "outtmpl": output_template,
                    "merge_output_format": "mp4",
                }
            else:  # audio
                output_template = str(DOWNLOAD_DIR / f"{title}_{video_id}_audio.%(ext)s")
                fmt = self.format_id or DEFAULT_AUDIO_FMT
                dl_opts = {
                    **base_opts,
                    "format": fmt,
                    "outtmpl": output_template,
                    "postprocessors": [
                        {
                            "key": "FFmpegExtractAudio",
                            "preferredcodec": "mp3",
                            "preferredquality": "192",
                        }
                    ],
                }

            # 진행 콜백
            def progress_hook(d):
                if d["status"] == "downloading":
                    percent = d.get("_percent_str", "").strip()
                    speed = d.get("_speed_str", "").strip()
                    eta = d.get("_eta_str", "").strip()
                    logger.info(f"   🔄 {percent} {speed} {eta}")
                elif d["status"] == "finished":
                    logger.info(f"   ✅ 다운로드 완료")

            dl_opts["progress_hooks"] = [progress_hook]

            # 다운로드 실행
            with yt_dlp.YoutubeDL(dl_opts) as ydl:
                result = ydl.download([video_url])

            if result == 0:
                # 파일 크기 계산
                candidates = sorted(
                    DOWNLOAD_DIR.glob(f"{title}_{video_id_actual}_*.*"),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )
                if candidates:
                    file_size = candidates[0].stat().st_size
                    self.stats["total_size"] += file_size
                    logger.info(f"   📦 파일 크기: {format_size(file_size)}")

                self.stats["success"] += 1
                logger.info(f"✨ 완료 [{index}/{total}]")
                
                # 체크포인트 업데이트 (완료)
                update_checkpoint(video_id_actual, "completed", {
                    "title": title,
                    "url": video_url,
                    "size": file_size if candidates else 0
                })
                return True
            else:
                logger.warning(f"⚠️  다운로드 실패: {video_url}")
                self.stats["failed"] += 1
                self.failed_videos.append((video_url, "Unknown error"))
                
                # 체크포인트 업데이트 (실패)
                update_checkpoint(video_id_actual, "failed", {
                    "title": title,
                    "url": video_url,
                    "error": "Unknown error"
                })
                return False

        except Exception as e:
            logger.error(f"❌ 다운로드 오류: {e}")
            self.stats["failed"] += 1
            self.failed_videos.append((video_url, str(e)))
            
            # 체크포인트 업데이트 (실패) - 함수 매개변수의 video_id 사용
            update_checkpoint(video_id, "failed", {
                "url": video_url,
                "error": str(e)
            })
            return False

    def run(self, channel_url: str):
        """배치 다운로드 실행"""
        logger.info("=" * 80)
        logger.info(f"🚀 배치 다운로드 시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"📍 채널 URL: {channel_url}")
        logger.info(f"📋 다운로드 타입: {self.download_type}")
        logger.info(f"🔄 중복 처리: {'스킵' if self.skip_existing else '재다운로드'}")
        logger.info("=" * 80)

        # 채널 비디오 목록 추출
        entries = self.get_channel_videos(channel_url)
        if not entries:
            logger.error("❌ 동영상을 찾을 수 없습니다.")
            return

        # 체크포인트 기반 대기 중인 비디오 필터링
        pending_entries, completed_ids = get_pending_videos(entries)
        
        # 대기 중인 비디오만 다운로드
        for idx, entry in enumerate(pending_entries, 1):
            # entry는 dict 또는 ID만 포함될 수 있음
            if isinstance(entry, dict):
                video_id = entry.get("id")
                video_url = f"https://www.youtube.com/watch?v={video_id}"
            else:
                video_url = f"https://www.youtube.com/watch?v={entry}"
                video_id = entry

            self.download_video(video_url, video_id, idx, len(pending_entries))

        # 최종 통계
        logger.info("\n" + "=" * 80)
        logger.info("📊 배치 다운로드 완료")
        logger.info("=" * 80)
        logger.info(f"✅ 성공: {self.stats['success']}")
        logger.info(f"❌ 실패: {self.stats['failed']}")
        logger.info(f"⏭️  스킵: {self.stats['skipped']}")
        logger.info(f"📦 총 크기: {format_size(self.stats['total_size'])}")
        logger.info(f"💾 저장 위치: {DOWNLOAD_DIR}")

        if self.skipped_videos:
            logger.info("\n⏭️  스킵된 동영상 (이미 존재):")
            for url, title, size in self.skipped_videos:
                logger.info(f"   - {title} ({format_size(size)})")

        if self.failed_videos:
            logger.info("\n⚠️  실패한 동영상:")
            for url, error in self.failed_videos:
                logger.info(f"   - {url}: {error}")

        logger.info(f"📝 로그 파일: {log_filename}")
        logger.info(f"📊 체크포인트 파일: {CHECKPOINT_FILE}")
        logger.info("=" * 80)


# ===========================
# CLI 인터페이스
# ===========================

def main():
    parser = argparse.ArgumentParser(
        description="YouTube 채널/재생목록 배치 다운로드",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  # 채널의 모든 MP4 다운로드 (중복 스킵)
  python batch_download.py --url "https://www.youtube.com/@Niminem_HipHop/videos"

  # 채널의 모든 MP3 다운로드
  python batch_download.py --url "https://www.youtube.com/@Niminem_HipHop/videos" --type audio

  # 중단된 곳부터 계속 다운로드 (자동)
  python batch_download.py --url "https://www.youtube.com/@Niminem_HipHop/videos"

  # 중복 파일도 재다운로드
  python batch_download.py --url "https://www.youtube.com/@Niminem_HipHop/videos" --force

  # 체크포인트 초기화 후 처음부터 다운로드
  python batch_download.py --url "https://www.youtube.com/@Niminem_HipHop/videos" --reset

  # 재생목록 다운로드 (중복 스킵)
  python batch_download.py --url "https://www.youtube.com/playlist?list=PLxxxxx"
        """
    )

    parser.add_argument(
        "--url",
        type=str,
        required=False,
        default="https://www.youtube.com/@Niminem_HipHop/videos",
        help="YouTube 채널/재생목록 URL (기본값: Niminem_HipHop 채널)"
    )

    parser.add_argument(
        "--type",
        type=str,
        choices=["video", "audio"],
        default="video",
        help="다운로드 타입 (기본값: video)"
    )

    parser.add_argument(
        "--format-id",
        type=str,
        default=None,
        help="yt-dlp format_id (예: 22, 251 등. 생략 시 최적값 사용)"
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="중복 파일이 있어도 재다운로드 (기본: 스킵)"
    )

    parser.add_argument(
        "--reset",
        action="store_true",
        help="체크포인트 초기화 후 처음부터 다운로드"
    )

    args = parser.parse_args()

    # 체크포인트 초기화
    if args.reset:
        if CHECKPOINT_FILE.exists():
            CHECKPOINT_FILE.unlink()
            logger.info(f"🔄 체크포인트 초기화 완료: {CHECKPOINT_FILE}")
        else:
            logger.info("ℹ️  체크포인트 파일이 없습니다.")

    # 배치 다운로더 생성 및 실행
    downloader = BatchDownloader(
        download_type=args.type,
        format_id=args.format_id,
        skip_existing=not args.force
    )
    downloader.run(args.url)


if __name__ == "__main__":
    main()
