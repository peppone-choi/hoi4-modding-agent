"""
Configuration and settings management.
Handles environment variables, API keys, and application constants.
"""
import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv


@dataclass
class Config:
    """Application configuration."""
    
    ai_provider: str = "anthropic"
    
    anthropic_key: str | None = None
    
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:70b"
    
    gemini_key: str | None = None
    tavily_key: str | None = None
    google_api_key: str | None = None
    google_cx: str | None = None
    
    mod_root: Path | None = None
    db_path: Path | None = None
    
    default_model: str = "claude-opus-4-6"
    max_tokens: int = 16384
    max_tool_rounds: int = 50
    
    max_sessions: int = 50
    session_auto_save: bool = True
    
    # Portrait background configuration
    portrait_bg_top: str = "#bfdc7f"
    portrait_bg_bottom: str = "#0a0f0a"
    portrait_bg_gradient: bool = True
    portrait_scanlines_enabled: bool = True


def load_config(mod_root: Path | str | None = None) -> Config:
    """
    Load configuration from environment variables.
    
    Args:
        mod_root: Optional mod root path override
        
    Returns:
        Configured Config object
        
    Raises:
        ValueError: If required API keys are missing
    """
    load_dotenv()
    
    ai_provider = os.getenv("AI_PROVIDER", "anthropic").lower()
    
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    if ai_provider == "anthropic" and not anthropic_key:
        raise ValueError(
            "ANTHROPIC_API_KEY is required when AI_PROVIDER=anthropic. "
            "Set it in .env or environment variables."
        )
    
    ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    ollama_model = os.getenv("OLLAMA_MODEL", "llama3.1:70b")
    
    gemini_key = os.getenv("GEMINI_API_KEY")
    tavily_key = os.getenv("TAVILY_API_KEY")
    google_api_key = os.getenv("GOOGLE_API_KEY")
    google_cx = os.getenv("GOOGLE_CX")
    
    # Portrait background configuration
    portrait_bg_top = os.getenv("PORTRAIT_BG_TOP", "#bfdc7f")
    portrait_bg_bottom = os.getenv("PORTRAIT_BG_BOTTOM", "#0a0f0a")
    portrait_bg_gradient = os.getenv("PORTRAIT_BG_GRADIENT", "true").lower() in ("true", "1", "yes")
    portrait_scanlines_enabled = os.getenv("PORTRAIT_SCANLINES_ENABLED", "true").lower() in ("true", "1", "yes")
    
    if mod_root:
        mod_root = Path(mod_root)
    else:
        mod_root_env = os.getenv("MOD_ROOT")
        mod_root = Path(mod_root_env) if mod_root_env else None
    
    project_root = Path(__file__).parent.parent.parent
    if mod_root:
        mod_name = mod_root.name.lower().replace(" ", "_").replace("-", "_")
        db_path = project_root / "tools" / f".chat_sessions_{mod_name}.db"
    else:
        db_path = project_root / "tools" / ".chat_sessions.db"
    
    return Config(
        ai_provider=ai_provider,
        anthropic_key=anthropic_key if anthropic_key else None,
        ollama_base_url=ollama_base_url,
        ollama_model=ollama_model,
        gemini_key=gemini_key,
        tavily_key=tavily_key,
        google_api_key=google_api_key,
        google_cx=google_cx,
        mod_root=mod_root,
        db_path=db_path,
        portrait_bg_top=portrait_bg_top,
        portrait_bg_bottom=portrait_bg_bottom,
        portrait_bg_gradient=portrait_bg_gradient,
        portrait_scanlines_enabled=portrait_scanlines_enabled,
    )


def get_tool_status(config: Config) -> dict[str, bool]:
    """
    Get status of available tools based on API keys.
    
    Args:
        config: Application configuration
        
    Returns:
        Dictionary mapping tool names to availability
    """
    return {
        "anthropic": bool(config.anthropic_key),
        "gemini": bool(config.gemini_key),
        "tavily": bool(config.tavily_key),
        "google_search": bool(config.google_api_key and config.google_cx),
        "wikipedia": True,
    }
