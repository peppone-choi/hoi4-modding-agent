"""
rembg 래퍼.
Python 3.12 venv에 설치된 rembg를 subprocess로 호출한다.
메인 venv(3.14)에서도 배경 제거를 사용할 수 있도록 한다.
"""
from __future__ import annotations

import subprocess
from io import BytesIO
from pathlib import Path

from PIL import Image
from loguru import logger

REMBG_PYTHON = Path("/Users/apple/.rembg-venv/bin/python")


def remove_background_bytes(input_bytes: bytes) -> bytes:
    """이미지 바이트에서 배경을 제거한다.

    Returns:
        배경이 제거된 PNG 바이트 (RGBA).
    """
    if not REMBG_PYTHON.exists():
        raise FileNotFoundError(f"rembg Python not found: {REMBG_PYTHON}")

    result = subprocess.run(
        [
            str(REMBG_PYTHON), "-c",
            "import sys; from rembg import remove, new_session; "
            "s = new_session('birefnet-portrait'); "
            "data = sys.stdin.buffer.read(); "
            "sys.stdout.buffer.write(remove(data, session=s))",
        ],
        input=input_bytes,
        capture_output=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"rembg failed: {result.stderr.decode()}")
    return result.stdout


def remove_background(image: Image.Image) -> Image.Image:
    """PIL Image에서 배경을 제거한다.

    Returns:
        RGBA 이미지 (배경 투명).
    """
    # 방법 1: 직접 import (같은 venv에 rembg 있을 때)
    try:
        from rembg import remove as _remove, new_session
        session = new_session("birefnet-portrait")
        buf = BytesIO()
        image.convert("RGB").save(buf, format="PNG")
        result_bytes = _remove(buf.getvalue(), session=session)
        return Image.open(BytesIO(result_bytes)).convert("RGBA")
    except ImportError:
        pass
    except Exception as exc:
        logger.warning(f"rembg 직접 호출 실패: {exc}")

    # 방법 2: subprocess (다른 venv의 rembg 호출)
    try:
        buf = BytesIO()
        image.convert("RGB").save(buf, format="PNG")
        result_bytes = remove_background_bytes(buf.getvalue())
        return Image.open(BytesIO(result_bytes)).convert("RGBA")
    except Exception as exc:
        logger.warning(f"rembg subprocess 호출도 실패: {exc}")

    logger.debug("배경 제거 실패 — 원본 반환")
    return image.convert("RGBA")
