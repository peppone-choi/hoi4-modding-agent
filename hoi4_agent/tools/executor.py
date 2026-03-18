"""
Tool execution engine for HOI4 Modding Agent.
Handles all tool invocations from the Claude API.
"""
import json
from pathlib import Path


class ToolExecutor:
    """Executes tools based on Claude API tool calls."""
    
    def __init__(
        self, 
        mod_root: Path, 
        gemini_key: str | None = None, 
        mcp_manager=None,
        portrait_bg_top: str = "#bfdc7f",
        portrait_bg_bottom: str = "#0a0f0a",
        portrait_bg_gradient: bool = True,
        portrait_scanlines_enabled: bool = True,
        mod_context=None,
    ):
        self.mod_root = mod_root
        self.gemini_key = gemini_key
        self.mcp_manager = mcp_manager
        self.portrait_bg_top = portrait_bg_top
        self.portrait_bg_bottom = portrait_bg_bottom
        self.portrait_bg_gradient = portrait_bg_gradient
        self.portrait_scanlines_enabled = portrait_scanlines_enabled
        self.mod_context = mod_context
    
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
            if name == "read_file_chunk":
                return self._read_file_chunk(inp)
            if name == "get_file_info":
                return self._get_file_info(inp)
            if name == "search_in_file":
                return self._search_in_file(inp)
            if name == "read_file_full_chunked":
                return self._read_file_full_chunked(inp)
            if name == "edit_file_lines":
                return self._edit_file_lines(inp)
            if name == "replace_in_file":
                return self._replace_in_file(inp)
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
        from hoi4_agent.core.file_utils import read_file_smart, read_file_cached
        fp = self.mod_root / inp["path"]
        if not fp.exists():
            return f"[파일 없음] {inp['path']}"
        
        max_lines = inp.get("max_lines", 2000)
        
        if max_lines == 2000:
            try:
                content = read_file_cached(fp, max_age_seconds=300)
                lines = content.splitlines()
                if len(lines) <= 2000:
                    numbered = "\n".join(f"{idx}: {line}" for idx, line in enumerate(lines, 1))
                    return numbered
            except Exception:
                pass
        
        content, meta = read_file_smart(fp, max_lines=max_lines)
        
        if meta.get("warning"):
            footer = f"\n\n[경고] {meta['warning']}\n"
            if meta.get("next_offset"):
                footer += f"다음 청크: read_file_chunk(path='{inp['path']}', offset={meta['next_offset']})\n"
            footer += f"파일 정보: get_file_info(path='{inp['path']}')"
            return content + footer
        
        return content
    
    def _read_file_chunk(self, inp: dict) -> str:
        from hoi4_agent.core.file_utils import read_file_chunk
        fp = self.mod_root / inp["path"]
        if not fp.exists():
            return f"[파일 없음] {inp['path']}"
        
        offset = inp.get("offset", 1)
        num_lines = inp.get("num_lines", 2000)
        
        content, has_more = read_file_chunk(fp, start_line=offset, num_lines=num_lines)
        
        footer = f"\n\n[청크 정보] 줄 {offset}~{offset + num_lines - 1}"
        if has_more:
            next_offset = offset + num_lines
            footer += f"\n더 읽기: read_file_chunk(path='{inp['path']}', offset={next_offset})"
        else:
            footer += "\n[파일 끝]"
        
        return content + footer
    
    def _get_file_info(self, inp: dict) -> str:
        from hoi4_agent.core.file_utils import get_file_info
        fp = self.mod_root / inp["path"]
        info = get_file_info(fp)
        
        if "error" in info:
            return f"[오류] {info['error']}"
        
        return json.dumps(info, ensure_ascii=False, indent=2)
    
    def _search_in_file(self, inp: dict) -> str:
        from hoi4_agent.core.file_utils import search_in_large_file
        fp = self.mod_root / inp["path"]
        if not fp.exists():
            return f"[파일 없음] {inp['path']}"
        
        results = search_in_large_file(
            fp,
            pattern=inp["pattern"],
            max_results=inp.get("max_results", 100),
        )
        
        if not results:
            return f"[검색 결과 없음] '{inp['pattern']}'"
        
        lines = [f"[검색 결과 {len(results)}건]"]
        for r in results:
            lines.append(f"줄 {r['line']}: {r['text']}")
        
        return "\n".join(lines)
    
    def _read_file_full_chunked(self, inp: dict) -> str:
        from hoi4_agent.core.file_utils import read_file_full_chunked
        fp = self.mod_root / inp["path"]
        
        content, meta = read_file_full_chunked(
            fp,
            offset=inp.get("offset", 1),
            limit=inp.get("limit", 2000),
        )
        
        if "error" in meta:
            return f"[오류] {meta['error']}"
        
        footer = f"\n\n[청크 정보]\n"
        footer += f"- 청크: {meta['chunk_number']}/{meta['total_chunks']}\n"
        footer += f"- 전체: {meta['total_lines']}줄\n"
        footer += f"- 현재: {meta['current_offset']}-{meta['current_offset'] + meta['lines_read'] - 1}줄 ({meta['lines_read']}줄)\n"
        footer += f"- 진행률: {int(meta['progress'] * 100)}%\n"
        
        if not meta['is_last_chunk']:
            footer += f"- 다음: read_file_full_chunked(path='{inp['path']}', offset={meta['next_offset']}, limit={inp.get('limit', 2000)})\n"
        else:
            footer += f"- 상태: 마지막 청크\n"
        
        return content + footer
    
    def _edit_file_lines(self, inp: dict) -> str:
        from hoi4_agent.core.file_utils import edit_file_lines, invalidate_file_cache
        fp = self.mod_root / inp["path"]
        
        result = edit_file_lines(
            fp,
            start_line=inp["start_line"],
            end_line=inp["end_line"],
            new_content=inp["new_content"],
        )
        
        if result["success"]:
            invalidate_file_cache(fp)
            if self.mod_context:
                self.mod_context.cache_clear()
        
        if not result["success"]:
            return result["message"]
        
        msg = result["message"]
        msg += f"\n- 편집 전: {result['total_lines_before']}줄"
        msg += f"\n- 편집 후: {result['total_lines_after']}줄"
        
        return msg
    
    def _replace_in_file(self, inp: dict) -> str:
        from hoi4_agent.core.file_utils import replace_in_file, invalidate_file_cache
        fp = self.mod_root / inp["path"]
        
        result = replace_in_file(
            fp,
            old_text=inp["old_text"],
            new_text=inp["new_text"],
            max_replacements=inp.get("max_replacements"),
        )
        
        if result["success"]:
            invalidate_file_cache(fp)
            if self.mod_context:
                self.mod_context.cache_clear()
        
        if not result["success"]:
            return result["message"]
        
        msg = result["message"]
        
        if result["preview"]:
            msg += f"\n\n[교체 위치 미리보기 (최대 10개)]"
            for p in result["preview"]:
                msg += f"\n줄 {p['line']}: {p['text']}"
        
        return msg
    
    def _write_file(self, inp: dict) -> str:
        from hoi4_agent.core.file_utils import invalidate_file_cache
        fp = self.mod_root / inp["path"]
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(inp["content"], encoding="utf-8")
        invalidate_file_cache(fp)
        if self.mod_context:
            self.mod_context.cache_clear()
        return f"[저장 완료] {inp['path']} ({len(inp['content'])}자)"
    
    def _safe_write(self, inp: dict) -> str:
        from hoi4_agent.core.mod_tools import safe_write
        from hoi4_agent.core.file_utils import invalidate_file_cache
        result = safe_write(self.mod_root, inp["path"], inp["content"], inp.get("backup", False))
        fp = self.mod_root / inp["path"]
        invalidate_file_cache(fp)
        if self.mod_context:
            self.mod_context.cache_clear()
        return result
    
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
                bg_color_top=self.portrait_bg_top,
                bg_color_bottom=self.portrait_bg_bottom,
                bg_gradient=self.portrait_bg_gradient,
                scanlines_enabled=self.portrait_scanlines_enabled,
            )

            success = pipeline.process_single(input_path, output_path)
            if success:
                return f"[포트레잇 완료] {inp['output_path']}"
            return "[포트레잇 오류] 파이프라인 처리 실패"
        except Exception as e:
            return f"[포트레잇 오류] {e}"
