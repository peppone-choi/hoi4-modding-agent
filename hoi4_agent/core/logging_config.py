"""
로깅 설정.
loguru를 사용한 구조화된 로깅.
"""
import sys
from pathlib import Path
from loguru import logger


def setup_logging(log_dir: Path | None = None, level: str = "INFO") -> None:
    """로깅 초기화. 콘솔 + 파일 로깅 설정."""
    logger.remove()
    
    # 콘솔 출력 (색상 포함)
    logger.add(
        sys.stdout,
        level=level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        colorize=True,
    )
    
    # 파일 출력 (tools/logs/ 에 저장)
    if log_dir:
        log_dir.mkdir(parents=True, exist_ok=True)
        logger.add(
            log_dir / "breaking_point_{time:YYYY-MM-DD}.log",
            level="DEBUG",
            rotation="1 day",
            retention="7 days",
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        )


def get_logger(name: str):
    """모듈별 logger 반환."""
    return logger.bind(name=name)
