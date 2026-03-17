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
    
    anthropic_key: str
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
    
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not anthropic_key:
        raise ValueError(
            "ANTHROPIC_API_KEY is required. "
            "Set it in .env or environment variables."
        )
    
    gemini_key = os.getenv("GEMINI_API_KEY")
    tavily_key = os.getenv("TAVILY_API_KEY")
    google_api_key = os.getenv("GOOGLE_API_KEY")
    google_cx = os.getenv("GOOGLE_CX")
    
    if mod_root:
        mod_root = Path(mod_root)
    else:
        mod_root_env = os.getenv("MOD_ROOT")
        mod_root = Path(mod_root_env) if mod_root_env else None
    
    if mod_root:
        db_path = mod_root / "tools" / ".chat_sessions.db"
    else:
        db_path = Path.cwd() / ".chat_sessions.db"
    
    return Config(
        anthropic_key=anthropic_key,
        gemini_key=gemini_key,
        tavily_key=tavily_key,
        google_api_key=google_api_key,
        google_cx=google_cx,
        mod_root=mod_root,
        db_path=db_path,
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
