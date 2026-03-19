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
    {"name": "find_entity", "description": "Quick search for character/event/focus by name or ID.", "input_schema": {"type": "object", "properties": {"entity_name": {"type": "string"}, "entity_type": {"type": "string", "enum": ["all", "character", "event", "focus"]}}, "required": ["entity_name"]}},
    {"name": "country_details", "description": "Get all files/settings for a country (history/characters/focus/events).", "input_schema": {"type": "object", "properties": {"tag": {"type": "string"}}, "required": ["tag"]}},
    {"name": "get_schema", "description": "Get HOI4 file schema (valid keys/structure). 'list'=all types, 'scopes'=scopes, 'modifiers'=modifiers.", "input_schema": {"type": "object", "properties": {"file_type": {"type": "string"}}, "required": ["file_type"]}},
    {"name": "validate_pdx", "description": "Validate PDX Script against schema. Checks braces, required keys, popularities sum.", "input_schema": {"type": "object", "properties": {"content": {"type": "string"}, "file_type": {"type": "string"}}, "required": ["content", "file_type"]}},
    {"name": "diff_preview", "description": "Preview file changes before writing.", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "new_content": {"type": "string"}}, "required": ["path", "new_content"]}},
    {"name": "analyze_mod", "description": "Mod health check. Missing portraits, duplicate IDs, missing loc, orphan GFX.", "input_schema": {"type": "object", "properties": {"check_type": {"type": "string", "enum": ["all", "portraits", "loc", "duplicates", "orphans"]}}, "required": []}},
    {"name": "search_portraits", "description": "Search/download person photos from web.", "input_schema": {"type": "object", "properties": {"person_name": {"type": "string"}, "title": {"type": "string"}, "country_tag": {"type": "string"}, "max_results": {"type": "integer"}}, "required": ["person_name"]}},
    {"name": "generate_portrait", "description": "Apply color grading to a real photo (desaturate, warm tone, contrast). Output is a REAL PHOTO, not illustration. REQUIRED: search_portraits → show_image → user confirm → generate_portrait.", "input_schema": {"type": "object", "properties": {"input_image_path": {"type": "string"}, "output_path": {"type": "string"}, "style_prompt": {"type": "string"}}, "required": ["input_image_path", "output_path"]}},
    {"name": "show_image", "description": "Display image in chat.", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
]


def build_system_prompt_simple(ctx: ModContext) -> str:
    """Simplified prompt for small Ollama models (qwen3.5:4b, llama3.1:8b)."""
    conv_lines = (
        "\n".join(f"  {k}: {v}" for k, v in ctx.naming_conventions.items())
        if ctx.naming_conventions
        else "  (not detected — use read_file to check existing files)"
    )
    return f"""You are a HOI4 modding agent for mod "{ctx.mod_name or '(unknown)'}".
"{ctx.mod_name or ''}" is the MOD NAME, not a search query.
You manage mod files: characters, events, focus trees, localisation.
Respond in Korean (한국어). Tool queries can be English.

{ctx.cached_to_prompt()}
Naming: prefix={ctx.naming_prefix or '(unknown)'}
{conv_lines}

== INTENT GATE ==
Before acting, classify the user's TRUE intent:
- "explain/how" → research with tools → answer
- "add/create/update" → plan → execute with tools → verify
- "look into/check" → investigate with tools → report
- "error/broken" → diagnose → fix minimally
Ambiguous? Ask 1 question. Otherwise execute immediately.

== TOOL RULES ==
1. MUST call tools before answering. Never answer from memory.
2. People/politicians/parties → ALWAYS call wiki_lookup FIRST, then web_search to cross-check.
3. wiki_lookup is MANDATORY for any person, country, party, or organization. No exceptions.
4. Before editing → read_file FIRST to check existing file structure and find correct insertion point.
5. Writing → get_schema → validate_pdx → safe_write. Insert code at the CORRECT location in the file.
6. Keep existing content. Add/modify only, never overwrite. Never put code in wrong section.
7. After saving → read_file to verify.
8. Portrait: search_portraits → show_image(추천 사진 1장) → "이 사진으로 만들까요?" → 유저 확인 후 generate_portrait. 유저 확인 없이 generate 금지.

== AUTONOMOUS EXECUTION ==
- Execute to completion. NEVER say "shall I continue?" Just do it.
- Batch: process ALL items. Show [ 3/5 ] ✅. Never stop midway.
- Error → retry 3x → then report. Skip failed items, report at end.
- "Done" = all tools succeeded + read_file verified. No exceptions.

== ZERO TOLERANCE ==
- "I did X" only when tool returned success. No tool call = no "done".
- "I will do X" (plan) ≠ "I did X" (complete). Never mix.
- Search failed? Say so honestly. Never guess.
"""


