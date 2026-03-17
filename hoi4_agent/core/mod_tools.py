"""
모드 도구 v2 — 범용 HOI4 모드 파일 조작 도구 모음.

모든 함수는 mod_root 를 파라미터로 받아 어떤 모드에서든 동작한다.
하드코딩된 경로 없음.
"""
from __future__ import annotations

import difflib
import json
import re
import shutil
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

_SKIP_DIRS = {".git", ".venv", "__pycache__", "tools", ".omc", ".omx", ".claude", ".cache"}


# =====================================================================
# search_mod
# =====================================================================

def search_mod(mod_root: Path, query: str, file_type: str = "", directory: str = "", max_results: int = 30) -> str:
    """모드 파일 내에서 텍스트/패턴을 검색한다."""
    search_dir = mod_root / directory if directory else mod_root
    if not search_dir.is_dir():
        return f"[검색 오류] 디렉토리 없음: {directory}"
    globs = [f"**/*.{file_type}"] if file_type else ["**/*.txt", "**/*.yml", "**/*.gui", "**/*.gfx"]
    try:
        regex = re.compile(query, re.IGNORECASE)
    except re.error:
        regex = re.compile(re.escape(query), re.IGNORECASE)
    results: list[str] = []
    for g in globs:
        for fp in search_dir.glob(g):
            if set(fp.relative_to(mod_root).parts) & _SKIP_DIRS:
                continue
            try:
                text = fp.read_text(encoding="utf-8-sig", errors="replace")
                for ln, line in enumerate(text.splitlines(), 1):
                    if regex.search(line):
                        results.append(f"{fp.relative_to(mod_root)}:{ln}: {line.strip()[:120]}")
                        if len(results) >= max_results:
                            break
            except Exception:
                continue
            if len(results) >= max_results:
                break
        if len(results) >= max_results:
            break
    if not results:
        return f"[검색 결과 없음] '{query}'"
    return f"[검색 결과 {len(results)}건]\n" + "\n".join(results)


# =====================================================================
# get_schema
# =====================================================================

def get_schema(file_type: str) -> str:
    """HOI4 파일 타입의 스키마를 반환한다."""
    try:
        from tools.shared.hoi4_schema import FILE_SCHEMAS, SCOPES, MODIFIER_CATEGORIES, get_automation_tier, get_all_file_types
    except ImportError as exc:
        return f"[스키마 오류] hoi4_schema 모듈 로드 실패: {exc}"
    if file_type == "list":
        return json.dumps({"사용가능_파일타입": get_all_file_types()}, ensure_ascii=False, indent=2)
    if file_type == "scopes":
        return json.dumps(SCOPES, ensure_ascii=False, indent=2)
    if file_type == "modifiers":
        return json.dumps(MODIFIER_CATEGORIES, ensure_ascii=False, indent=2)
    schema = FILE_SCHEMAS.get(file_type)
    if schema is None:
        return f"[스키마 오류] 알 수 없는 타입: '{file_type}'\n사용가능: {', '.join(get_all_file_types())}"
    return json.dumps({"file_type": file_type, "automation_tier": get_automation_tier(file_type), **schema}, ensure_ascii=False, indent=2)


# =====================================================================
# validate_pdx
# =====================================================================

