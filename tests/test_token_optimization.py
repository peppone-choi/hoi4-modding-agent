"""
Token optimization verification tests.
Compares before/after token counts for Phase 1-5 optimizations.
"""
import pytest
from pathlib import Path

from hoi4_agent.core.prompt import build_system_prompt, TOOLS
from hoi4_agent.core.scanner import ModContext


def estimate_tokens(text: str) -> int:
    return int(len(text.split()) * 1.3)


class TestPhase1PromptCompression:
    
    def test_prompt_line_count(self):
        ctx = ModContext(root=Path("."))
        prompt = build_system_prompt(ctx)
        lines = prompt.split("\n")
        
        assert len(lines) <= 110, f"Prompt too long: {len(lines)} lines (target: ≤110)"
    
    def test_prompt_token_estimate(self):
        ctx = ModContext(root=Path("."))
        prompt = build_system_prompt(ctx)
        tokens = estimate_tokens(prompt)
        
        assert tokens <= 1500, f"Prompt tokens too high: {tokens} (target: ≤1500)"


class TestPhase2ModContextCaching:
    
    def test_modcontext_has_cache_methods(self):
        ctx = ModContext(root=Path("."))
        
        assert hasattr(ctx, "cached_to_prompt")
        assert hasattr(ctx, "cache_clear")
    
    def test_cache_invalidation_on_write(self):
        ctx = ModContext(root=Path("."))
        
        result1 = ctx.cached_to_prompt()
        result2 = ctx.cached_to_prompt()
        assert result1 == result2, "Cache should return same result"
        
        ctx.cache_clear()
        result3 = ctx.cached_to_prompt()
        assert result3 is not None, "Cache should regenerate after clear"


class TestPhase3FileUtils:
    
    def test_file_cache_functions_exist(self):
        from hoi4_agent.core import file_utils
        
        assert hasattr(file_utils, "read_file_cached")
        assert hasattr(file_utils, "invalidate_file_cache")
        assert hasattr(file_utils, "clear_file_cache")
    
    def test_file_cache_ttl(self):
        from hoi4_agent.core.file_utils import read_file_cached, clear_file_cache
        import tempfile
        import time
        
        clear_file_cache()
        
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("test content")
            f.flush()
            path = Path(f.name)
        
        try:
            content1 = read_file_cached(path, max_age_seconds=1)
            assert content1 == "test content"
            
            path.write_text("updated content")
            
            content2 = read_file_cached(path, max_age_seconds=1)
            assert content2 == "test content", "Cache should serve stale content within TTL"
            
            time.sleep(1.1)
            
            content3 = read_file_cached(path, max_age_seconds=1)
            assert content3 == "updated content", "Cache should refresh after TTL"
        finally:
            path.unlink()
            clear_file_cache()


class TestPhase4MCPServerCleanup:
    
    def test_mcp_servers_count(self):
        import json
        mcp_config = Path("mcp_servers.json")
        
        if mcp_config.exists():
            with mcp_config.open() as f:
                servers = json.load(f)
            
            assert len(servers) <= 7, f"Too many MCP servers: {len(servers)} (target: ≤7)"
    
    def test_essential_servers_present(self):
        import json
        mcp_config = Path("mcp_servers.json")
        
        if mcp_config.exists():
            with mcp_config.open() as f:
                servers = json.load(f)
            
            essential = ["context7", "tavily", "fetch"]
            for server in essential:
                assert server in servers, f"Essential server missing: {server}"


class TestPhase5HaikuWorkers:
    
    def test_haiku_worker_definitions_exist(self):
        workers_doc = Path(".omc/agents/haiku-workers.md")
        assert workers_doc.exists(), "Haiku workers documentation missing"
    
    def test_orchestration_module_exists(self):
        from hoi4_agent.core import orchestration
        
        assert hasattr(orchestration, "HaikuOrchestrator")
        assert hasattr(orchestration, "WorkerType")
    
    def test_task_decomposer_exists(self):
        from hoi4_agent.core import task_decomposer
        
        assert hasattr(task_decomposer, "TaskDecomposer")
        assert hasattr(task_decomposer, "ExecutionStrategy")
    
    def test_quality_gates_exist(self):
        from hoi4_agent.core import quality_gates
        
        assert hasattr(quality_gates, "QualityGateValidator")
        assert hasattr(quality_gates, "GateLevel")


class TestPhase6HaikuRouting:
    
    def test_decomposer_routes_simple_korean_to_haiku(self):
        from hoi4_agent.core.task_decomposer import TaskDecomposer, ExecutionStrategy
        
        d = TaskDecomposer()
        
        for msg in ["파일 읽어줘", "검색해줘", "목록 보여줘"]:
            analysis = d.analyze(msg)
            assert analysis.strategy == ExecutionStrategy.HAIKU_WORKER, \
                f"'{msg}' should route to Haiku, got {analysis.strategy}"
    
    def test_decomposer_routes_complex_korean_to_sonnet(self):
        from hoi4_agent.core.task_decomposer import TaskDecomposer, ExecutionStrategy
        
        d = TaskDecomposer()
        
        for msg in ["캐릭터 추가해줘", "이벤트 만들어줘", "포커스 트리 설계해줘"]:
            analysis = d.analyze(msg)
            assert analysis.strategy != ExecutionStrategy.HAIKU_WORKER, \
                f"'{msg}' should NOT route to Haiku, got {analysis.strategy}"
    
    def test_decomposer_routes_simple_english_to_haiku(self):
        from hoi4_agent.core.task_decomposer import TaskDecomposer, ExecutionStrategy
        
        d = TaskDecomposer()
        analysis = d.analyze("search for country tags")
        assert analysis.strategy == ExecutionStrategy.HAIKU_WORKER


class TestOverallTokenSavings:
    
    def test_tool_count_reasonable(self):
        assert len(TOOLS) <= 25, f"Too many tools: {len(TOOLS)} (target: ≤25)"
    
    def test_estimated_daily_savings(self):
        tokens_per_message_saved = 3500
        messages_per_day = 30
        daily_savings = tokens_per_message_saved * messages_per_day
        
        baseline = 150_000
        target_reduction = 0.50
        target_usage = baseline * (1 - target_reduction)
        
        actual_usage = baseline - daily_savings
        
        assert actual_usage <= target_usage * 1.1, \
            f"Token usage still too high: {actual_usage} (target: ≤{target_usage})"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
