"""
검색 인프라 — Tavily → DuckDuckGo 폴백 체인.

환경변수:
- TAVILY_API_KEY: Tavily Search API 키 (무료 1000회/월)
- GOOGLE_API_KEY + GOOGLE_CX: Google Custom Search (선택)

검색 실패 시 모델에 "검색 불가" 메시지를 명확히 반환하여
할루시네이션을 원천 차단한다.
"""
from __future__ import annotations

import os
import time
from typing import Any

from loguru import logger

# =====================================================================
# 검색 결과 포매터
# =====================================================================

def _format_results(results: list[dict[str, str]]) -> str:
    """검색 결과 목록을 LLM-readable 문자열로 포매팅."""
    if not results:
        return ""
    parts: list[str] = []
    for i, r in enumerate(results, 1):
        title = r.get("title", "")
        body = r.get("body", r.get("content", ""))
        url = r.get("url", r.get("href", ""))
        parts.append(f"[{i}] {title}\n{body}\n출처: {url}")
    return "\n\n".join(parts)


# =====================================================================
# Tavily Search
# =====================================================================

def _search_tavily(query: str, max_results: int = 5) -> list[dict[str, str]]:
    """Tavily Search API 호출. 키가 없으면 빈 리스트."""
    api_key = os.environ.get("TAVILY_API_KEY", "")
    if not api_key:
        logger.debug("TAVILY_API_KEY 미설정 — Tavily 건너뜀")
        return []

    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=api_key)
        response = client.search(
            query=query,
            max_results=max_results,
            include_answer=True,
            search_depth="advanced",
        )
        results: list[dict[str, str]] = []
        # answer가 있으면 첫 번째로 추가
        if response.get("answer"):
            results.append({
                "title": "AI 요약",
                "body": response["answer"],
                "url": "",
            })
        for item in response.get("results", []):
            results.append({
                "title": item.get("title", ""),
                "body": item.get("content", ""),
                "url": item.get("url", ""),
            })
        logger.info("Tavily 검색 성공: '{}' → {}건", query, len(results))
        return results
    except Exception as exc:
        logger.warning("Tavily 검색 실패: {}", exc)
        return []


# =====================================================================
# DuckDuckGo Search (폴백)
# =====================================================================

def _search_ddgs(query: str, max_results: int = 5) -> list[dict[str, str]]:
    """DuckDuckGo 텍스트 검색. 실패 시 빈 리스트."""
    try:
        try:
            from ddgs import DDGS  # 신규 패키지명
        except ImportError:
            from duckduckgo_search import DDGS  # 레거시 호환
        results: list[dict[str, str]] = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append({
                    "title": r.get("title", ""),
                    "body": r.get("body", ""),
                    "url": r.get("href", ""),
                })
        logger.info("DDGS 검색 성공: '{}' → {}건", query, len(results))
        return results
    except Exception as exc:
        logger.warning("DDGS 검색 실패: {}", exc)
        return []


# =====================================================================
# Google Custom Search (선택적)
# =====================================================================

def _search_google(query: str, max_results: int = 5) -> list[dict[str, str]]:
    """Google Custom Search API. 키 미설정 시 빈 리스트."""
    api_key = os.environ.get("GOOGLE_API_KEY", "")
    cx = os.environ.get("GOOGLE_CX", "")
    if not api_key or not cx:
        return []

    try:
        import requests
        resp = requests.get(
            "https://www.googleapis.com/customsearch/v1",
            params={"key": api_key, "cx": cx, "q": query, "num": min(max_results, 10)},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        results: list[dict[str, str]] = []
        for item in data.get("items", []):
            results.append({
                "title": item.get("title", ""),
                "body": item.get("snippet", ""),
                "url": item.get("link", ""),
            })
        logger.info("Google 검색 성공: '{}' → {}건", query, len(results))
        return results
    except Exception as exc:
        logger.warning("Google 검색 실패: {}", exc)
        return []


# =====================================================================
# 통합 검색 (폴백 체인 + 재시도)
# =====================================================================

# 검색 실패 시 모델에 반환할 명시적 경고 메시지
SEARCH_FAILURE_MSG = (
    "[검색 실패] 모든 검색 엔진이 결과를 반환하지 못했습니다.\n"
    "⚠️ 절대로 내부 지식으로 추측하지 마세요.\n"
    "유저에게 '현재 검색이 불가하여 정확한 정보를 확인할 수 없습니다'라고 알리세요."
)


def web_search(query: str, max_results: int = 5, max_retries: int = 2) -> str:
    """
    통합 웹 검색. 폴백 체인: Tavily → Google → DuckDuckGo.

    모든 소스가 실패하면 재시도 후 SEARCH_FAILURE_MSG 반환.
    모델이 이 메시지를 보면 추측 대신 유저에게 검색 불가를 알린다.
    """
    engines = [
        ("Tavily", _search_tavily),
        ("Google", _search_google),
        ("DuckDuckGo", _search_ddgs),
    ]

    for attempt in range(max_retries + 1):
        for engine_name, engine_fn in engines:
            results = engine_fn(query, max_results=max_results)
            if results:
                formatted = _format_results(results)
                return f"[검색 엔진: {engine_name}]\n\n{formatted}"

        if attempt < max_retries:
            wait = 2 ** (attempt + 1)
            logger.warning(
                "모든 검색 엔진 실패 (시도 {}/{}), {}초 후 재시도",
                attempt + 1, max_retries + 1, wait,
            )
            time.sleep(wait)

    logger.error("웹 검색 완전 실패: '{}'", query)
    return SEARCH_FAILURE_MSG