def validate_pdx(content: str, file_type: str) -> str:
    """PDX Script 를 스키마 대비 검증한다."""
    issues: list[str] = []
    depth = 0; in_str = in_cmt = False
    for i, ch in enumerate(content):
        if in_cmt:
            if ch == "\n": in_cmt = False
            continue
        if in_str:
            if ch == "\\": continue
            if ch == '"': in_str = False
            continue
        if ch == "#": in_cmt = True; continue
        if ch == '"': in_str = True; continue
        if ch == "{": depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                issues.append(f"구문 오류: 위치 {i} 여분의 '}}'")
                break
    if depth > 0:
        issues.append(f"구문 오류: 닫히지 않은 '{{' {depth}개")
    try:
        from tools.shared.hoi4_schema import FILE_SCHEMAS
        schema = FILE_SCHEMAS.get(file_type, {})
        for key in schema.get("required_keys", []):
            if key not in content:
                issues.append(f"필수 키 누락: '{key}'")
    except ImportError:
        pass
    if file_type == "country_history":
        pm = re.search(r"set_popularities\s*=\s*\{([^}]+)\}", content, re.DOTALL)
        if pm:
            total = sum(int(n) for n in re.findall(r"=\s*(\d+)", pm.group(1)))
            if total != 100:
                issues.append(f"set_popularities 합계 {total}% (100% 필요)")
    elif file_type == "character":
        for m in re.finditer(r"^\t(\w+)\s*=\s*\{", content, re.MULTILINE):
            cid = m.group(1)
            if cid not in ("characters", "portraits", "civilian", "army", "navy"):
                if not re.match(r"^[A-Z0-9_]+_\w+", cid):
                    issues.append(f"캐릭터 ID 패턴 불일치: '{cid}'")
    elif file_type == "localisation":
        for ln, line in enumerate(content.splitlines(), 1):
            s = line.strip()
            if not s or s.startswith("#") or s.startswith("l_"): continue
            if not re.match(r'^\s*[\w.]+:\d+\s+"', s):
                issues.append(f"줄 {ln}: 로컬 형식 불일치")
                if len(issues) > 20:
                    issues.append("... (이하 생략)"); break
    if not issues:
        return f"[검증 통과] '{file_type}' — 이슈 없음 ✅"
    return f"[검증 결과] {len(issues)}건 이슈\n" + "\n".join(f"  • {i}" for i in issues)


# =====================================================================
# diff_preview: 수정 전 미리보기
# =====================================================================

def diff_preview(mod_root: Path, path: str, new_content: str) -> str:
    """기존 파일과 새 내용의 diff 를 생성한다."""
    fp = mod_root / path
    old = fp.read_text(encoding="utf-8-sig", errors="replace").splitlines(keepends=True) if fp.exists() else []
    new = new_content.splitlines(keepends=True)
    diff = list(difflib.unified_diff(old, new, fromfile=f"현재/{path}", tofile=f"수정/{path}", lineterm=""))
    if not diff:
        return "[변경 없음] 기존 파일과 동일합니다."
    added = sum(1 for l in diff if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in diff if l.startswith("-") and not l.startswith("---"))
    return f"[Diff] +{added}줄 / -{removed}줄\n" + "\n".join(diff[:100]) + ("\n..." if len(diff) > 100 else "")


# =====================================================================
# safe_write: 자동 백업 + 쓰기
# =====================================================================

def safe_write(mod_root: Path, path: str, content: str, backup: bool = True) -> str:
    """파일을 안전하게 쓴다. backup=True 이면 .bak 백업."""
    fp = mod_root / path
    fp.parent.mkdir(parents=True, exist_ok=True)
    bak_msg = ""
    if backup and fp.exists():
        bak_dir = mod_root / "tools" / ".backups"
        bak_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        bak_name = f"{fp.stem}_{ts}{fp.suffix}.bak"
        shutil.copy2(fp, bak_dir / bak_name)
        bak_msg = f" (백업: tools/.backups/{bak_name})"
    fp.write_text(content, encoding="utf-8")
    return f"[저장 완료] {path} ({len(content)}자){bak_msg}"


# =====================================================================
# analyze_mod: 모드 건강 진단
# =====================================================================

def analyze_mod(mod_root: Path, check_type: str = "all") -> str:
    """모드 전체를 분석하여 문제점을 보고한다.
    check_type: all | portraits | loc | duplicates | orphans"""
    issues: list[str] = []
    warnings: list[str] = []
    if check_type in ("all", "duplicates"):
        _check_duplicate_ids(mod_root, issues)
    if check_type in ("all", "portraits"):
        _check_missing_portraits(mod_root, issues, warnings)
    if check_type in ("all", "loc"):
        _check_missing_loc(mod_root, issues, warnings)
    if check_type in ("all", "orphans"):
        _check_orphan_gfx(mod_root, warnings)
    parts: list[str] = []
    if issues:
        parts.append(f"❌ 오류 {len(issues)}건:\n" + "\n".join(f"  • {i}" for i in issues[:30]))
    if warnings:
        parts.append(f"⚠️ 경고 {len(warnings)}건:\n" + "\n".join(f"  • {w}" for w in warnings[:30]))
    if not issues and not warnings:
        parts.append("✅ 모드 분석 통과 — 문제 없음")
    return "\n\n".join(parts)


