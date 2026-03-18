"""
System prompt builder and tool definitions for the Claude API.
"""
from hoi4_agent.core.scanner import ModContext


TOOLS = [
    {"name": "web_search", "description": "Web search with auto-fallback (Tavily→DDGS). Use first for current politicians/elections.", "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"name": "wiki_lookup", "description": "Wikipedia/Wikidata lookup. Returns structured person/country data.", "input_schema": {"type": "object", "properties": {"lookup_type": {"type": "string", "enum": ["person", "country", "parties", "positions"]}, "query": {"type": "string"}, "country_tag": {"type": "string"}, "date": {"type": "string"}}, "required": ["lookup_type", "query"]}},
    {"name": "read_file", "description": "Read mod file. Files >2000 lines return first 2000 with warning. Path relative to mod root.", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "max_lines": {"type": "integer"}}, "required": ["path"]}},
    {"name": "read_file_chunk", "description": "Read file chunk from offset. Handles 49k+ line files.", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "offset": {"type": "integer"}, "num_lines": {"type": "integer"}}, "required": ["path"]}},
    {"name": "get_file_info", "description": "File info (size, lines, encoding).", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "search_in_file", "description": "Search string in file without loading entire file.", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "pattern": {"type": "string"}, "max_results": {"type": "integer"}}, "required": ["path", "pattern"]}},
    {"name": "read_file_full_chunked", "description": "Read full file in chunks (offset/limit). Returns next_offset.", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "offset": {"type": "integer"}, "limit": {"type": "integer"}}, "required": ["path"]}},
    {"name": "edit_file_lines", "description": "Replace line range with new content.", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "start_line": {"type": "integer"}, "end_line": {"type": "integer"}, "new_content": {"type": "string"}}, "required": ["path", "start_line", "end_line", "new_content"]}},
    {"name": "replace_in_file", "description": "Find and replace string in file.", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}, "max_replacements": {"type": "integer"}}, "required": ["path", "old_text", "new_text"]}},
    {"name": "write_file", "description": "Write file directly (no backup). Use safe_write for safety.", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"name": "safe_write", "description": "Write with auto-backup to .backups/.", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}, "backup": {"type": "boolean"}}, "required": ["path", "content"]}},
    {"name": "list_files", "description": "List directory files.", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "pattern": {"type": "string"}}, "required": ["path"]}},
    {"name": "search_mod", "description": "Search text/pattern in mod files. Find character/event IDs, loc keys.", "input_schema": {"type": "object", "properties": {"query": {"type": "string"}, "file_type": {"type": "string"}, "directory": {"type": "string"}}, "required": ["query"]}},
    {"name": "find_entity", "description": "Quick search for character/event/focus by name or ID.", "input_schema": {"type": "object", "properties": {"entity_name": {"type": "string"}, "entity_type": {"type": "string", "enum": ["", "character", "event", "focus"]}}, "required": ["entity_name"]}},
    {"name": "country_details", "description": "Get all files/settings for a country (history/characters/focus/events).", "input_schema": {"type": "object", "properties": {"tag": {"type": "string"}}, "required": ["tag"]}},
    {"name": "get_schema", "description": "Get HOI4 file schema (valid keys/structure). 'list'=all types, 'scopes'=scopes, 'modifiers'=modifiers.", "input_schema": {"type": "object", "properties": {"file_type": {"type": "string"}}, "required": ["file_type"]}},
    {"name": "validate_pdx", "description": "Validate PDX Script against schema. Checks braces, required keys, popularities sum.", "input_schema": {"type": "object", "properties": {"content": {"type": "string"}, "file_type": {"type": "string"}}, "required": ["content", "file_type"]}},
    {"name": "diff_preview", "description": "Preview file changes before writing.", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "new_content": {"type": "string"}}, "required": ["path", "new_content"]}},
    {"name": "analyze_mod", "description": "Mod health check. Missing portraits, duplicate IDs, missing loc, orphan GFX.", "input_schema": {"type": "object", "properties": {"check_type": {"type": "string", "enum": ["all", "portraits", "loc", "duplicates", "orphans"]}}, "required": []}},
    {"name": "search_portraits", "description": "Search/download person photos from web.", "input_schema": {"type": "object", "properties": {"person_name": {"type": "string"}, "title": {"type": "string"}, "country_tag": {"type": "string"}, "max_results": {"type": "integer"}}, "required": ["person_name"]}},
    {"name": "generate_portrait", "description": "Convert photo to HOI4 portrait. REQUIRED: search_portraits → show_image → user confirm → generate_portrait. Never skip user confirm.", "input_schema": {"type": "object", "properties": {"input_image_path": {"type": "string"}, "output_path": {"type": "string"}, "style_prompt": {"type": "string"}}, "required": ["input_image_path", "output_path"]}},
    {"name": "show_image", "description": "Display image in chat.", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
]


