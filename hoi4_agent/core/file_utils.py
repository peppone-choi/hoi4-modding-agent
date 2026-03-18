"""
파일 읽기/쓰기 헬퍼 유틸리티.
큰 파일 자동 처리, 청크 읽기, 파일 정보 조회 등.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Iterator

# File content cache: {path_str: (content, timestamp)}
_file_cache: dict[str, tuple[str, float]] = {}


def read_file_cached(file_path: Path, max_age_seconds: int = 300) -> str:
    """Read file with caching (default TTL: 5 minutes).
    
    Args:
        file_path: File path to read
        max_age_seconds: Cache TTL in seconds (default: 300)
        
    Returns:
        File content as string
    """
    cache_key = str(file_path.resolve())
    now = time.time()
    
    if cache_key in _file_cache:
        content, timestamp = _file_cache[cache_key]
        if now - timestamp < max_age_seconds:
            return content
    
    content = file_path.read_text(encoding="utf-8-sig", errors="replace")
    _file_cache[cache_key] = (content, now)
    return content


def invalidate_file_cache(file_path: Path) -> None:
    """Invalidate cache for a specific file.
    
    Args:
        file_path: File path to invalidate
    """
    cache_key = str(file_path.resolve())
    _file_cache.pop(cache_key, None)


def clear_file_cache() -> None:
    """Clear entire file cache."""
    _file_cache.clear()


def get_file_line_count(file_path: Path) -> int:
    """파일의 총 줄 수를 빠르게 계산한다.
    
    Args:
        file_path: 파일 경로
        
    Returns:
        총 줄 수
    """
    if not file_path.exists():
        return 0
    
    count = 0
    with file_path.open("rb") as f:
        for _ in f:
            count += 1
    return count


def get_file_info(file_path: Path) -> dict:
    """파일 정보를 반환한다.
    
    Args:
        file_path: 파일 경로
        
    Returns:
        파일 정보 딕셔너리 (size_bytes, line_count, encoding)
    """
    if not file_path.exists():
        return {"error": "파일 없음"}
    
    size = file_path.stat().st_size
    line_count = get_file_line_count(file_path)
    
    encoding = "utf-8"
    try:
        raw = file_path.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            encoding = "utf-8-sig"
    except Exception:
        pass
    
    return {
        "size_bytes": size,
        "size_kb": round(size / 1024, 2),
        "line_count": line_count,
        "encoding": encoding,
        "is_large": line_count > 2000,
    }


def read_file_chunk(
    file_path: Path,
    start_line: int = 1,
    num_lines: int = 2000,
) -> tuple[str, bool]:
    """파일의 특정 줄 범위를 읽는다.
    
    Args:
        file_path: 파일 경로
        start_line: 시작 줄 번호 (1-indexed)
        num_lines: 읽을 줄 수
        
    Returns:
        (내용, 더 읽을 내용이 있는지)
    """
    if not file_path.exists():
        return "", False
    
    lines = []
    has_more = False
    
    with file_path.open("r", encoding="utf-8-sig", errors="replace") as f:
        for idx, line in enumerate(f, 1):
            if idx < start_line:
                continue
            if idx >= start_line + num_lines:
                has_more = True
                break
            lines.append(f"{idx}: {line.rstrip()}")
    
    return "\n".join(lines), has_more


def read_large_file(
    file_path: Path,
    start_line: int = 1,
    end_line: int | None = None,
    chunk_size: int = 2000,
) -> str:
    """큰 파일을 여러 청크로 나눠 읽는다.
    
    Args:
        file_path: 파일 경로
        start_line: 시작 줄 번호 (1-indexed)
        end_line: 끝 줄 번호 (None이면 파일 끝까지)
        chunk_size: 청크당 줄 수
        
    Returns:
        파일 내용
    """
    if not file_path.exists():
        return "[오류] 파일 없음"
    
    info = get_file_info(file_path)
    total_lines = info["line_count"]
    
    final_line = total_lines if end_line is None else end_line
    
    lines = []
    current_line = start_line
    
    while current_line <= final_line:
        chunk, has_more = read_file_chunk(
            file_path,
            start_line=current_line,
            num_lines=min(chunk_size, final_line - current_line + 1),
        )
        lines.append(chunk)
        current_line += chunk_size
        
        if not has_more:
            break
    
    return "\n".join(lines)


def read_file_smart(
    file_path: Path,
    max_lines: int = 2000,
) -> tuple[str, dict]:
    """스마트 파일 읽기.
    
    작은 파일은 전체를 읽고, 큰 파일은 처음 max_lines만 읽고 경고를 반환한다.
    
    Args:
        file_path: 파일 경로
        max_lines: 한 번에 읽을 최대 줄 수
        
    Returns:
        (내용, 메타정보)
    """
    info = get_file_info(file_path)
    
    if "error" in info:
        return "", info
    
    if not info["is_large"]:
        content = file_path.read_text(encoding="utf-8-sig", errors="replace")
        numbered = "\n".join(
            f"{idx}: {line}" 
            for idx, line in enumerate(content.splitlines(), 1)
        )
        return numbered, {**info, "read_all": True}
    
    content, has_more = read_file_chunk(file_path, start_line=1, num_lines=max_lines)
    
    meta = {
        **info,
        "read_all": False,
        "lines_read": max_lines,
        "next_offset": max_lines + 1 if has_more else None,
        "warning": f"파일이 큽니다 ({info['line_count']}줄). 처음 {max_lines}줄만 표시합니다.",
    }
    
    return content, meta


def iter_file_chunks(
    file_path: Path,
    chunk_size: int = 2000,
) -> Iterator[tuple[str, int, bool]]:
    """파일을 청크 단위로 순회한다.
    
    Args:
        file_path: 파일 경로
        chunk_size: 청크당 줄 수
        
    Yields:
        (내용, 시작 줄 번호, 더 있는지)
    """
    if not file_path.exists():
        return
    
    current_line = 1
    
    while True:
        content, has_more = read_file_chunk(
            file_path,
            start_line=current_line,
            num_lines=chunk_size,
        )
        
        if not content:
            break
        
        yield content, current_line, has_more
        
        if not has_more:
            break
        
        current_line += chunk_size


def search_in_large_file(
    file_path: Path,
    pattern: str,
    max_results: int = 100,
) -> list[dict]:
    """큰 파일에서 패턴을 검색한다.
    
    Args:
        file_path: 파일 경로
        pattern: 검색할 문자열 (정규식 아님)
        max_results: 최대 결과 수
        
    Returns:
        매칭 결과 리스트 [{"line": 줄번호, "text": 줄내용}, ...]
    """
    import re
    
    if not file_path.exists():
        return []
    
    try:
        regex = re.compile(re.escape(pattern), re.IGNORECASE)
    except re.error:
        regex = re.compile(re.escape(pattern))
    
    results = []
    
    with file_path.open("r", encoding="utf-8-sig", errors="replace") as f:
        for line_num, line in enumerate(f, 1):
            if regex.search(line):
                results.append({
                    "line": line_num,
                    "text": line.rstrip()[:200],
                })
                if len(results) >= max_results:
                    break
    
    return results


def read_file_full_chunked(
    file_path: Path,
    offset: int = 1,
    limit: int = 2000,
) -> tuple[str, dict]:
    """전체 파일을 청크 단위로 읽는다 (offset/limit 방식).
    
    큰 파일을 여러 번에 나눠 읽을 때 사용.
    AI 에이전트가 "다음 청크"를 순차적으로 읽을 수 있도록 메타데이터를 제공.
    
    Args:
        file_path: 파일 경로
        offset: 시작 줄 번호 (1-indexed)
        limit: 읽을 줄 수 (청크 크기)
        
    Returns:
        (내용, 메타정보)
        메타정보: {
            "total_lines": 전체 줄 수,
            "current_offset": 현재 오프셋,
            "lines_read": 실제 읽은 줄 수,
            "next_offset": 다음 청크 시작 줄 (None이면 끝),
            "chunk_number": 현재 청크 번호 (1부터 시작),
            "total_chunks": 전체 청크 수,
            "progress": 진행률 (0.0 ~ 1.0),
            "is_last_chunk": 마지막 청크 여부
        }
    """
    import math
    
    if not file_path.exists():
        return "[오류] 파일 없음", {}
    
    info = get_file_info(file_path)
    total_lines = info["line_count"]
    
    if offset < 1:
        offset = 1
    if offset > total_lines:
        return "[오류] 오프셋이 파일 범위를 벗어남", {
            "total_lines": total_lines,
            "current_offset": offset,
            "error": f"오프셋 {offset}은 파일 범위 (1-{total_lines})를 벗어남"
        }
    
    total_chunks = math.ceil(total_lines / limit)
    current_chunk = math.ceil(offset / limit)
    
    remaining_lines = total_lines - offset + 1
    lines_to_read = min(limit, remaining_lines)
    
    content, has_more = read_file_chunk(file_path, offset, lines_to_read)
    
    next_offset = None if not has_more else offset + lines_to_read
    is_last_chunk = not has_more or next_offset is None
    
    progress = min(1.0, (offset + lines_to_read - 1) / total_lines)
    
    meta = {
        "total_lines": total_lines,
        "current_offset": offset,
        "lines_read": lines_to_read,
        "next_offset": next_offset,
        "chunk_number": current_chunk,
        "total_chunks": total_chunks,
        "progress": round(progress, 3),
        "is_last_chunk": is_last_chunk,
        "encoding": info["encoding"],
    }
    
    return content, meta


def edit_file_lines(
    file_path: Path,
    start_line: int,
    end_line: int,
    new_content: str,
) -> dict:
    """파일의 특정 라인 범위를 새 내용으로 교체한다.
    
    Args:
        file_path: 파일 경로
        start_line: 시작 줄 번호 (1-indexed, 이 줄부터 삭제)
        end_line: 끝 줄 번호 (1-indexed, 이 줄까지 삭제)
        new_content: 삽입할 새 내용 (여러 줄 가능)
        
    Returns:
        {
            "success": True/False,
            "message": 결과 메시지,
            "lines_removed": 삭제된 줄 수,
            "lines_added": 추가된 줄 수,
            "total_lines_before": 편집 전 전체 줄 수,
            "total_lines_after": 편집 후 전체 줄 수,
        }
    """
    if not file_path.exists():
        return {
            "success": False,
            "message": f"[오류] 파일 없음: {file_path}",
        }
    
    if start_line < 1 or end_line < start_line:
        return {
            "success": False,
            "message": f"[오류] 잘못된 라인 범위: {start_line}-{end_line}",
        }
    
    info = get_file_info(file_path)
    encoding = info["encoding"]
    
    with file_path.open("r", encoding=encoding, errors="replace") as f:
        lines = f.readlines()
    
    total_lines_before = len(lines)
    
    if start_line > total_lines_before:
        return {
            "success": False,
            "message": f"[오류] 시작 라인 {start_line}이 파일 범위 (1-{total_lines_before})를 벗어남",
        }
    
    if end_line > total_lines_before:
        end_line = total_lines_before
    
    lines_removed = end_line - start_line + 1
    
    new_lines = new_content.splitlines(keepends=True)
    if new_lines and not new_lines[-1].endswith("\n"):
        new_lines[-1] += "\n"
    
    lines_added = len(new_lines)
    
    result_lines = (
        lines[: start_line - 1] + 
        new_lines + 
        lines[end_line:]
    )
    
    total_lines_after = len(result_lines)
    
    with file_path.open("w", encoding="utf-8", errors="replace") as f:
        f.writelines(result_lines)
    
    return {
        "success": True,
        "message": f"[편집 완료] {start_line}-{end_line}줄 교체 ({lines_removed}줄 삭제 → {lines_added}줄 추가)",
        "lines_removed": lines_removed,
        "lines_added": lines_added,
        "total_lines_before": total_lines_before,
        "total_lines_after": total_lines_after,
    }


def replace_in_file(
    file_path: Path,
    old_text: str,
    new_text: str,
    max_replacements: int | None = None,
) -> dict:
    """파일 내 문자열을 찾아서 교체한다.
    
    Args:
        file_path: 파일 경로
        old_text: 찾을 문자열
        new_text: 바꿀 문자열
        max_replacements: 최대 교체 횟수 (None이면 전체 교체)
        
    Returns:
        {
            "success": True/False,
            "message": 결과 메시지,
            "replacements": 교체된 횟수,
            "preview": 교체된 위치 목록 (최대 10개),
        }
    """
    if not file_path.exists():
        return {
            "success": False,
            "message": f"[오류] 파일 없음: {file_path}",
            "replacements": 0,
        }
    
    info = get_file_info(file_path)
    encoding = info["encoding"]
    
    with file_path.open("r", encoding=encoding, errors="replace") as f:
        content = f.read()
    
    if old_text not in content:
        return {
            "success": False,
            "message": f"[오류] 문자열을 찾을 수 없음: '{old_text[:50]}...'",
            "replacements": 0,
        }
    
    count = content.count(old_text)
    
    if max_replacements is not None:
        replacements = 0
        result = []
        parts = content.split(old_text)
        
        for i, part in enumerate(parts[:-1]):
            result.append(part)
            if replacements < max_replacements:
                result.append(new_text)
                replacements += 1
            else:
                result.append(old_text)
        result.append(parts[-1])
        
        new_content = "".join(result)
    else:
        new_content = content.replace(old_text, new_text)
        replacements = count
    
    lines = content.split("\n")
    preview = []
    for line_num, line in enumerate(lines[:1000], 1):
        if old_text in line and len(preview) < 10:
            preview.append({
                "line": line_num,
                "text": line.strip()[:100],
            })
    
    with file_path.open("w", encoding="utf-8", errors="replace") as f:
        f.write(new_content)
    
    limit_msg = f" (최대 {max_replacements}회)" if max_replacements else ""
    
    return {
        "success": True,
        "message": f"[교체 완료] '{old_text[:30]}...' → '{new_text[:30]}...': {replacements}회{limit_msg}",
        "replacements": replacements,
        "preview": preview,
    }
