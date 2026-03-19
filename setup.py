from setuptools import setup, find_packages

setup(
    name="hoi4-modding-agent",
    version="4.0.0",
    description="AI-powered modding assistant for Hearts of Iron IV",
    author="Breaking Point Team",
    python_requires=">=3.11,<3.13",
    packages=find_packages(exclude=["tests*", "docs*", "examples*"]),
    install_requires=[
        "anthropic>=0.40.0",
        "google-genai>=1.0.0",
        "openai>=1.0.0",
        "streamlit>=1.31.0",
        "python-dotenv>=1.0.0",
        "requests>=2.31.0",
        "Pillow>=10.2.0",
        "pydantic>=2.11.0",
        "loguru>=0.7.2",
        "click>=8.1.8",
        "mwparserfromhell>=0.6.6",
        "SPARQLWrapper>=2.0.0",
        "tqdm>=4.66.1",
    ],
    extras_require={
        "search": [
            "ddgs>=7.0.0",
            "tavily-python>=0.5.0",
            "icrawler>=0.6.6",
        ],
        "portrait": [
            # Gemini API
            "google-generativeai>=0.8.0",
            "google-genai>=0.3.0",
            # 이미지 처리 — numpy<2 필수 (mediapipe 호환)
            "numpy>=1.26.0,<2",
            "opencv-python>=4.9.0.80,<4.12",
            "opencv-contrib-python>=4.9.0.80,<4.12",
            "mediapipe>=0.10.21",
            # 배경 제거
            "rembg>=2.0.67,<2.0.70",
            "onnxruntime>=1.17.0",
            # rembg 내부 의존성 (numba/llvmlite는 반드시 프리빌드 휠 사용)
            "llvmlite>=0.43.0",
            "numba>=0.60.0",
            "pymatting>=1.1.12",
            "scikit-image>=0.22.0",
            "scipy>=1.12.0",
        ],
        "mcp": [
            "mcp>=1.0.0",
            "nest-asyncio>=1.6.0",
        ],
        "dev": [
            "pytest>=7.4.4",
            "pytest-cov>=4.1.0",
            "pytest-mock>=3.12.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "hoi4-agent=hoi4_agent.cli:main",
        ],
    },
)
