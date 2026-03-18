"""
위키 데이터 → HOI4 GFX sprite 등록.
초상화 이미지를 interface/*.gfx 파일에 spriteType으로 등록한다.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from loguru import logger

from tools.shared.constants import INTERFACE_DIR
from tools.shared.hoi4_generator import GFXGenerator as BaseGFXGen


class WikiGFXGenerator:
    """초상화 GFX 항목 자동 등록."""

    def __init__(self) -> None:
        self._base = BaseGFXGen()

    # ------------------------------------------------------------------
    # 단일 등록
    # ------------------------------------------------------------------

    def register_portrait(
        self,
        char_id: str,
        image_path: Path,
        mod_root: Path,
    ) -> str:
        """초상화 이미지를 GFX에 등록하고 sprite 이름을 반환한다.

        GFX 스프라이트 이름: ``GFX_{char_id}``
        텍스처 경로: ``gfx/leaders/{country_tag}/{char_id}.png``
        """
        # char_id에서 국가 태그 추출
        parts = char_id.split("_")
        country_tag = parts[0] if parts else "UNK"

        from hoi4_agent.core.scanner import detect_mod_prefix
        prefix = detect_mod_prefix(mod_root)
        
        sprite_name = f"GFX_{char_id}"
        texture_path = f"gfx/leaders/{country_tag}/{char_id}.png"

        gfx_file = mod_root / "interface" / f"{prefix}_portraits.gfx"
        if not gfx_file.exists():
            gfx_file = mod_root / "interface" / "_leader_portraits.gfx"
        if not gfx_file.exists():
            gfx_file = mod_root / "interface" / f"{prefix}_portraits.gfx"
            gfx_file.parent.mkdir(parents=True, exist_ok=True)
            gfx_file.write_text("spriteTypes = {\n}\n", encoding="utf-8")

        self._base.add_sprite_to_gfx(sprite_name, texture_path, gfx_file)
        logger.info(f"GFX 등록: {sprite_name} → {texture_path}")
        return sprite_name

    # ------------------------------------------------------------------
    # 일괄 등록
    # ------------------------------------------------------------------

    def generate_gfx_entries(
        self,
        characters: list[dict[str, Any]],
        mod_root: Path,
    ) -> int:
        """여러 캐릭터의 GFX 항목을 일괄 생성한다.

        Args:
            characters: ``[{"char_id": str, "image_path": Path}, ...]``
            mod_root: 모드 루트 경로.

        Returns:
            등록된 항목 수.
        """
        count = 0
        for char in characters:
            char_id = char.get("char_id", "")
            image_path = char.get("image_path")
            if not char_id:
                continue
            try:
                self.register_portrait(char_id, image_path, mod_root)
                count += 1
            except Exception as exc:
                logger.error(f"GFX 등록 실패: {char_id} — {exc}")
        return count