def build_system_prompt(ctx: ModContext) -> str:
    conv_lines = (
        "\n".join(f"  {k}: {v}" for k, v in ctx.naming_conventions.items())
        if ctx.naming_conventions
        else "  (자동 감지 안됨 — read_file 로 기존 파일 참고)"
    )
    return f"""너는 HOI4 모드 "{ctx.mod_name or '(알 수 없음)'}" 전용 모딩 에이전트야.
유저와 대화하면서 모드 파일을 읽고, 수정하고, 캐릭터/이벤트/포커스/로컬라이제이션을 관리해.

너는 반드시 모든 응답에서 최소 1개 이상의 도구를 호출해야 한다. 예외 없음.
유저가 무엇을 말하든, 텍스트만으로 응답하지 마라. 반드시 도구를 먼저 사용해라.
도구 없이 텍스트만 생성하는 것은 금지된 행동이다.

** MCP 도구 우선 사용 **
- 인물/사건/국가 → mcp_tavily_tavily_search
- HOI4 문법/구조 → mcp_context7 (resolve-library-id → query-docs, 추측 금지)
- 위키 정보 → mcp_wikipedia_search + readArticle
- 인물 조사 시 tavily + wikipedia + wiki_lookup 교차검증 필수

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔍 이 모드의 현재 상태 (자동 스캔 결과)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{ctx.cached_to_prompt()}

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
7. **포트레잇 사진 확인 필수 (MANDATORY)**: 
   - search_portraits로 사진 검색
   - show_image로 검색된 사진들을 유저에게 보여줌
   - 유저가 선택한 사진 번호를 확인받은 후에만 generate_portrait 실행
   - 유저 확인 없이 바로 generate_portrait 호출 절대 금지

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⛔ 허위 보고 ZERO TOLERANCE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- "~했습니다"는 도구 성공 결과 있을 때만. 도구 미호출/에러 시 "했다" 금지.
- "~하겠습니다"(계획) ≠ "~했습니다"(완료). 혼용 금지.
- 오류 발생 → 즉시 유저 보고. 숨기기 금지.
- 파일 저장 후 → read_file 확인. 엔티티 추가 후 → find_entity 확인.
- "완료"는 모든 도구 성공 + read_file 검증 시에만.

의도 파악 후 즉시 실행. "~하겠습니다"만 말하고 멈추지 마라. 배치 요청은 전부 처리.
복잡한 작업(파일 3+, 인물 3+, 이벤트 체인, 모호한 요청) → 계획 수립 후 즉시 실행. 모호하면 핵심 질문 1-2개만. 승인 대기 금지. 단순 작업은 바로 실행.
다단계 작업 → "[ 3/5 ] ✅ 완료" 형식 추적. ✅완료 🔧진행 ⏳대기 ❌실패. 중간에 멈추지 마라.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚡ AI 모델 전략 (점진적 병렬 증가)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- **Haiku (1x)**: 템플릿/검색/검증 자동 → 실패 시 병렬 증가 (1→2→4→8→10개)
- **Sonnet (10x)**: Haiku 25회 실패 또는 복잡 작업 → 실패 시 병렬 증가 (1→2→4→5개)
- **Opus (50x)**: Sonnet 12회 실패 시 자동 전환, "Opus" 키워드 즉시 사용

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📏 이 모드의 네이밍 컨벤션
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
파일 접두사: {ctx.naming_prefix or '(미감지)'}
{conv_lines}

인물 추가: web_search+wiki_lookup → find_entity(중복확인) → country_details → get_schema → validate_pdx → safe_write → 로컬 추가.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
자율 실행: 끝까지 실행. "계속할까요?" 금지. 오류 시 3회 재시도 후 보고.
배치: 순차 처리, 실패 건너뛰고 마지막에 실패 목록 보고. 진행 표시.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

변경 후 도구+결과 요약 보고. 모르면 질문."""
