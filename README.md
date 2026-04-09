# Local AI Assistant

로컬 LLM 기반의 PC 제어(Computer Use) 데스크탑 채팅 애플리케이션입니다.  
LLM이 사용자의 요청을 해석하고, 브라우저 자동화 및 OS 제어 스킬을 실행한 뒤 결과를 채팅창에 보고합니다.

## Tech Stack

| Layer | Tech |
|---|---|
| Frontend | Vue 3, TypeScript, Ant Design, Tailwind CSS |
| Backend | FastAPI (Python 3.10+) |
| Desktop | Electron |
| LLM | Local LLM (OpenAI-compatible API) |
| Automation | Playwright (브라우저), PyAutoGUI (OS) |

## Project Structure

```
local-agents/
├── apps/
│   ├── frontend/                  # Vue 3 + Vite SPA
│   │   └── src/
│   │       ├── components/
│   │       │   ├── ChatWindow.vue # 메인 채팅 UI
│   │       │   ├── MessageItem.vue
│   │       │   └── Settings.vue   # LLM 설정 모달
│   │       ├── stores/chat.ts     # Pinia 상태 관리
│   │       ├── api/client.ts      # SSE 스트리밍 API 클라이언트
│   │       └── types/index.ts
│   └── desktop/                   # Electron 메인 프로세스
│       ├── main.js                # 창 관리, 트레이, FastAPI 자식 프로세스
│       ├── preload.js
│       └── assets/icon.png
├── server/
│   ├── main.py                    # FastAPI 엔트리포인트
│   ├── requirements.txt
│   ├── core/
│   │   ├── llm_connector.py       # OpenAI-compatible LLM 프록시
│   │   └── orchestrator.py        # Tool-call 에이전트 루프
│   ├── browsers/                  # 로컬 Chromium (git 제외, 수동 설치)
│   │   └── chrome-win64/
│   │       └── chrome.exe
│   └── skills/                    # 스킬 레지스트리 (자동 로드)
│       ├── __init__.py            # 폴더 스캔 → 자동 등록
│       ├── skill_base.py          # SkillBase 추상 클래스
│       ├── browser_skill.py       # Playwright 브라우저 제어
│       └── os_skill.py            # PyAutoGUI OS 제어
├── start.bat                      # Windows 원클릭 실행
├── start-dev.sh                   # Unix 개발 실행 스크립트
└── package.json                   # 루트 모노레포
```

## Prerequisites

