# yt-download 프로젝트 종합 분석

## 📋 프로젝트 개요

**프로젝트명**: YouTube 로컬 다운로더 (yt-download)  
**목적**: 사용자가 YouTube URL을 입력하여 MP4(영상) 또는 MP3(오디오)로 로컬 환경에서 다운로드받을 수 있는 웹 기반 도구  
**기술 스택**: FastAPI + yt-dlp + FFmpeg + 순수 HTML/CSS/JavaScript  
**배포**: 로컬 실행(Python 3.10+) 또는 Docker  
**비용**: 0원(모두 오픈소스 기반)

---

## 🎯 핵심 기능

### 1. 포맷 조회 (`/api/formats`)
- **입력**: YouTube URL
- **출력**: 영상(MP4) 및 오디오(MP3) 포맷 목록
- **로직**:
  - yt-dlp로 메타데이터 추출 (다운로드 없음)
  - 영상: `avc1` 코덱 + `mp4` 컨테이너 기준 해상도별 **대표 포맷만** 추출
  - 오디오: 비트레이트별 **대표 포맷만** 추출(m4a 우선)
  - 정렬: 영상은 해상도 오름차순, 오디오는 비트레이트 오름차순

### 2. 동기식 다운로드 (`/api/download`)
- **입력**: URL + type(video|audio) + format_id
- **출력**: 다운로드된 파일(MP4 또는 MP3)
- **프로세스**:
  1. 제목/ID 사전 추출
  2. 파일명 규칙 생성: `제목_ID_해상도_formatID.ext`
  3. 중복 시 `_2`, `_3` ... 접미사 부여
  4. yt-dlp 실행:
     - 영상: `merge_output_format=mp4` (병합 필수)
     - 오디오: FFmpeg 후처리로 MP3 변환(192kbps)
  5. 결과 파일 반환
  6. 백그라운드로 `downloads/` 폴더 정리

### 3. 비동기식 다운로드 + 진행률 (SSE)
- **흐름**:
  1. `POST /api/download/start` → job_id 생성 (백그라운드 스레드 시작)
  2. `GET /api/progress/{job_id}` (SSE) → 진행률 스트리밍
  3. `GET /api/download/result/{job_id}` → 파일 전송

- **Job 상태 관리** (메모리):
  ```python
  _JOBS = {
    "job_id": {
      "queue": Queue(),           # 진행률 이벤트
      "is_done": bool,
      "is_error": bool,
      "error_message": str,
      "file_path": str,
      "meta": {...},
      "created_at": timestamp
    }
  }
  ```

- **진행률 콜백**:
  - yt-dlp `progress_hooks` → Queue에 진행 이벤트 적재
  - SSE로 0.5초 주기로 하트비트 전송(연결 유지)
  - 대역폭, 속도, ETA 포함

---

## 🏗️ 아키텍처

### 백엔드 (FastAPI)

#### 핵심 모듈
```
server/app.py
├── 기본 설정 (BASE_DIR, DOWNLOAD_DIR, 포맷 템플릿)
├── 유틸리티 함수
│   ├── sanitize_filename()      # 파일명 정제
│   ├── ydl_base_opts()          # yt-dlp 공통 옵션
│   ├── build_output_template()  # 파일 템플릿 생성
│   ├── ensure_unique_outtmpl()  # 중복 파일 처리
│   └── _cleanup_downloads_dir() # 임시 파일 정리
├── API 엔드포인트
│   ├── GET  /api/health
│   ├── GET  /api/formats
│   ├── GET  /api/download
│   ├── POST /api/download/start
│   ├── GET  /api/progress/{job_id}
│   └── GET  /api/download/result/{job_id}
└── 정적 파일 서빙 (web/)
```

#### 포맷 필터링 로직
```python
# 영상: 해상도별 최고 품질
video_by_res = {
  "1280x720": {..., "tbr": 1500},  # 최고 tbr만 보관
  "1920x1080": {..., "tbr": 3000}
}

# 오디오: 비트레이트별 m4a 우선
audio_by_bitrate = {
  128: {..., "ext": "m4a"},
  192: {..., "ext": "m4a"}  # m4a가 없으면 다른 포맷
}
```

#### 에러 처리 전략
- **사용자 메시지**: 일반적이고 친절한 안내만 제공
- **내부 로그**: 전체 스택 트레이스 기록
- **부분 실패 대응**: 훅 미발화 대비 파일 시스템 직접 탐색