def _check_duplicate_ids(mod_root: Path, issues: list[str]) -> None:
    ids: dict[str, list[str]] = defaultdict(list)
    d = mod_root / "common" / "characters"
    if d.is_dir():
        for f in d.glob("*.txt"):
            t = f.read_text(encoding="utf-8-sig", errors="replace")
            r = str(f.relative_to(mod_root))
            for m in re.finditer(r"^\t(\w+)\s*=\s*\{", t, re.MULTILINE):
                cid = m.group(1)
                if cid != "characters":
                    ids[cid].append(r)
    for cid, files in ids.items():
        if len(files) > 1:
            issues.append(f"중복 캐릭터 ID: {cid} — {', '.join(files)}")
    eids: dict[str, list[str]] = defaultdict(list)
    d = mod_root / "events"
    if d.is_dir():
        for f in d.glob("*.txt"):
            t = f.read_text(encoding="utf-8-sig", errors="replace")
            r = str(f.relative_to(mod_root))
            for m in re.finditer(r"id\s*=\s*([\w.]+)", t):
                eids[m.group(1)].append(r)
    for eid, files in eids.items():
        if len(files) > 1:
            issues.append(f"중복 이벤트 ID: {eid} — {', '.join(set(files))}")


def _check_missing_portraits(mod_root: Path, issues: list[str], warnings: list[str]) -> None:
    d = mod_root / "common" / "characters"
    if not d.is_dir(): return
    checked = 0
    for f in d.glob("*.txt"):
        t = f.read_text(encoding="utf-8-sig", errors="replace")
        for m in re.finditer(r'large\s*=\s*"([^"]+)"', t):
            pp = m.group(1)
            checked += 1
            full = mod_root / pp
            if not full.exists() and not _ci_exists(mod_root, pp):
                issues.append(f"누락 초상화: {pp}")
    if checked:
        warnings.append(f"초상화 참조 {checked}건 검사 완료")


def _check_missing_loc(mod_root: Path, issues: list[str], warnings: list[str]) -> None:
    loc_keys: set[str] = set()
    ld = mod_root / "localisation"
    if ld.is_dir():
        for f in ld.rglob("*.yml"):
            t = f.read_text(encoding="utf-8-sig", errors="replace")
            for m in re.finditer(r"^\s*([\w.]+):\d+\s+\"", t, re.MULTILINE):
                loc_keys.add(m.group(1))
    if not loc_keys:
        warnings.append("로컬 키를 찾을 수 없음"); return
    missing = 0
    ed = mod_root / "events"
    if ed.is_dir():
        for f in ed.glob("*.txt"):
            t = f.read_text(encoding="utf-8-sig", errors="replace")
            for m in re.finditer(r'(?:title|desc|name)\s*=\s*(\w[\w.]*)', t):
                k = m.group(1)
                if k not in loc_keys and not k.startswith("GFX_") and k not in ("yes", "no", "always"):
                    missing += 1
    if missing:
        warnings.append(f"로컬 키 누락 가능성: 이벤트에서 {missing}건")


def _check_orphan_gfx(mod_root: Path, warnings: list[str]) -> None:
    d = mod_root / "interface"
    if not d.is_dir(): return
    cnt = 0
    for f in d.glob("*.gfx"):
        cnt += len(re.findall(r'name\s*=\s*"(GFX_\w+)"', f.read_text(encoding="utf-8-sig", errors="replace")))
    if cnt:
        warnings.append(f"GFX 스프라이트 {cnt}개 정의됨")


