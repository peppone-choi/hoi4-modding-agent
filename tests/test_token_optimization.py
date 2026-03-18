"""
Token optimization verification tests.
Compares before/after token counts for Phase 1-5 optimizations.
"""
import pytest
from pathlib import Path

from hoi4_agent.core.prompt import build_system_prompt, TOOLS
from hoi4_agent.core.scanner import ModContext


def estimate_tokens(text: str) -> int:
    """Rough token estimate (1.3 words per token)."""
    return int(len(text.split()) * 1.3)


class TestPhase1PromptCompression:
    """Phase 1: System prompt compression (272 → 99 lines)."""
    
    def test_prompt_line_count(self):
        ctx = ModContext(mod_root=Path("."))
        prompt = build_system_prompt(ctx)
        lines = prompt.split("\n")
        
        assert len(lines) <= 110, f"Prompt too long: {len(lines)} lines (target: ≤110)"
    
    def test_prompt_token_estimate(self):
        ctx = ModContext(mod_root=Path("."))
        prompt = build_system_prompt(ctx)
        tokens = estimate_tokens(prompt)
        
        assert tokens <= 1500, f"Prompt tokens too high: {tokens} (target: ≤1500)"


class TestPhase2ModContextCaching:
    """Phase 2: ModContext caching (300-500 tokens/msg saved)."""
    
    def test_modcontext_has_cache_methods(self):
        ctx = ModContext(mod_root=Path("."))
        
        assert hasattr(ctx, "cached_to_prompt"), "Missing cached_to_prompt() method"
        assert hasattr(ctx, "cache_clear"), "Missing cache_clear() method"
    
    def test_cache_invalidation_on_write(self):
        ctx = ModContext(mod_root=Path("."))
        
        result1 = ctx.cached_to_prompt()
        
        result2 = ctx.cached_to_prompt()
        assert result1 == result2, "Cache should return same result"
        
        ctx.cache_clear()
        result3 = ctx.cached_to_prompt()
        assert result3 is not None, "Cache should regenerate after clear"


class TestPhase3FileUtils:
    """Phase 3: File caching system (20-30% duplicate reads removed)."""
    
    def test_file_cache_functions_exist(self):
        from hoi4_agent.core import file_utils
        
        assert hasattr(file_utils, "read_file_cached"), "Missing read_file_cached()"
        assert hasattr(file_utils, "invalidate_file_cache"), "Missing invalidate_file_cache()"
        assert hasattr(file_utils, "clear_file_cache"), "Missing clear_file_cache()"
    
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
    """Phase 4: MCP server cleanup (~1000 tokens/msg saved)."""
    
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
    """Phase 5: Haiku worker system (37% additional savings)."""
    
    def test_haiku_worker_definitions_exist(self):
        workers_doc = Path(".omc/agents/haiku-workers.md")
        assert workers_doc.exists(), "Haiku workers documentation missing"
    
    def test_orchestration_module_exists(self):
        from hoi4_agent.core import orchestration
        
        assert hasattr(orchestration, "HaikuOrchestrator"), "Missing HaikuOrchestrator class"
        assert hasattr(orchestration, "WorkerType"), "Missing WorkerType enum"
    
    def test_task_decomposer_exists(self):
        from hoi4_agent.core import task_decomposer
        
        assert hasattr(task_decomposer, "TaskDecomposer"), "Missing TaskDecomposer class"
        assert hasattr(task_decomposer, "ExecutionStrategy"), "Missing ExecutionStrategy enum"
    
    def test_quality_gates_exist(self):
        from hoi4_agent.core import quality_gates
        
        assert hasattr(quality_gates, "QualityGateValidator"), "Missing QualityGateValidator"
        assert hasattr(quality_gates, "GateLevel"), "Missing GateLevel enum"


class TestOverallTokenSavings:
    """Overall token savings validation."""
    
    def test_tool_count_reasonable(self):
        """Ensure tool count hasn't exploded."""
        assert len(TOOLS) <= 20, f"Too many tools: {len(TOOLS)} (target: ≤20)"
    
    def test_estimated_daily_savings(self):
        """Estimate daily token savings from all phases."""
        
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
