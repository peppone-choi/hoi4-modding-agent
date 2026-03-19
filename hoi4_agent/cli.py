"""CLI entry point for HOI4 Modding Agent."""
import os
import sys
from pathlib import Path

import click
from dotenv import load_dotenv


@click.command()
@click.argument("mod_path", type=click.Path(exists=True), default=".")
@click.option("--port", default=8501, help="Streamlit server port")
def main(mod_path: str, port: int):
    """HOI4 Modding Agent - AI-powered mod assistant.

    MOD_PATH: Path to your HOI4 mod directory (default: current directory)
    """
    agent_root = Path(__file__).resolve().parent.parent
    load_dotenv(agent_root / ".env")

    mod_path_abs = Path(mod_path).resolve()
    
    if mod_path_abs.name == "hoi4-modding-agent":
        actual_mod = mod_path_abs.parent / "Breaking-Point"
        mcp_symlink = mod_path_abs / "Breaking-Point"
        
        if actual_mod.exists() and actual_mod.is_dir():
            if not mcp_symlink.exists():
                try:
                    mcp_symlink.symlink_to(actual_mod)
                    click.echo(f"✓ MCP 접근용 심볼릭 링크 생성: {mcp_symlink.name}")
                except OSError as e:
                    click.echo(f"⚠ 심볼릭 링크 생성 실패: {e}", err=True)
            
            os.environ["MOD_ROOT"] = str(actual_mod)
            click.echo(f"📂 모드: {actual_mod.name}")
        else:
            click.echo(f"⚠ Breaking-Point 폴더 없음: {actual_mod}", err=True)
            os.environ["MOD_ROOT"] = str(mod_path_abs)
    else:
        os.environ["MOD_ROOT"] = str(mod_path_abs)

    ai_provider = os.getenv("AI_PROVIDER", "anthropic").lower()
    if ai_provider == "ollama":
        model = os.getenv("OLLAMA_MODEL", "llama3.1:70b")
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        click.echo(f"🦙 AI: Ollama ({model}) · {base_url} · 무료")
    elif ai_provider == "gemini":
        model = os.getenv("GEMINI_MODEL", "gemini-3-flash-preview")
        click.echo(f"💎 AI: Gemini ({model})")
    elif ai_provider == "openai":
        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        click.echo(f"🧠 AI: GPT ({model})")
    else:
        model = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
        click.echo(f"🤖 AI: Claude ({model}) · 유료")

    sys.argv = [
        "streamlit",
        "run",
        os.path.join(os.path.dirname(__file__), "ui", "app.py"),
        "--server.port",
        str(port),
        "--browser.gatherUsageStats",
        "false",
    ]

    from streamlit.web.cli import main as st_main

    st_main()


if __name__ == "__main__":
    main()
