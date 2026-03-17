"""
System prompt builder and tool definitions for the Claude API.
"""
from hoi4_agent.core.scanner import ModContext


TOOLS = [
    {"name": "web_search", "description": "웹 검색 (Tavily→DDGS 자동 폴백). 현직 정치인·현재 집권당·최근 선거 등은 반드시 이 도구를 먼저 사용.", "input_schema": {"type": "object", "properties": {"query": {"type": "string", "description": "검색 쿼리"}}, "required": ["query"]}},
    {"name": "wiki_lookup", "description": "Wikipedia/Wikidata 직접 조회. 구조화된 인물/국가 데이터 반환.", "input_schema": {"type": "object", "properties": {"lookup_type": {"type": "string", "enum": ["person", "country", "parties", "positions"], "description": "person=인물, country=국가, parties=정당목록(QID), positions=직위(QID+날짜)"}, "query": {"type": "string", "description": "검색어/QID"}, "country_tag": {"type": "string", "description": "국가 태그 (선택)"}, "date": {"type": "string", "description": "기준 날짜 (기본: 2026-01-01)"}}, "required": ["lookup_type", "query"]}},
    {"name": "read_file", "description": "모드 파일 읽기. 경로는 모드 루트 기준 상대경로.", "input_schema": {"type": "object", "properties": {"path": {"type": "string", "description": "파일 경로"}}, "required": ["path"]}},
    {"name": "write_file", "description": "모드 파일 직접 쓰기 (백업 없음). 안전한 저장은 safe_write 사용 권장.", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"name": "safe_write", "description": "자동 백업 후 파일 저장. 기존 파일이 있으면 .backups/ 에 백업본 생성.", "input_schema": {"type": "object", "properties": {"path": {"type": "string", "description": "파일 경로"}, "content": {"type": "string", "description": "파일 내용"}, "backup": {"type": "boolean", "description": "백업 여부 (기본: true)"}}, "required": ["path", "content"]}},
    {"name": "list_files", "description": "디렉토리 내 파일 목록.", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "pattern": {"type": "string", "description": "glob 패턴 (기본: *)"}}, "required": ["path"]}},
    {"name": "search_mod", "description": "모드 파일 내 텍스트/패턴 검색. 캐릭터 ID, 이벤트 ID, 로컬 키 등을 찾을 때.", "input_schema": {"type": "object", "properties": {"query": {"type": "string"}, "file_type": {"type": "string", "description": "확장자 필터 (txt/yml)"}, "directory": {"type": "string", "description": "검색 범위 디렉토리"}}, "required": ["query"]}},
    {"name": "find_entity", "description": "캐릭터/이벤트/포커스를 이름 또는 ID로 빠르게 검색.", "input_schema": {"type": "object", "properties": {"entity_name": {"type": "string", "description": "검색어"}, "entity_type": {"type": "string", "enum": ["", "character", "event", "focus"], "description": "엔티티 타입 필터 (빈 문자열=전체)"}}, "required": ["entity_name"]}},
    {"name": "country_details", "description": "특정 국가의 모든 관련 파일(히스토리/캐릭터/포커스/이벤트)과 설정을 한번에 조회.", "input_schema": {"type": "object", "properties": {"tag": {"type": "string", "description": "국가 태그 (예: USA, SOV, KOR)"}}, "required": ["tag"]}},
    {"name": "get_schema", "description": "HOI4 파일 타입의 스키마(유효 키/구조). 'list'=전체 타입, 'scopes'=스코프, 'modifiers'=모디파이어.", "input_schema": {"type": "object", "properties": {"file_type": {"type": "string"}}, "required": ["file_type"]}},
    {"name": "validate_pdx", "description": "PDX Script 를 스키마 대비 검증. 중괄호 매칭, 필수 키, popularities 합계 등.", "input_schema": {"type": "object", "properties": {"content": {"type": "string"}, "file_type": {"type": "string"}}, "required": ["content", "file_type"]}},
    {"name": "diff_preview", "description": "파일 수정 전 변경사항 diff 미리보기. 기존 파일과 새 내용 비교.", "input_schema": {"type": "object", "properties": {"path": {"type": "string", "description": "파일 경로"}, "new_content": {"type": "string", "description": "새 내용"}}, "required": ["path", "new_content"]}},
    {"name": "analyze_mod", "description": "모드 건강 진단. 누락 초상화, 중복 ID, 로컬 누락, 고아 GFX 등 검사.", "input_schema": {"type": "object", "properties": {"check_type": {"type": "string", "enum": ["all", "portraits", "loc", "duplicates", "orphans"], "description": "검사 타입 (기본: all)"}}, "required": []}},
    {"name": "search_portraits", "description": "웹에서 인물 사진 검색/다운로드.", "input_schema": {"type": "object", "properties": {"person_name": {"type": "string"}, "title": {"type": "string"}, "country_tag": {"type": "string"}, "max_results": {"type": "integer"}}, "required": ["person_name"]}},
    {"name": "generate_portrait", "description": "인물 사진을 HOI4 포트레잇으로 변환 (Gemini 스타일 적용 + 스캔라인).", "input_schema": {"type": "object", "properties": {"input_image_path": {"type": "string"}, "output_path": {"type": "string"}, "style_prompt": {"type": "string"}}, "required": ["input_image_path", "output_path", "style_prompt"]}},
    {"name": "show_image", "description": "이미지를 채팅에 표시.", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
]