- **Python 3.10+**
- **Node.js 18+**
- **로컬 LLM 서버** — [Ollama](https://ollama.com), [LM Studio](https://lmstudio.ai), 또는 OpenAI-compatible 엔드포인트

## Installation

### 1. Python 의존성

```bash
cd server
pip install -r requirements.txt
```

**Chromium 설치** — 인터넷 환경에 따라 아래 두 방법 중 선택합니다.

**방법 A. 자동 설치 (외부망 접근 가능 시)**
```bash
playwright install chromium
```

**방법 B. 수동 설치 (사내망 등 제한 환경)**

아래 URL에서 zip을 다운로드한 뒤 `server/browsers/`에 압축 해제합니다.

```
https://cdn.playwright.dev/builds/cft/147.0.7727.15/win64/chrome-win64.zip
```

PowerShell:
```powershell
# 프로젝트 루트에서 실행
Expand-Archive -Path "chrome-win64.zip" -DestinationPath "server\browsers\"
```

압축 해제 후 구조:
```
server/browsers/
└── chrome-win64/
    ├── chrome.exe   ← 이 파일이 있어야 함
    └── ...
```

> `server/browsers/`는 `.gitignore`에 등록되어 있어 git에 포함되지 않습니다.

### 2. Node.js 의존성

```bash
cd apps/frontend
npm install

cd ../desktop
npm install
```

## Running

### Windows (원클릭)

```bat
start.bat
```

FastAPI 서버 → Vue 개발 서버 → Electron 순서로 자동 실행됩니다.

### 수동 실행 (터미널 3개)

```bash
# 터미널 1 — FastAPI 서버
python server/main.py

# 터미널 2 — Vue 개발 서버
cd apps/frontend && npm run dev

# 터미널 3 — Electron
cd apps/desktop && npx electron . --dev
```

## LLM 설정

앱 실행 후 우상단 **Settings(⚙)** 버튼을 클릭해 설정합니다.  
설정값은 브라우저 localStorage에 저장됩니다.

| 항목 | 설명 | 예시 |
|---|---|---|
| Endpoint URL | LLM API 베이스 URL | `http://localhost:11434/v1` |
| API Key | 인증키 (없으면 임의값) | `ollama` |
| Model | 사용할 모델명 | `llama3`, `qwen2.5`, `mistral` |

**Ollama 사용 시:**
```bash
ollama pull llama3
ollama serve
```

## Chromium 경로 우선순위

`analyze_equipment` 스킬 실행 시 아래 순서로 Chromium 실행 파일을 탐색합니다.

| 우선순위 | 방법 | 설정 방법 |
|---|---|---|
| 1 | 환경변수 | `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=C:\path\to\chrome.exe` |
| 2 | 로컬 설치 | `server/browsers/chrome-win64/chrome.exe` |
| 3 | Playwright 기본 경로 | `playwright install chromium` 실행 시 자동 설정 |

환경변수로 지정하려면:
```bat
set PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=C:\path\to\chrome.exe
python server\main.py
```

## Skills System

모든 자동화 시나리오는 **Skill** 단위로 관리됩니다.  
`server/skills/` 폴더의 Python 파일을 서버 시작 시 자동으로 스캔하여 등록합니다.

### 기본 제공 스킬

| 스킬명 | 설명 | 파라미터 |
|---|---|---|
| `analyze_equipment` | Edge 브라우저로 설비 진단 사이트 접속 및 데이터 추출 | `equipment_id: str` |
| `run_application` | Windows 검색창을 통해 앱 실행 | `app_name: str` |
| `desktop_interaction` | UI 요소 클릭 (좌표 또는 이미지 매칭) | `button_name: str`, `x?: int`, `y?: int` |

### 새 스킬 추가

`server/skills/` 폴더에 파일을 추가하면 서버 재시작 시 자동으로 로드됩니다.

```python
# server/skills/my_skill.py
from .skill_base import SkillBase

class MySkill(SkillBase):
    name = "my_skill"
    description = "스킬 설명 (LLM이 언제 이 스킬을 쓸지 판단하는 기준)"
    parameters = {
        "type": "object",
        "properties": {
            "target": {"type": "string", "description": "대상"}
        },
        "required": ["target"]
    }

    async def run(self, target: str, **kwargs) -> dict:
        # 자동화 로직 구현
        return {"status": "success", "message": f"{target} 처리 완료"}
```

### 스킬 직접 테스트 (LLM 없이)

`server/test_skill.py`를 사용하면 LLM을 거치지 않고 스킬을 바로 실행할 수 있습니다.

```bash
cd server

# 등록된 스킬 목록 + 파라미터 확인
python test_skill.py

# 파라미터 없이 실행
python test_skill.py run_ees

# 파라미터 전달 (key=value)
python test_skill.py open_browser url=https://google.com

# JSON 값 전달 (숫자, bool, 리스트, dict 지원)
python test_skill.py my_skill count=3 flag=true items=[1,2,3]
```

결과는 JSON 형태로 출력됩니다.

## API Endpoints

| Method | Endpoint | 설명 |
|---|---|---|
| `GET` | `/api/health` | 서버 상태 확인 |
| `POST` | `/api/chat` | LLM 채팅 (SSE 스트리밍 지원) |
| `POST` | `/api/chat/reset` | 서버 측 대화 컨텍스트 초기화 |
| `GET` | `/api/skills` | 등록된 스킬 목록 조회 |
| `POST` | `/api/skills/{skill_name}/run` | 스킬 직접 실행 |

### Chat Request

```json
POST /api/chat
Headers:
  X-LLM-Endpoint: http://localhost:11434/v1
  X-LLM-Key: ollama

Body:
{
  "messages": [{"role": "user", "content": "CAC681 설비 분석해줘"}],
  "model": "llama3",
  "stream": true
}
```

## Example Workflow

사용자: **"CAC681 설비 분석해줘"**

```
1. LLM → analyze_equipment(equipment_id="CAC681") 호출 결정
2. Playwright → Edge 브라우저 실행 → 설비 진단 사이트 접속 → 데이터 추출
3. (옵션) run_application(app_name="EES UI 2.0") → Windows 검색창으로 앱 실행
4. (옵션) desktop_interaction(button_name="PnP 데스크탑") → UI 클릭
5. LLM → 수집된 결과를 종합하여 채팅창에 보고
```

## UI Features

- **다크모드** 채팅 인터페이스
- **실시간 스트리밍** 응답 (SSE)
- **Session Reset** — 채팅 기록 및 서버 컨텍스트 초기화
- **Skills 패널** — 사이드바에서 등록된 스킬 목록 확인
- **시스템 트레이** — 창 닫기 시 트레이로 최소화, 더블클릭으로 복원

## License

MIT