### 프론트엔드 (HTML/JS)

#### 상태 관리
```javascript
{
  lastFormats: { video: [], audio: [] },  // 조회 결과 캐시
  currentEventSource: EventSource,         // SSE 연결
}
```

#### 주요 플로우
```
1. URL 입력 + "포맷 조회" 버튼
   ↓
2. /api/formats → 해상도/비트레이트 드롭다운 구성
   ↓
3. 형식(영상/오디오) + 품질 선택
   ↓
4. "다운로드" 버튼 클릭
   ↓
5. POST /api/download/start → job_id
   ↓
6. EventSource /api/progress/{job_id}
   ↓
7. 모달에 진행률(%) + 속도 + ETA 표시
   ↓
8. 완료 시 /api/download/result/{job_id} 자동 다운로드
```

#### UI 컴포넌트
- **입력영역**: URL 입력 + "포맷 조회" 버튼
- **선택영역**: 영상(해상도) + 오디오(비트레이트) 드롭다운
- **다운로드버튼**: MP4/MP3 각각
- **모달**: 진행률 바(0~100%) + 상태 메시지 + 스피드/ETA
- **상태표시**: 조회 상태, 에러 메시지 (상단 텍스트)

---

## 📊 데이터 흐름 다이어그램

```
┌─────────────┐
│  Browser    │
│  (Web UI)   │
└────┬────────┘
     │ HTTP
     ▼
┌────────────────────────────────────────┐
│  FastAPI Server (127.0.0.1:3001)       │
├────────────────────────────────────────┤
│  GET  /api/formats                     │
│  └─→ yt-dlp (extract_info) → meta JSON │
│                                        │
│  POST /api/download/start              │
│  ├─→ _create_job()                     │
│  ├─→ Start background thread           │
│  └─→ Return job_id                     │
│                                        │
│  GET  /api/progress/{job_id} (SSE)     │
│  ├─→ StreamingResponse                 │
│  ├─→ Queue.get() → Event               │
│  └─→ Heartbeat every 15sec             │
│                                        │
│  GET  /api/download/result/{job_id}    │
│  └─→ FileResponse (MP4/MP3)            │
└────────────────────────────────────────┘
     ▲         ▲         ▲
     │         │         │
  yt-dlp   FFmpeg   FileSystem
  (조회)  (MP3 변환)  (저장)
```

---

## 🔧 핵심 로직 상세 분석

### 1. 파일명 규칙 및 중복 처리

**규칙**: `{제목}_{ID}_{해상도}_{formatId}.{ext}`

**예시**:
- 영상: `My Video_abc123_1920x1080_22.mp4`
- 오디오: `My Video_abc123_audio_251.mp3`

**중복 처리**:
```python
def ensure_unique_outtmpl(outtmpl):
    # 1차: 기본 파일이 없으면 반환
    # 2차: 있으면 _2, _3, ... 시도
    # 최대 1000번 시도 후 마지막 후보 반환
```

### 2. yt-dlp 옵션 전략

#### 공통 옵션
```python
{
  "quiet": True,        # 불필요한 출력 억제
  "noprogress": True,   # 텍스트 진행바 비활성화(이벤트 사용)
  "ignoreerrors": False,
  "no_warnings": True,
  "cachedir": False
}
```

#### 영상 다운로드
```python
{
  "format": "best[ext=mp4]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best",
  "merge_output_format": "mp4",
  # → 우선순위: progressive mp4 > 영상+오디오 병합 > 기본
}
```

#### 오디오 다운로드
```python
{
  "format": "bestaudio/best",
  "postprocessors": [
    {
      "key": "FFmpegExtractAudio",
      "preferredcodec": "mp3",
      "preferredquality": "192"
    }
  ]
  # → 추출 후 192kbps MP3로 변환
}
```

### 3. SSE (Server-Sent Events) 기반 진행률 스트리밍

**흐름**:
```
yt-dlp 실행 (백그라운드 스레드)
├─ progress_hooks 콜백 → Queue.put()
├─ postprocessor_hooks 콜백 → Queue.put()
└─ 다운로드 완료 → Queue.put("completed")

SSE 엔드포인트 (/api/progress/{job_id})
├─ 루프: Queue.get_nowait()
├─ 15초마다 하트비트 전송(연결 유지)
├─ 클라이언트 연결 해제 감지
└─ 작업 완료 & 큐 비어있음 → 스트림 종료
```

