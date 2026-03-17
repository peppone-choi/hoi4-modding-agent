# HOI4 Modding Agent

Hearts of Iron IV 모드 전용 AI 어시스턴트.
모드 폴더를 지정하면 자동으로 구조를 스캔하고, 채팅으로 캐릭터/이벤트/포커스/포트레잇을 관리할 수 있다.

## 주요 기능

- **자동 스캔** — 국가, 캐릭터, 이벤트, 이념, 포커스 트리를 시작 시 자동 감지
- **51개 도구** — 내장 16개 + MCP 35개 (Context7, Tavily, Filesystem, Memory, Fetch, Sequential Thinking)
- **실시간 스트리밍** — 응답이 토큰 단위로 실시간 출력 (Anthropic Streaming API)
- **자율 실행** — 복잡한 작업을 계획→실행→검증 루프로 자율적으로 끝까지 처리 (Ralph Loop / Ultrawork 스타일)
- **허위 보고 방지** — 도구를 호출하지 않은 행동을 "했다"고 주장하는 것을 원천 차단
- **의도 분석 (IntentGate)** — 유저 메시지의 진짜 의도를 파악하고 즉시 행동
- **전략 기획 (Prometheus)** — 복잡한 작업은 자동으로 계획 수립 후 즉시 실행
- **진행 추적 (Todo Enforcer)** — 다단계 작업 진행 상황을 `[ 3/5 ] ✅` 형식으로 실시간 보고
- **세션 유지 + 검색** — SQLite 기반 채팅 기록, 도구 실행 이력 보존, 키워드 검색
- **MCP 지원** — 외부 MCP 서버 연결로 도구 무한 확장 가능
- **팩트체크** — 실존 정치인/선거/정당 정보는 반드시 웹 검색 후 답변
- **포트레잇 파이프라인** — 얼굴 감지 → 배경 제거 → Gemini 스타일 전사 → 스캔라인 오버레이

## MCP (Model Context Protocol) 지원

에이전트가 외부 MCP 서버에 연결하여 도구를 확장할 수 있다.
기본 설정으로 6개 서버, 35개 도구가 포함되어 있다.

### 기본 MCP 서버

| 서버                    | 도구 수 | 용도                                                                     | API 키           |
| ----------------------- | ------- | ------------------------------------------------------------------------ | ---------------- |
| **Context7**            | 2       | 라이브러리/프레임워크 공식 문서 조회. HOI4 모딩 문서 4,545개 스니펫 포함 | 불필요           |
| **Tavily**              | 5       | 웹 검색, URL 콘텐츠 추출, 사이트 크롤링, 사이트맵, 종합 리서치           | `TAVILY_API_KEY` |
| **Filesystem**          | 14      | 파일 읽기/쓰기/편집/검색/이동, 디렉토리 트리, 파일 메타데이터            | 불필요           |
| **Memory**              | 9       | 지식 그래프 — 엔티티/관계 생성·검색·삭제 (세션 간 기억 유지)             | 불필요           |
| **Sequential Thinking** | 1       | 복잡한 문제의 단계별 사고 체인 (Chain-of-Thought)                        | 불필요           |
| **Fetch**               | 4       | URL → HTML/Markdown/텍스트/JSON 변환 (위키 페이지 파싱 등)               | 불필요           |

### MCP 설정

```bash
# 1. 설정 파일 복사
cp mcp_servers.json.example mcp_servers.json

# 2. MCP Python 패키지 설치
pip install mcp nest-asyncio

# 3. Node.js + npx 필요 (MCP 서버는 npx로 실행됨)
# macOS: brew install node
# Windows: https://nodejs.org 에서 설치

# 4. 앱 실행 — MCP 도구가 자동으로 에이전트에 추가됨
hoi4-agent .
```

사이드바에서 MCP 연결 상태를 확인할 수 있다:

- `🔌 MCP: ✅ (35개 도구)` — 정상 연결
- `🔌 MCP: ⚠️ pip install mcp 필요` — Python 패키지 미설치
- `🔌 MCP: — (mcp_servers.json 없음)` — 설정 파일 없음

### 커스텀 MCP 서버 추가

`mcp_servers.json`을 편집하여 원하는 MCP 서버를 추가할 수 있다:

```json
{
  "my-server": {
    "command": "npx",
    "args": ["-y", "my-mcp-server-package"],
    "env": {
      "API_KEY": "${MY_API_KEY}"
    }
  }
}
```

`${변수명}` 형식은 `.env` 파일의 환경변수로 자동 치환된다.

## 에이전트 행동 규칙

