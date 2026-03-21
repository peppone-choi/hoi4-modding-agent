# HoI4 포트레잇 관리자

## 실행 방법

### macOS
```bash
# 더블클릭
portrait_manager.command

# 또는 터미널
.venv/bin/python portrait_selector.py
```

### Windows
```cmd
:: 더블클릭
portrait_manager.bat

:: 또는 명령 프롬프트
.venv\Scripts\python portrait_selector.py
```

### 옵션
```bash
# 모드 폴더 지정
.venv/bin/python portrait_selector.py --mod /path/to/mod

# 포트 변경
.venv/bin/python portrait_selector.py --port 8080

# 둘 다
.venv/bin/python portrait_selector.py --mod /path/to/mod --port 8080
```

## 기능

| 기능 | 설명 |
|------|------|
| 검색 | 인물 사진 웹 검색 (15장) |
| URL 추가 | 직접 이미지 URL 입력 |
| 사진 업로드 | 로컬 파일 업로드 |
| 미리보기 | 생성 후 저장 전 확인 |
| 저장 / 다른 이름 저장 | 포트레잇 저장 |
| 아이콘 자동 생성 | 저장 시 65x67 아이콘 자동 |
| 재생성 | 프롬프트 변경 후 재생성 |
| 캐시 비우기 | 검색/미리보기 캐시 삭제 |
| 설정 | API 키, 배경색, 주사선, 블렌드 |
| 캐릭터 추가 | 새 인물 생성 + 연결 |
| 태그/역할 필터 | 국가별, 역할별 필터링 |

## 파이프라인

```
사진 선택 → 얼굴 크롭 (156x210) → rembg 배경 제거
→ Gemini 색보정 (실사 유지) → 배경 템플릿 틴트 합성
→ 주사선 오버레이 → 미리보기 → 저장 + 아이콘 자동 생성
```

## 필요 환경

- Python 3.12 + .venv
- `GEMINI_API_KEY` (설정에서 입력 가능)
- Flask, Pillow, rembg, google-genai
