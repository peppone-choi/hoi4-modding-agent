from setuptools import setup, find_packages

setup(
    name="hoi4-modding-agent",
    version="4.0.0",
    description="AI-powered modding assistant for Hearts of Iron IV",
    author="Breaking Point Team",
    python_requires=">=3.11",
    packages=find_packages(exclude=["tests*", "docs*", "examples*"]),
    install_requires=[
        "anthropic>=0.40.0",
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
        ],
        "portrait": [
            "google-generativeai>=0.8.0",
            "google-genai>=0.3.0",
            "rembg>=2.0.67",
            "opencv-python>=4.9.0.80",
            "mediapipe>=0.10.21",
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
