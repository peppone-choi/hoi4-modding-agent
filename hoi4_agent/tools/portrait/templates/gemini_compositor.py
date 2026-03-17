"""
Gemini (Nano Banana) 기반 의상 합성.
배경 제거된 인물 사진에 군복/의상을 AI로 합성한다.
"""
from __future__ import annotations

import os
from io import BytesIO
from pathlib import Path

from PIL import Image
from loguru import logger
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()

# Gemini API 키: 환경변수 또는 .env 파일에서 로드
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# 국가 태그 → 군복 설명 매핑
UNIFORM_PROMPTS: dict[str, dict[str, str]] = {
    "AFG": {
        "military": "Afghan National Army general uniform with medals and military cap",
        "guerrilla": "Afghan mujahideen fighter clothing with pakol hat",
    },
    "USA": {
        "military": "United States Army dress uniform with medals and officer cap",
        "suit": "dark navy blue business suit with red tie",
        "guerrilla": "tactical military gear with kevlar helmet",
    },
    "RUS": {
        "military": "Russian military general dress uniform with medals and peaked cap",
    },
    "CHI": {
        "military": "Chinese PLA military general uniform with medals",
    },
    "IRN": {
        "military": "Iranian military general uniform with medals",
        "guerrilla": "Iranian Revolutionary Guard Corps uniform",
    },
    "generic": {
        "military": "military general dress uniform with medals and officer cap",
        "suit": "formal dark business suit with tie",
        "guerrilla": "military tactical gear and combat uniform",
        "casual": "casual civilian clothing",
    },
}

# 합성 기본 프롬프트 템플릿
COMPOSITE_PROMPT_TEMPLATE = (
    "Edit this portrait photo: dress this person in {uniform_description}. "
    "Keep the person's face, expression, and skin tone exactly the same. "
    "Only change the clothing and add appropriate headgear if needed. "
    "The background should be plain/transparent. "
    "Maintain photorealistic quality."
)


class GeminiCompositor:
    """Gemini (Nano Banana) API를 사용한 의상 합성."""

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or GEMINI_API_KEY
        self._client = None

    @property
    def client(self):
        """Gemini API 클라이언트 (지연 초기화)."""
        if self._client is None:
            if not self.api_key:
                raise ValueError(
                    "GEMINI_API_KEY 환경변수를 설정하거나 api_key를 전달하세요."
                )
            from google import genai
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    # ------------------------------------------------------------------
    # 의상 합성
    # ------------------------------------------------------------------

    def composite_outfit(
        self,
        image: Image.Image,
        outfit_description: str,
        model: str = "gemini-3.1-flash-image-preview",
    ) -> Image.Image | None:
        """인물 이미지에 의상을 합성한다.

        Args:
            image: 인물 이미지 (배경 제거된 것 권장).
            outfit_description: 의상 설명 (영어).
            model: Gemini 모델명.

        Returns:
            합성된 이미지 또는 실패 시 ``None``.
        """
        from google.genai import types

        prompt = COMPOSITE_PROMPT_TEMPLATE.format(
            uniform_description=outfit_description
        )

        try:
            response = self.client.models.generate_content(
                model=model,
                contents=[prompt, image],
                config=types.GenerateContentConfig(
                    response_modalities=["TEXT", "IMAGE"],
                ),
            )

            for part in response.parts:
                if part.inline_data is not None:
                    result = Image.open(BytesIO(part.inline_data.data))
                    logger.info(f"Gemini 합성 성공: {outfit_description[:40]}...")
                    return result

            logger.warning("Gemini 응답에 이미지 없음")
            return None

        except Exception as exc:
            logger.error(f"Gemini 합성 실패: {exc}")
            return None

    # ------------------------------------------------------------------
    # 국가별 군복 합성
    # ------------------------------------------------------------------

    def composite_by_tag(
        self,
        image: Image.Image,
        country_tag: str,
        outfit_type: str = "military",
        model: str = "gemini-3.1-flash-image-preview",
    ) -> Image.Image | None:
        """국가 태그 + 의상 타입으로 합성한다.

        Args:
            image: 인물 이미지.
            country_tag: HOI4 국가 태그 (예: "AFG", "USA").
            outfit_type: "military", "suit", "guerrilla" 등.
            model: Gemini 모델명.

        Returns:
            합성된 이미지 또는 ``None``.
        """
        # 국가별 프롬프트 조회
        tag_prompts = UNIFORM_PROMPTS.get(
            country_tag, UNIFORM_PROMPTS["generic"]
        )
        description = tag_prompts.get(
            outfit_type,
            UNIFORM_PROMPTS["generic"].get(outfit_type, "military uniform"),
        )

        logger.info(f"Gemini 합성: [{country_tag}] {outfit_type} → {description}")
        return self.composite_outfit(image, description, model)

    # ------------------------------------------------------------------
    # 멀티턴 편집 (반복 수정)
    # ------------------------------------------------------------------

    def interactive_edit(
        self,
        image: Image.Image,
        prompts: list[str],
        model: str = "gemini-3.1-flash-image-preview",
    ) -> Image.Image | None:
        """멀티턴으로 이미지를 단계적으로 편집한다.

        Args:
            image: 원본 이미지.
            prompts: 순차적 편집 프롬프트 리스트.
            model: Gemini 모델명.

        Returns:
            최종 편집된 이미지 또는 ``None``.
        """
        from google.genai import types

        chat = self.client.chats.create(
            model=model,
            config=types.GenerateContentConfig(
                response_modalities=["TEXT", "IMAGE"],
            ),
        )

        # 첫 번째: 이미지 + 프롬프트
        current_image = None
        first_prompt = prompts[0] if prompts else "Describe this image"

        try:
            response = chat.send_message([first_prompt, image])
            for part in response.parts:
                if part.inline_data is not None:
                    current_image = Image.open(BytesIO(part.inline_data.data))
                    break

            # 후속 프롬프트
            for prompt in prompts[1:]:
                if current_image is None:
                    break
                response = chat.send_message(prompt)
                for part in response.parts:
                    if part.inline_data is not None:
                        current_image = Image.open(BytesIO(part.inline_data.data))
                        break

            return current_image

        except Exception as exc:
            logger.error(f"Gemini 멀티턴 편집 실패: {exc}")
            return None

    # ------------------------------------------------------------------
    # 파일 기반 편의 메서드
    # ------------------------------------------------------------------

    def composite_from_paths(
        self,
        input_path: Path,
        output_path: Path,
        country_tag: str = "generic",
        outfit_type: str = "military",
    ) -> bool:
        """파일 경로 기반 합성."""
        try:
            image = Image.open(input_path).convert("RGB")
        except Exception as exc:
            logger.error(f"이미지 로드 실패: {exc}")
            return False

        result = self.composite_by_tag(image, country_tag, outfit_type)
        if result is None:
            return False

        output_path.parent.mkdir(parents=True, exist_ok=True)
        result.save(str(output_path), "PNG")
        logger.info(f"합성 저장: {output_path}")
        return True