**이벤트 타입**:
```json
{
  "type": "progress",
  "percent": 45.5,
  "speed": 1024000,
  "eta": 120
}

{
  "type": "completed",
  "filename": "My Video_abc123_1920x1080_22.mp4"
}

{
  "type": "error",
  "message": "다운로드 중 문제가 발생했습니다."
}
```

### 4. 파일 경로 결정 전략

**1차 방법** (권장): postprocessor_hooks에서 `filepath` 추출
```python
final_path_holder = {"path": None}
def _post_hook(d):
    if d.get("status") == "finished":
        fp = d.get("info_dict", {}).get("filepath")
        if fp and os.path.exists(fp):
            final_path_holder["path"] = fp
```

**2차 방법** (폴백): 파일 시스템 직접 탐색
```python
search_base = Path(_remove_ext_placeholder(outtmpl_base)).name
candidates = sorted(
    DOWNLOAD_DIR.glob(f"{search_base}.*"),
    key=lambda p: p.stat().st_mtime,
    reverse=True
)
file_path = candidates[0] if candidates else None
```

---

## 🎨 프론트엔드 로직 상세

### 포맷 옵션 렌더링

**영상 드롭다운**:
```javascript
// 레이블: "1920x1080 (오디오포함)" 형식
// 값: format_id (숨김)
for (const f of videoList) {
  const label = `${f.width}x${f.height}${f.hasAudio ? ' (오디오포함)' : ''}`;
  // 사용자가 클릭하면 f.format_id를 선택
}
```

**오디오 드롭다운**:
```javascript
// 레이블: "192 kbps" 형식
// 값: format_id (숨김)
for (const f of audioList) {
  const br = f.tbr != null ? Math.round(f.tbr) : '';
  const label = `${br} kbps`;
}
```

### SSE 이벤트 핸들링

```javascript
const es = new EventSource(`/api/progress/${job_id}`);

es.addEventListener('message', (ev) => {
  const data = JSON.parse(ev.data);
  
  if (data.type === 'progress') {
    percent = Math.max(0, Math.min(100, data.percent));
    setModalProgress(percent);  // 진행률 바 업데이트
    setModalMessage(`${percent.toFixed(1)}%` + speed + eta);
  } 
  else if (data.type === 'completed') {
    es.close();
    triggerFileDownload(`/api/download/result/${job_id}`);
    setTimeout(closeModal, 1200);
  } 
  else if (data.type === 'error') {
    es.close();
    setModalMessage('오류가 발생했습니다.');
    setTimeout(closeModal, 1500);
  }
});
```

### 속도/ETA 포맷팅

```javascript
function formatSpeed(bytesPerSec) {
  // 1 MB/s, 512 KB/s, 1024 B/s 형식
}

function formatEta(sec) {
  // mm:ss 형식 (예: 02:45)
}
```

---

## 📁 디렉토리 구조 및 파일 흐름

```
yt-download/
├── Dockerfile               # Docker 이미지 정의
├── Makefile                 # 편의 명령어(있으면)
├── pyproject.toml           # Python 프로젝트 정의(uv)
├── requirements.txt         # 의존성
├── README.md                # 설치/실행 가이드
├── shrimp-rules.md          # 개발 규칙
│
├── server/
│   └── app.py              # FastAPI 애플리케이션 (메인)
│
├── web/
│   └── index.html          # 프론트엔드 (전체)
│
├── downloads/              # 다운로드 결과 저장 경로
│   └── (파일들)
│
├── scripts/
│   ├── run_local_mac.sh
│   ├── run_local_win.ps1
│   ├── run_docker.sh
│   └── serve_uv.sh
│
└── docs/
    └── PRD.md              # 제품 요구사항 문서
```

---

## 🚀 실행 흐름

### 1. 로컬 실행 (Windows)
```powershell
# 가상환경 생성
uv venv
.\.venv\Scripts\Activate.ps1

# 의존성 설치
uv pip install -r requirements.txt

# 서버 시작
python -m uvicorn server.app:app --host 127.0.0.1 --port 3001 --reload

# 브라우저: http://127.0.0.1:3001
```