이 에이전트는 다음 규칙을 엄격히 따른다:

- **허위 보고 금지**: 도구를 호출하지 않은 행동을 "했다"고 절대 주장하지 않음
- **증거 기반 완료**: "완료했습니다"는 모든 도구의 성공 결과가 있을 때만 사용
- **계획 vs 실행 구분**: "~하겠습니다"(계획)와 "~했습니다"(완료)를 엄격히 구분
- **오류 즉시 보고**: 도구 오류 발생 시 숨기지 않고 그대로 유저에게 전달
- **자기 검증**: 파일 저장 후 read_file로 확인, 캐릭터 추가 후 find_entity로 확인
- **자율 실행**: 복잡한 작업은 자동으로 계획→실행→검증 루프를 돌며 끝까지 처리
- **배치 처리**: 여러 항목 작업 시 멈추지 않고 순차 처리, 진행 상황 실시간 보고

## 사전 준비

### 필수 소프트웨어

| 소프트웨어 | 버전      | 설치 방법                        |
| ---------- | --------- | -------------------------------- |
| Python     | 3.11 이상 | 아래 참조                        |
| Git        | 최신      | 아래 참조                        |
| pip        | 최신      | Python과 함께 설치됨             |
| C 컴파일러 | -         | 아래 참조 (포트레잇 기능에 필요) |

### Python 설치

**macOS**

```bash
# Homebrew로 설치 (Homebrew가 없으면: https://brew.sh)
brew install python@3.12

# 설치 확인
python3 --version
```

**Windows**

1. https://www.python.org/downloads/ 에서 Python 3.12 다운로드
2. 설치 시 **"Add python.exe to PATH"** 체크박스를 반드시 선택
3. 설치 완료 후 새 터미널(PowerShell 또는 CMD)을 열어 확인:

```powershell
python --version
```

### Git 및 C 컴파일러 설치

**macOS**

Xcode Command Line Tools 하나로 Git과 C 컴파일러가 모두 설치된다.
포트레잇의 배경 제거(`rembg`)가 내부적으로 `numba` → `llvmlite`를 빌드하는데, C 헤더 파일이 필요하다.

```bash
# 필수 — Git + C 컴파일러 + 시스템 헤더 한 번에 설치
xcode-select --install
```

설치 후에도 `stdlib.h not found` 에러가 발생하면:

```bash
# SDK 경로를 명시적으로 지정
export SDKROOT=$(xcrun --sdk macosx --show-sdk-path)

# .zshrc에 영구 추가 (터미널을 열 때마다 자동 적용)
echo 'export SDKROOT=$(xcrun --sdk macosx --show-sdk-path)' >> ~/.zshrc
```

**Windows**

1. https://git-scm.com/download/win 에서 Git 다운로드 → 기본 옵션으로 설치
2. [Visual Studio Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/) 다운로드
3. 설치 시 **"C++를 사용한 데스크톱 개발"** 워크로드를 선택
4. 설치 후 새 터미널에서 확인:

```powershell
git --version
cl
```

## 설치

### 1. 저장소 클론

**macOS**

```bash
cd ~/Documents
git clone https://github.com/your-org/hoi4-modding-agent.git
cd hoi4-modding-agent
```

**Windows**

```powershell
cd $HOME\Documents
git clone https://github.com/your-org/hoi4-modding-agent.git
cd hoi4-modding-agent
```

### 2. 가상환경 생성 및 활성화

**macOS**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

**Windows**

```powershell
python -m venv .venv
.venv\Scripts\activate
```

> 터미널 앞에 `(.venv)` 가 표시되면 활성화 성공.
> Windows에서 스크립트 실행이 차단될 경우:
>
> ```powershell
> Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
> ```

### 3. 패키지 설치

**방법 A: lockfile로 설치 (권장 — 검증된 버전 조합)**

의존성 충돌 없이 한 번에 설치된다:

```bash
pip install -r requirements-lock.txt
pip install -e .
```

**방법 B: setup.py extras로 설치**

기본 설치 (채팅 에이전트만):

```bash
pip install -e .
```

전체 설치 (검색 + 포트레잇):

```bash
pip install -e ".[search,portrait]"
```

> **중요**: `portrait` 옵션은 `llvmlite`/`numba`를 설치한다.
> 이 패키지들은 **반드시 프리빌드 휠**로 설치해야 한다.
> 소스 빌드가 시도되면서 실패하는 경우, 아래 **문제 해결** 섹션을 참고.

**방법 B에서 설치 순서가 꼬일 경우 수동 설치:**

