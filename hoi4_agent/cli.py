"""CLI entry point for HOI4 Modding Agent."""
import os
import sys

import click


@click.command()
@click.argument("mod_path", type=click.Path(exists=True), default=".")
@click.option("--port", default=8501, help="Streamlit server port")
def main(mod_path: str, port: int):
    """HOI4 Modding Agent - AI-powered mod assistant.

    MOD_PATH: Path to your HOI4 mod directory (default: current directory)
    """
    os.environ["MOD_ROOT"] = os.path.abspath(mod_path)

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