def _ci_exists(root: Path, rel: str) -> bool:
    cur = root
    for part in Path(rel).parts:
        if cur.is_dir():
            found = False
            for ch in cur.iterdir():
                if ch.name.lower() == part.lower():
                    cur = ch; found = True; break
            if not found: return False
        else:
            return False
    return cur.exists()


# =====================================================================
# find_entity: 스마트 엔티티 검색
# =====================================================================

def find_entity(mod_root: Path, entity_name: str, entity_type: str = "") -> str:
    """모드 내에서 캐릭터/이벤트/포커스를 이름/ID로 찾는다."""
    results: list[dict[str, str]] = []
    sl = entity_name.lower()
    if not entity_type or entity_type == "character":
        d = mod_root / "common" / "characters"
        if d.is_dir():
            for f in d.glob("*.txt"):
                t = f.read_text(encoding="utf-8-sig", errors="replace")
                for m in re.finditer(r"^\t(\w+)\s*=\s*\{", t, re.MULTILINE):
                    cid = m.group(1)
                    if cid == "characters": continue
                    if sl in cid.lower():
                        blk = t[m.start():m.start() + 500]
                        im = re.search(r"ideology\s*=\s*(\w+)", blk)
                        results.append({"type": "character", "id": cid, "file": str(f.relative_to(mod_root)), "ideology": im.group(1) if im else ""})
    if not entity_type or entity_type == "event":
        d = mod_root / "events"
        if d.is_dir():
            for f in d.glob("*.txt"):
                t = f.read_text(encoding="utf-8-sig", errors="replace")
                for m in re.finditer(r"id\s*=\s*([\w.]+)", t):
                    if sl in m.group(1).lower():
                        results.append({"type": "event", "id": m.group(1), "file": str(f.relative_to(mod_root))})
    if not entity_type or entity_type == "focus":
        d = mod_root / "common" / "national_focus"
        if d.is_dir():
            for f in d.glob("*.txt"):
                t = f.read_text(encoding="utf-8-sig", errors="replace")
                for m in re.finditer(r"\bid\s*=\s*(\w+)", t):
                    if sl in m.group(1).lower():
                        results.append({"type": "focus", "id": m.group(1), "file": str(f.relative_to(mod_root))})
    if not results:
        return f"[엔티티 없음] '{entity_name}'"
    return f"[{len(results)}건 발견]\n" + json.dumps(results[:30], ensure_ascii=False, indent=2)


# =====================================================================
# list_country_details: 국가 상세 조회
# =====================================================================

def list_country_details(mod_root: Path, tag: str) -> str:
    """특정 국가의 모든 관련 파일과 캐릭터를 조회한다."""
    info: dict[str, Any] = {"tag": tag}
    hd = mod_root / "history" / "countries"
    if hd.is_dir():
        for f in hd.glob("*.txt"):
            if f.stem.startswith(tag):
                info["history_file"] = str(f.relative_to(mod_root))
                t = f.read_text(encoding="utf-8-sig", errors="replace")
                info["recruited_characters"] = re.findall(r"recruit_character\s*=\s*(\w+)", t)
                cm = re.search(r"capital\s*=\s*(\d+)", t)
                if cm: info["capital"] = cm.group(1)
                rm = re.search(r"ruling_party\s*=\s*(\w+)", t)
                if rm: info["ruling_party"] = rm.group(1)
                break
    cd = mod_root / "common" / "characters"
    if cd.is_dir():
        for f in cd.glob("*.txt"):
            if tag in f.stem.upper():
                info["character_file"] = str(f.relative_to(mod_root)); break
    fd = mod_root / "common" / "national_focus"
    if fd.is_dir():
        for f in fd.glob("*.txt"):
            if tag in f.stem.upper():
                info["focus_file"] = str(f.relative_to(mod_root)); break
    ed = mod_root / "events"
    if ed.is_dir():
        evf = [str(f.relative_to(mod_root)) for f in ed.glob("*.txt") if tag in f.stem.upper()]
        if evf: info["event_files"] = evf
    return json.dumps(info, ensure_ascii=False, indent=2)