### 2. Docker 실행
```bash
docker build -t yt-download .
docker run -p 3001:3001 -v $(pwd)/downloads:/app/downloads yt-download
# → http://localhost:3001
```

### 3. 사용자 시나리오

**단계 1**: 포맷 조회
```
URL: https://www.youtube.com/watch?v=...
→ GET /api/formats?url=...
← {
    "id": "abc123",
    "title": "My Video",
    "video": [
      {"width": 1280, "height": 720, "format_id": "22", ...},
      {"width": 1920, "height": 1080, "format_id": "18", ...}
    ],
    "audio": [
      {"tbr": 128, "format_id": "251", ...},
      {"tbr": 192, "format_id": "140", ...}
    ]
  }
```

**단계 2**: 영상 다운로드 (진행률 포함)
```
POST /api/download/start?url=...&type=video&format_id=18
← {"job_id": "xyz789"}

GET /api/progress/xyz789 (SSE)
← data: {"type": "progress", "percent": 10, "speed": 1024000, ...}
← data: {"type": "progress", "percent": 25, ...}
← ...
← data: {"type": "completed", "filename": "My Video_abc123_1920x1080_18.mp4"}

GET /api/download/result/xyz789
← [MP4 파일 바이너리]
```

---

## ⚠️ 주요 제약 및 특이사항

| 항목 | 설명 |
|------|------|
| **FFmpeg 의존성** | MP3 변환에 필수(오디오 다운로드 시) |
| **로컬 전용** | 127.0.0.1 바인딩, 외부 접근 불가(보안) |
| **메모리 저장** | Job 상태가 메모리에만 저장(서버 재시작 시 초기화) |
| **동시 처리** | 2건 이상은 경계(각각 백그라운드 스레드) |
| **포맷 필터링** | 특정 코덱만 노출(avc1+mp4), 대부분 포함 |
| **파일 자동 정리** | 다운로드 완료 후 `downloads/` 폴더 비워짐 |
| **중복 파일명** | _2, _3 ... 자동 부여(최대 1000) |

---

## 🔐 보안 고려사항

✅ **구현된 보안**:
- 로컬 바인딩 (127.0.0.1)
- 파일명 새니타이제이션 (위험 문자 치환)
- 외부 네트워크 요청 없음 (yt-dlp는 YouTube CDN과 직통)
- 민감 정보 로깅 없음

⚠️ **제약사항**:
- HTTPS/로그인 없음 (로컬 전용)
- 같은 머신 사용자 간 격리 없음
- DRM 컨텐츠 미지원

---

## 📈 성능 특성

| 지표 | 목표/실제 |
|------|----------|
| 포맷 조회 시간 | ~2초 (네트워크 제외) |
| 진행률 업데이트 주기 | 500ms~1s |
| SSE 하트비트 | 15초 |
| 동시 다운로드 | 2건(권장) |
| 서버 메모리 | ~50MB(유휴) + Job당 ~1MB |

---

## 🛠️ 확장 가능성 (로드맵)

### v2 계획
- ✅ 자동 포맷 선택(사용자 설정)
- ✅ 다중 큐(순차/병렬)
- ✅ 드래그&드롭 URL
- ✅ 자막/썸네일 옵션
- ✅ 최근 다운로드 내역
- ✅ 프록시 지원

### 기술 부채
- 콜백 기반 에러 처리 개선 (try-except 중복)
- 파일 경로 결정 로직 단순화
- Job 메모리 대신 Redis/DB 사용

---

## 📝 요약

**yt-download**는 **로컬 환경에 최적화된 YouTube 다운로더**로, 다음과 같은 특징을 가집니다:

1. **간단한 UI**: URL 입력 → 형식 선택 → 다운로드 (3단계)
2. **실시간 진행률**: SSE 기반 진행 상태 + 속도 + ETA
3. **파일 자동 정리**: 다운로드 후 로컬 스토리지 정리
4. **포맷 최적화**: 가장 높은 해상도/비트레이트만 노출
5. **오류 대응**: 부분 실패 시에도 파일 탐색으로 복구 시도
6. **배포 유연성**: 로컬 실행 + Docker 지원

**핵심 강점**: 0원 비용 + 의존성 최소(FastAPI, yt-dlp) + 모든 변환이 로컬(대역폭 절약)
