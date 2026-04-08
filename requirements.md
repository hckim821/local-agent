# Project: Local Computer-Use Chat UI (Toy Project)

이 프로젝트는 로컬 LLM을 기반으로 사용자의 PC 제어(Computer Use) 기능을 수행하는 초경량 데스크탑 애플리케이션입니다. 기능의 복잡성보다는 **"LLM - 백엔드(Automation) - 프론트엔드(Electron)"** 간의 연결성과 **"Skill 기반의 확장성"** 확인에 집중합니다.

## 🛠 Tech Stack
- **Frontend**: Vue 3, TypeScript, Ant Design (Antd), Tailwind CSS
- **Backend**: FastAPI (Python 3.10+)
- **Desktop**: Electron (Vue 앱 패키징)
- **LLM**: Local LLM (OpenAI-compatible API base)
- **Automation**: Playwright (Web), PyAutoGUI (OS Control)

---

## 🤖 Agent Team Roles & Responsibilities

Claude Code 실행 시 다음 에이전트 구성을 참고하여 작업을 할당하세요.

| 에이전트 역할 | 주요 책임 범위 (Responsibilities) | 구현 핵심 기능 |
| :--- | :--- | :--- |
| **Architect Agent** | 프로젝트 전체 구조 설계 및 에이전트 간 워크플로우 관리 | 프로젝트 초기 구조 생성, API 규격 정의, 프로세스 실행 스크립트 작성 |
| **Frontend Agent** | Vue 3 + Electron 기반의 UI 구현 및 상태 관리 | 채팅 인터페이스(Single Session), API 설정 창, Electron 메인/렌더러 프로세스 설정 |
| **Action Agent** | FastAPI 기반의 백엔드 개발 및 실제 하드웨어/브라우저 제어 로직 | Computer Use 핵심 로직, Local LLM 연동 프록시, OS 명령 실행부 |
| **Skill Manager Agent** | 'Skill' 시스템 설계 및 개별 시나리오 스크립트화 | Skill 등록/관리 API, 시나리오별 JSON 스키마 정의 (Edge 접속, 파일 검색 등) |

---

## 📝 상세 구현 기능 정의

### 1. Frontend (Vue + Electron)
- **Chat UI**: 
  - 대화 내역은 DB에 저장하지 않으며 현재 세션만 표시.
  - 상단에 'Session Reset' 버튼을 배치하여 화면 및 백엔드 컨텍스트 초기화.
- **Settings**: 
  - 로컬 LLM의 Endpoint URL 및 API Key를 입력하고 로컬 스토리지에 저장하는 기능.
- **Electron Shell**: 
  - FastAPI 서버와 함께 실행되는 구조.
  - 시스템 트레이 아이콘 및 기본 창 크기 설정.

### 2. Backend (FastAPI)
- **LLM Proxy**: 프론트엔드의 요청을 받아 로컬 LLM에 전달하고 결과를 파싱.
- **Computer Use Engine**:
  - LLM의 'Skill' 호출(Tool Calling) 신호를 해석하여 실제 Python 스크립트 실행.
  - **Browser Automation**: Edge 브라우저를 실행하여 특정 URL(`nxswe.samsungds.net`) 접근 및 특정 행(Row) 데이터 추출.
  - **OS Automation**: `pyautogui` 등을 활용해 윈도우 검색창 제어 및 앱 실행.

### 3. Skills System (The 'Skill' Registry)
- 모든 시나리오는 `Skill` 단위로 추상화되어 관리됨.
- **구현 대상 Skills**:
  1. `analyze_equipment(equipment_id)`: Edge 브라우저를 통한 설비 진단 사이트 분석.
  2. `run_application(app_name)`: 윈도우 검색을 통한 특정 앱 실행.
  3. `desktop_interaction(button_name)`: 실행된 앱 내의 UI 요소 클릭 (PnP 데스크탑, MCC 등).

---

## 🚀 시나리오 워크플로우 (User Query: "CAC681 설비 분석해줘")

1. **LLM 해석**: "설비 분석" 의도를 파악하고 `analyze_equipment` 스킬 호출.
2. **Step 1 (Web)**: Edge 브라우저 실행 -> `nxswe.samsungds.net/...` 접속 -> `CAC681` 데이터 획득.
3. **Step 2 (OS)**: 윈도우 검색창 활성화 -> "EES UI 2.0" 입력 및 Enter.
4. **Step 3 (Interaction)**: 실행된 앱 내에서 이미지 매칭 또는 좌표 기반으로 "PnP 데스크탑" 및 "MCC" 순차 클릭.
5. **Final**: 수행 결과를 채팅창에 보고.

---

## 📂 Project Structure (Proposed)
```text
.
├── apps/
│   ├── frontend/         # Vue 3 + Vite + Tailwind + Antd
│   └── desktop/          # Electron Main Process
├── server/
│   ├── main.py           # FastAPI Entry Point
│   ├── core/             # LLM Connector & Orchestrator
│   └── skills/           # Action Scripts (Skill Registry)
│       ├── browser_skill.py
│       └── os_skill.py
└── shared/               # Types & Configs
```

---

## 🛠 실행 가이드 (Claude Code 전달용)
1. 상기 구조에 따라 프로젝트를 초기화해줘.
2. `Frontend Agent`는 `antd`를 사용하여 깔끔한 다크 모드 채팅 UI를 만들어줘.
3. `Action Agent`는 `playwright`를 사용하여 Edge 브라우저 제어 로직을 먼저 구현해줘.
4. `Skill Manager Agent`는 새로운 스킬을 쉽게 추가할 수 있도록 `skills/` 폴더 내의 스크립트를 자동 로드하는 구조로 만들어줘.