```bash
# 1단계: 빌드 필요 패키지를 프리빌드 휠로 먼저 설치
pip install --only-binary=:all: llvmlite numba

# 2단계: numpy 버전 고정 (mediapipe는 numpy<2 필요)
pip install "numpy>=1.26.0,<2"

# 3단계: opencv 버전 고정 (numpy<2와 호환)
pip install "opencv-python>=4.9.0.80,<4.12" "opencv-contrib-python>=4.9.0.80,<4.12"

# 4단계: 나머지 설치
pip install -e ".[search,portrait]"
```

### 4. API 키 설정

```bash
cp .env.example .env
```

Windows:

```powershell
copy .env.example .env
```

`.env` 파일을 텍스트 에디터로 열어 API 키를 입력:

```env
# 필수 — Claude API (채팅 에이전트)
ANTHROPIC_API_KEY=sk-ant-xxxxx

# 필수 — Gemini API (포트레잇 생성)
# https://aistudio.google.com/apikey 에서 무료 발급
GEMINI_API_KEY=xxxxx

# 선택 — 웹 검색 (없으면 DuckDuckGo로 자동 폴백)
TAVILY_API_KEY=tvly-xxxxx
```

### API 키 발급 방법

| API              | 발급 링크                                   | 비용                  |
| ---------------- | ------------------------------------------- | --------------------- |
| Anthropic Claude | https://console.anthropic.com/settings/keys | 유료 (사용량 기반)    |
| Google Gemini    | https://aistudio.google.com/apikey          | 무료 티어 있음        |
| Tavily Search    | https://app.tavily.com/home                 | 무료 티어 있음 (선택) |

## 실행

### 방법 1: CLI 명령어 (권장)

가상환경이 활성화된 상태에서:

**macOS**

```bash
# 모드 폴더를 지정해서 실행
hoi4-agent /path/to/your/hoi4/mod

# 현재 디렉토리가 모드 폴더이면
hoi4-agent .
```

**Windows**

```powershell
# 모드 폴더를 지정해서 실행
hoi4-agent "C:\Users\사용자명\Documents\Paradox Interactive\Hearts of Iron IV\mod\your-mod"

# 현재 디렉토리가 모드 폴더이면
hoi4-agent .
```

### 방법 2: Streamlit 직접 실행

```bash
# macOS
MOD_ROOT=/path/to/your/mod streamlit run hoi4_agent/ui/app.py
```

```powershell
# Windows
$env:MOD_ROOT="C:\path\to\your\mod"
streamlit run hoi4_agent/ui/app.py
```

실행하면 브라우저에서 `http://localhost:8501` 이 자동으로 열린다.

### HOI4 모드 폴더 위치

| OS      | 기본 경로                                                                |
| ------- | ------------------------------------------------------------------------ |
| macOS   | `~/Documents/Paradox Interactive/Hearts of Iron IV/mod/`                 |
| Windows | `C:\Users\사용자명\Documents\Paradox Interactive\Hearts of Iron IV\mod\` |

## 포트레잇 생성

### 채팅에서 사용

에이전트 채팅창에서 자연어로 요청:

```
"도널드 트럼프 포트레잇 만들어줘"
"Abdul Rashid Dostum 장군 초상화 생성해줘"
```

에이전트가 자동으로 사진 검색 → 다운로드 → Gemini 스타일 전사 → HOI4 포트레잇 생성.

### CLI로 직접 사용

```bash
# 단일 이미지 처리
python -m hoi4_agent.tools.portrait.run_pipeline single input.jpg output.png

# 웹 검색 + 자동 처리
python -m hoi4_agent.tools.portrait.run_pipeline search "인물명" --tag USA --max 5
```

### 포트레잇 파이프라인 모드

| 모드            | 설명                                            | 필요 API       |
| --------------- | ----------------------------------------------- | -------------- |
| `gemini` (기본) | Gemini 3.1 Flash로 TFR 스타일 전사. 고품질      | GEMINI_API_KEY |
| `local`         | 로컬 알고리즘 기반 TFR 스타일. Gemini 없이 동작 | 없음           |

```python
from hoi4_agent.tools.portrait.pipeline.portrait_pipeline import PortraitPipeline

# Gemini 모드 (기본)
pipeline = PortraitPipeline(mode="gemini")

# 로컬 모드 (API 키 불필요)
pipeline = PortraitPipeline(mode="local")

