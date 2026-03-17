"""
Tool execution engine for HOI4 Modding Agent.
Handles all tool invocations from the Claude API.
"""
import json
from pathlib import Path


class ToolExecutor:
    """Executes tools based on Claude API tool calls."""
    
    def __init__(self, mod_root: Path, gemini_key: str | None = None, mcp_manager=None):
        self.mod_root = mod_root
        self.gemini_key = gemini_key
        self.mcp_manager = mcp_manager
    
    def execute(self, name: str, inp: dict) -> str:
        """
        Execute a tool by name with input parameters.
        
        Args:
            name: Tool name
            inp: Tool input parameters
            
        Returns:
            Tool execution result as string
        """
        try:
            if name.startswith("mcp_") and self.mcp_manager:
                return self.mcp_manager.execute(name, inp)
            if name == "web_search":
                return self._web_search(inp)
            if name == "wiki_lookup":
                return self._wiki_lookup(inp)
            if name == "read_file":
                return self._read_file(inp)
            if name == "write_file":
                return self._write_file(inp)
            if name == "safe_write":
                return self._safe_write(inp)
            if name == "list_files":
                return self._list_files(inp)
            if name == "search_mod":
                return self._search_mod(inp)
            if name == "find_entity":
                return self._find_entity(inp)
            if name == "country_details":
                return self._country_details(inp)
            if name == "get_schema":
                return self._get_schema(inp)
            if name == "validate_pdx":
                return self._validate_pdx(inp)
            if name == "diff_preview":
                return self._diff_preview(inp)
            if name == "analyze_mod":
                return self._analyze_mod(inp)
            if name == "search_portraits":
                return self._search_portraits(inp)
            if name == "generate_portrait":
                return self._generate_portrait(inp)
            if name == "show_image":
                return f"IMAGE:{inp['path']}"
            
            return f"[오류] 알 수 없는 도구: {name}"
        except Exception as exc:
            return f"[도구 오류] {name}: {exc}"
    
    def _web_search(self, inp: dict) -> str:
        from hoi4_agent.tools.search import web_search
        return web_search(inp["query"])
    
    def _wiki_lookup(self, inp: dict) -> str:
        from hoi4_agent.core.wiki_tools import (
            wiki_lookup_person, wiki_lookup_country,
            wiki_lookup_political_parties, wiki_lookup_person_positions,
        )
        lt, q = inp["lookup_type"], inp["query"]
        if lt == "person":
            return wiki_lookup_person(q, inp.get("country_tag", ""))
        if lt == "country":
            return wiki_lookup_country(q, inp.get("country_tag", ""))
        if lt == "parties":
            return wiki_lookup_political_parties(q)
        if lt == "positions":
            return wiki_lookup_person_positions(q, inp.get("date", "2026-01-01"))
        return f"[오류] 알 수 없는 lookup_type: {lt}"
    
    def _read_file(self, inp: dict) -> str:
        fp = self.mod_root / inp["path"]
        if not fp.exists():
            return f"[파일 없음] {inp['path']}"
        t = fp.read_text(encoding="utf-8-sig", errors="replace")
        return t[:20000] + (f"\n\n... ({len(t)-20000}자 생략)" if len(t) > 20000 else "")
    
    def _write_file(self, inp: dict) -> str:
        fp = self.mod_root / inp["path"]
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(inp["content"], encoding="utf-8")
        return f"[저장 완료] {inp['path']} ({len(inp['content'])}자)"
    
    def _safe_write(self, inp: dict) -> str:
        from hoi4_agent.core.mod_tools import safe_write
        return safe_write(self.mod_root, inp["path"], inp["content"], inp.get("backup", True))
    
    def _list_files(self, inp: dict) -> str:
        dp = self.mod_root / inp["path"]
        if not dp.exists():
            return f"[디렉토리 없음] {inp['path']}"
        pat = inp.get("pattern", "*")
        files = sorted(str(p.relative_to(self.mod_root)) for p in dp.glob(pat))[:100]
        return f"[{len(files)}개]\n" + "\n".join(files) if files else f"[결과 없음] {inp['path']}/{pat}"
    
    def _search_mod(self, inp: dict) -> str:
        from hoi4_agent.core.mod_tools import search_mod
        return search_mod(self.mod_root, inp["query"], inp.get("file_type", ""), inp.get("directory", ""))
    
    def _find_entity(self, inp: dict) -> str:
        from hoi4_agent.core.mod_tools import find_entity
        return find_entity(self.mod_root, inp["entity_name"], inp.get("entity_type", ""))
    
    def _country_details(self, inp: dict) -> str:
        from hoi4_agent.core.mod_tools import list_country_details
        return list_country_details(self.mod_root, inp["tag"])
    
    def _get_schema(self, inp: dict) -> str:
        from hoi4_agent.core.mod_tools import get_schema
        return get_schema(inp["file_type"])
    
    def _validate_pdx(self, inp: dict) -> str:
        from hoi4_agent.core.mod_tools import validate_pdx
        return validate_pdx(inp["content"], inp["file_type"])
    
    def _diff_preview(self, inp: dict) -> str:
        from hoi4_agent.core.mod_tools import diff_preview
        return diff_preview(self.mod_root, inp["path"], inp["new_content"])
    
    def _analyze_mod(self, inp: dict) -> str:
        from hoi4_agent.core.mod_tools import analyze_mod
        return analyze_mod(self.mod_root, inp.get("check_type", "all"))
    
    def _search_portraits(self, inp: dict) -> str:
        try:
            from hoi4_agent.tools.portrait.search.multi_search import MultiSourceSearch
            s = MultiSourceSearch(cache_dir=Path("/tmp/agent_portrait_cache"))
            dl = s.search_person(
                person_name=inp["person_name"], title=inp.get("title"),
                country_tag=inp.get("country_tag"), max_results=inp.get("max_results", 8),
            )
            return json.dumps([str(p) for p in dl], ensure_ascii=False)
        except ImportError:
            return "[오류] portrait_generator 모듈 없음"
        except Exception as e:
            return f"[포트레잇 검색 오류] {e}"
    
    def _generate_portrait(self, inp: dict) -> str:
        try:
            from hoi4_agent.tools.portrait.pipeline.portrait_pipeline import PortraitPipeline

            input_path = Path(inp["input_image_path"])
            output_path = self.mod_root / inp["output_path"]

            mode = "gemini" if self.gemini_key else "local"
            pipeline = PortraitPipeline(
                mode=mode,
                gemini_api_key=self.gemini_key,
                style_prompt=inp.get("style_prompt"),
            )

            success = pipeline.process_single(input_path, output_path)
            if success:
                return f"[포트레잇 완료] {inp['output_path']}"
            return "[포트레잇 오류] 파이프라인 처리 실패"
        except Exception as e:
            return f"[포트레잇 오류] {e}"
