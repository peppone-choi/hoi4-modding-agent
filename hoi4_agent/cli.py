"""CLI entry point for HOI4 Modding Agent."""
import os
import sys
from pathlib import Path

import click


@click.command()
@click.argument("mod_path", type=click.Path(exists=True), default=".")
@click.option("--port", default=8501, help="Streamlit server port")
def main(mod_path: str, port: int):
    """HOI4 Modding Agent - AI-powered mod assistant.

    MOD_PATH: Path to your HOI4 mod directory (default: current directory)
    """
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