# 커스텀 스타일 프롬프트
pipeline = PortraitPipeline(
    mode="gemini",
    style_prompt="Make this look like a WW2-era oil painting portrait",
)
```

## 도구 목록 (16개 내장 + 35개 MCP)

### 내장 도구 (16개)

| 카테고리 | 도구                | 설명                                    |
| -------- | ------------------- | --------------------------------------- |
| 검색     | `web_search`        | 웹 검색 (Tavily → DuckDuckGo 자동 폴백) |
|          | `wiki_lookup`       | Wikipedia/Wikidata 인물/국가/정당 조회  |
| 파일     | `read_file`         | 모드 파일 읽기                          |
|          | `write_file`        | 모드 파일 쓰기                          |
|          | `safe_write`        | 자동 백업 후 안전 저장                  |
|          | `list_files`        | 디렉토리 파일 목록                      |
| 모드     | `search_mod`        | 모드 내 텍스트/패턴 검색                |
|          | `find_entity`       | 캐릭터/이벤트/포커스 검색               |
|          | `country_details`   | 국가별 전체 파일 조회                   |
|          | `get_schema`        | HOI4 파일 스키마 조회                   |
|          | `validate_pdx`      | PDX Script 검증                         |
|          | `diff_preview`      | 수정 전 변경사항 미리보기               |
|          | `analyze_mod`       | 모드 건강 진단                          |
| 포트레잇 | `search_portraits`  | 웹에서 인물 사진 검색                   |
|          | `generate_portrait` | HOI4 포트레잇 생성 (Gemini)             |
|          | `show_image`        | 이미지 채팅에 표시                      |

### MCP 도구 (35개, mcp_servers.json 설정 시)

| MCP 서버            | 주요 도구                                                      | 설명                                                |
| ------------------- | -------------------------------------------------------------- | --------------------------------------------------- |
| Context7            | `resolve-library-id`, `query-docs`                             | 공식 문서 검색 (HOI4 모딩 문서 4,545개 스니펫 포함) |
| Tavily              | `tavily_search`, `tavily_extract`, `tavily_research` 등 5개    | AI 웹 검색, URL 추출, 사이트 크롤링, 종합 리서치    |
| Filesystem          | `read_file`, `write_file`, `edit_file`, `search_files` 등 14개 | 파일 읽기/쓰기/편집/검색/이동, 디렉토리 트리        |
| Memory              | `create_entities`, `search_nodes`, `read_graph` 등 9개         | 지식 그래프 — 엔티티/관계 생성·검색 (세션 간 기억)  |
| Sequential Thinking | `sequentialthinking`                                           | 복잡한 문제의 단계별 사고 체인 (CoT)                |
| Fetch               | `fetch_html`, `fetch_markdown`, `fetch_txt`, `fetch_json`      | URL → HTML/Markdown/텍스트/JSON 변환                |

## 프로젝트 구조

```
hoi4_agent/
├── cli.py                  # CLI 진입점 (hoi4-agent 명령어)
├── config/
│   └── settings.py         # 환경변수, 모델, max_tokens, max_tool_rounds 설정
├── core/
│   ├── scanner.py          # 모드 자동 스캐너
│   ├── mod_tools.py        # 모드 파일 조작
│   ├── wiki_tools.py       # Wikipedia/Wikidata 조회
│   ├── chat_session.py     # SQLite 세션 관리 + 도구 이력 + 검색
│   ├── prompt.py           # 시스템 프롬프트 (IntentGate, Prometheus, 자율 실행)
│   ├── mcp_client.py       # MCP 클라이언트 매니저
│   └── wiki/               # 위키 업데이터 모듈
├── ui/
│   ├── app.py              # Streamlit 메인 앱 + MCP 초기화
│   ├── sidebar.py          # 세션 관리 + 검색 + MCP 상태
│   └── chat_view.py        # 스트리밍 채팅 + 도구 이력 보존
└── tools/
    ├── executor.py          # 도구 실행 엔진 + MCP 라우팅
    ├── search.py            # 웹 검색 (Tavily → Google → DDGS)
    └── portrait/            # 포트레잇 생성 파이프라인
        ├── run_pipeline.py  # CLI 진입점
        ├── pipeline/        # 파이프라인 오케스트레이터
        ├── core/            # 얼굴 감지, 부위 마스크
        ├── effects/         # TFR 스타일, 스캔라인
        ├── search/          # 멀티소스 이미지 검색
        └── templates/       # Gemini 의상 합성

mcp_servers.json             # MCP 서버 설정 (6개 서버, 35개 도구)
mcp_servers.json.example     # MCP 설정 예제
```

## 개발

### 개발용 설치

```bash
pip install -e ".[dev,search,portrait,mcp]"
```

### MCP 설정 (선택)

```bash
# MCP 도구 활성화 (Node.js + npx 필요)
cp mcp_servers.json.example mcp_servers.json
pip install mcp nest-asyncio
```

### 테스트 실행

```bash
# 전체 테스트
pytest tests/ -v