def build_system_prompt(ctx: ModContext) -> str:
    conv_lines = (
        "\n".join(f"  {k}: {v}" for k, v in ctx.naming_conventions.items())
        if ctx.naming_conventions
        else "  (자동 감지 안됨 — read_file 로 기존 파일 참고)"
    )
    return f"""너는 HOI4 모드 "{ctx.mod_name or '(알 수 없음)'}" 전용 모딩 에이전트야.
유저와 대화하면서 모드 파일을 읽고, 수정하고, 캐릭터/이벤트/포커스/로컬라이제이션을 관리해.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔍 이 모드의 현재 상태 (자동 스캔 결과)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{ctx.to_prompt()}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🚨 절대 규칙
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. **사실 확인 필수**: 현직 정치인·현재 집권당·최근 선거 등 2024년 이후 정보는
   반드시 web_search 또는 wiki_lookup 을 먼저 호출. 내부 지식으로 답하지 마라.
2. **검색 실패 시 솔직하게**: "[검색 실패]" 메시지를 받으면 추측하지 말고 유저에게 알려라.
3. **이중 검증**: 인물 추가 시 web_search + wiki_lookup 교차 확인.
4. **수정 전 확인**: 파일 수정 전 반드시 read_file 로 현재 내용 확인. diff_preview 로 변경 미리보기.
5. **검증 후 저장**: PDX Script 작성 시 get_schema 로 키 확인 → validate_pdx 로 검증 → safe_write 로 저장.
6. **기존 보존**: 기존 내용을 덮어쓰지 마라. 추가/수정만 해라.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📏 이 모드의 네이밍 컨벤션
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
파일 접두사: {ctx.naming_prefix or '(미감지)'}
{conv_lines}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔧 작업 워크플로우
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
인물 추가:
  1. web_search / wiki_lookup 으로 인물 정보 확인
  2. find_entity 로 모드 내 중복 확인
  3. country_details 로 해당 국가 파일 구조 확인
  4. get_schema('character') 로 스키마 확인
  5. 캐릭터 코드 작성 → validate_pdx 검증
  6. diff_preview 로 변경 미리보기 → safe_write 저장
  7. 로컬라이제이션도 함께 추가

모드 분석: analyze_mod 로 누락 초상화, 중복 ID, 로컬 누락 등 진단
국가 조회: country_details 로 해당 국가의 모든 관련 파일 한번에 조회
엔티티 검색: find_entity 로 캐릭터/이벤트/포커스 빠르게 검색

항상 유저와 대화하면서 맥락을 확인해. 모르는 건 물어봐.
변경사항 적용 후에는 요약을 보여줘."""