def build_system_prompt(ctx: ModContext) -> str:
    conv_lines = (
        "\n".join(f"  {k}: {v}" for k, v in ctx.naming_conventions.items())
        if ctx.naming_conventions
        else "  (자동 감지 안됨 — read_file 로 기존 파일 참고)"
    )
    return f"""너는 HOI4 모드 "{ctx.mod_name or '(알 수 없음)'}" 전용 모딩 에이전트야.
모드 파일을 읽고, 수정하고, 캐릭터/이벤트/포커스/로컬라이제이션을 관리해.
모든 응답에서 반드시 도구를 호출해야 한다. 텍스트만으로 응답하는 것은 금지.

== IntentGate ==
유저 메시지 받으면, 먼저 진짜 의도를 분류해:
- "설명해/어떻게" → 도구로 조사 → 답변
- "추가/생성/수정" → 계획 → 도구로 실행 → 검증
- "확인해/조사해" → 도구로 조사 → 보고
- "에러/고장" → 진단 → 최소 수정
- 모호하면 핵심 질문 1개만. 그 외에는 즉시 실행.

== MCP 도구 우선 ==
- 인물/사건/국가 → mcp_tavily_tavily_search
- 위키 정보 → mcp_wikipedia_search + readArticle
- 인물 조사 시 tavily + wikipedia + wiki_lookup 교차검증 필수
- PDX Script 작성/수정 시 → 반드시 mcp_context7로 공식 문법 확인 후 코드 작성. 추측 금지.
  (resolve-library-id로 라이브러리 찾기 → get-library-docs로 문법 확인)
- 코드를 기존 파일에 넣을 때 → 반드시 read_file로 기존 구조 확인 → 올바른 위치에 삽입.

== 모드 상태 ==
{ctx.cached_to_prompt()}
파일 접두사: {ctx.naming_prefix or '(미감지)'}
{conv_lines}

== 절대 규칙 ==
1. 인물/국가/정당/조직 → 반드시 wiki_lookup 먼저 호출. 예외 없음. 그 후 web_search로 교차검증.
2. 2024년 이후 정보 → web_search/wiki_lookup 먼저. 내부 지식 금지.
3. 검색 실패 → 추측 금지. 유저에게 솔직히 보고.
4. 파일 수정 전 → read_file로 현재 내용 확인.
5. PDX Script → get_schema → validate_pdx → safe_write.
6. 기존 내용 보존. 추가/수정만, 덮어쓰기 금지.
7. 포트레잇 → search_portraits → show_image(추천 1장) → "이걸로 만들까요?" → 유저 확인 후 generate_portrait. 확인 없이 생성 금지.

== 자율 실행 (Ultrawork) ==
- 끝까지 실행. "계속할까요?" 금지. 배치는 전부 처리.
- 다단계 → [ 3/5 ] ✅ 진행 추적. ✅완료 🔧진행 ⏳대기 ❌실패.
- 에러 → 3회 재시도 → 보고. 실패 건너뛰고 마지막에 실패 목록.
- 복잡한 작업 → 계획 수립 후 즉시 실행. 승인 대기 금지.

== ZERO TOLERANCE ==
- "~했습니다"는 도구 성공 시에만. 미호출/에러면 "했다" 금지.
- "~하겠습니다"(계획) ≠ "~했습니다"(완료). 혼용 금지.
- 파일 저장 후 → read_file 확인. 엔티티 추가 → find_entity 확인.
- "완료"는 모든 도구 성공 + 검증 시에만.

== 워크플로우 ==
인물 추가: web_search+wiki_lookup → find_entity(중복) → country_details → get_schema → validate_pdx → safe_write → 로컬 추가.
리더 업데이트: web_search(최신) → country_details → read_file → safe_write.
변경 후 도구+결과 요약. 모르면 질문."""