# 포트레잇 파이프라인 테스트만
pytest tests/test_portrait_pipeline.py -v
```

### 문제 해결

> **팁**: 대부분의 설치 문제는 `pip install -r requirements-lock.txt`로 해결된다.
> lockfile에는 검증된 버전 조합이 고정되어 있다.

---

**`ModuleNotFoundError: No module named 'xxx'`**

가상환경이 활성화되어 있는지 확인:

```bash
# macOS
source .venv/bin/activate

# Windows
.venv\Scripts\activate
```

---

**`Failed building wheel for numba` / `Failed building wheel for llvmlite`**

`llvmlite`와 `numba`는 C 확장을 포함하고 있어서,
소스에서 빌드하면 높은 확률로 실패한다. **반드시 프리빌드 휠로 설치해야 한다.**

```bash
pip install --only-binary=:all: llvmlite numba
```

이 명령이 성공한 뒤에 나머지를 설치:

```bash
pip install -e ".[search,portrait]"
```

> `--only-binary=:all:` 옵션은 소스 빌드를 시도하지 않고
> PyPI에서 미리 컴파일된 `.whl` 파일만 사용한다.

---

**macOS에서 `stdlib.h file not found`**

Xcode Command Line Tools가 설치되었는데도 SDK 경로를 못 찾는 경우:

```bash
# SDK 경로 확인
xcrun --sdk macosx --show-sdk-path

# 환경변수 설정
export SDKROOT=$(xcrun --sdk macosx --show-sdk-path)

# .zshrc에 영구 추가
echo 'export SDKROOT=$(xcrun --sdk macosx --show-sdk-path)' >> ~/.zshrc
source ~/.zshrc
```

---

**`spawn() got an unexpected keyword argument 'dry_run'`**

`llvmlite` 소스 빌드가 최신 `setuptools`와 호환되지 않는 문제.
프리빌드 휠을 사용하면 해결:

```bash
pip install --only-binary=:all: llvmlite numba
```

---

**`numpy` 버전 충돌 (`mediapipe requires numpy<2` vs `rembg requires numpy>=2.3`)**

이 프로젝트는 **`numpy<2`** 를 사용한다 (`mediapipe` 요구).
`rembg 2.0.70+`는 `numpy>=2.3`을 요구하므로 **`rembg<2.0.70`** 을 사용한다.

```bash
pip install "numpy>=1.26.0,<2" "rembg>=2.0.67,<2.0.70"
```

`opencv-python 4.12+`도 `numpy>=2`를 요구하므로 **`4.11.x`** 를 사용:

```bash
pip install "opencv-python>=4.9.0.80,<4.12" "opencv-contrib-python>=4.9.0.80,<4.12"
```

> `requirements-lock.txt`에 이 버전 조합이 모두 고정되어 있다.
> 충돌이 해결 안 되면 lockfile로 설치하는 것이 가장 확실하다.

---

**`No module named 'onnxruntime'`**

`rembg`가 내부적으로 `onnxruntime`을 사용하지만 자동 설치하지 않는 경우가 있다:

```bash
pip install onnxruntime
```

---

**Windows에서 C++ 빌드 관련 에러 전반**

1. [Visual Studio Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/) 다운로드
2. **"C++를 사용한 데스크톱 개발"** 워크로드 선택 후 설치
3. 새 PowerShell을 열고 다시 설치

그래도 실패하면 프리빌드 휠로 우회:

```powershell
pip install --only-binary=:all: llvmlite numba
pip install -e ".[search,portrait]"
```

---

**`ANTHROPIC_API_KEY is required` 에러**

`.env` 파일이 프로젝트 루트에 있는지, 키가 올바른지 확인:

```bash
ls .env          # macOS
dir .env         # Windows
```

---

**포트 `8501` 이 이미 사용 중**

```bash
hoi4-agent . --port 8502
```

---

**전부 다 꼬였을 때: 클린 재설치**

```bash
# 가상환경 삭제 후 재생성
deactivate
rm -rf .venv                          # macOS
# rmdir /s /q .venv                   # Windows

python3 -m venv .venv
source .venv/bin/activate             # macOS
# .venv\Scripts\activate              # Windows

# lockfile로 깨끗하게 설치
pip install -r requirements-lock.txt
pip install -e .
```

## 라이선스

MIT
