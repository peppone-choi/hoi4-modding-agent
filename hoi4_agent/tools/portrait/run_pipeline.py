#!/usr/bin/env python3
"""
TFR 초상화 생성 CLI.

사용법:
    # 단일 이미지 처리
    python run_pipeline.py single input.jpg output.png

    # 디렉토리 배치 처리
    python run_pipeline.py batch ./raw_images/ ./output/ --tag USA --name donald_trump

    # 웹 검색 + 자동 처리
    python run_pipeline.py search "Abdul Rashid Dostum" --tag AFG --max 5

    # 웹 검색만 (다운로드만, 처리 안함)
    python run_pipeline.py fetch "Donald Trump" --tag USA --max 10
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from loguru import logger

# 프로젝트 루트를 PYTHONPATH에 추가
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from hoi4_agent.tools.portrait.pipeline.portrait_pipeline import PortraitPipeline
from hoi4_agent.tools.portrait.search.multi_search import MultiSourceSearch


def cmd_single(args: argparse.Namespace) -> None:
    """단일 이미지 처리."""
    pipeline = PortraitPipeline()
    success = pipeline.process_single(Path(args.input), Path(args.output))
    if success:
        logger.info("완료!")
    else:
        logger.error("처리 실패")
        sys.exit(1)


def cmd_batch(args: argparse.Namespace) -> None:
    """배치 처리."""
    pipeline = PortraitPipeline()
    results = pipeline.batch_process(
        input_dir=Path(args.input_dir),
        output_dir=Path(args.output_dir),
        tag=args.tag or "",
        name_prefix=args.name or "",
    )
    success = sum(1 for v in results.values() if v)
    total = len(results)
    logger.info(f"배치 처리 완료: {success}/{total} 성공")


def cmd_search(args: argparse.Namespace) -> None:
    """웹 검색 + 자동 처리."""
    searcher = MultiSourceSearch()
    pipeline = PortraitPipeline()

    # 1. 검색 + 다운로드
    logger.info(f"검색 시작: {args.person_name}")
    downloaded = searcher.search_person(
        person_name=args.person_name,
        native_name=args.native_name,
        title=args.title,
        country_tag=args.tag,
        max_results=args.max,
    )

    if not downloaded:
        logger.error("검색 결과 없음")
        sys.exit(1)

    # 2. 중복 제거
    downloaded = searcher.deduplicate_by_hash(downloaded)
    logger.info(f"처리할 이미지: {len(downloaded)}개")

    # 3. 각 이미지 처리
    tag = args.tag or "XXX"
    name = args.person_name.replace(" ", "_").lower()
    output_dir = Path(args.output_dir) if args.output_dir else (
        PROJECT_ROOT / "gfx" / "Leaders" / tag
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    for idx, img_path in enumerate(downloaded):
        suffix = "" if idx == 0 else str(idx)
        out_name = f"{tag}_{name}{suffix}.png"
        out_path = output_dir / out_name
        logger.info(f"[{idx+1}/{len(downloaded)}] {img_path.name} → {out_name}")
        pipeline.process_single(img_path, out_path)


def cmd_fetch(args: argparse.Namespace) -> None:
    """웹 검색만 (다운로드만)."""
    searcher = MultiSourceSearch(
        cache_dir=Path(args.output_dir) if args.output_dir else None,
    )
    downloaded = searcher.search_person(
        person_name=args.person_name,
        native_name=args.native_name,
        title=args.title,
        country_tag=args.tag,
        max_results=args.max,
    )
    downloaded = searcher.deduplicate_by_hash(downloaded)
    logger.info(f"다운로드 완료: {len(downloaded)}개")
    for p in downloaded:
        print(p)


def main() -> None:
    parser = argparse.ArgumentParser(description="TFR 초상화 생성 CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    # single
    p_single = sub.add_parser("single", help="단일 이미지 처리")
    p_single.add_argument("input", help="입력 이미지 경로")
    p_single.add_argument("output", help="출력 이미지 경로")

    # batch
    p_batch = sub.add_parser("batch", help="배치 처리")
    p_batch.add_argument("input_dir", help="입력 디렉토리")
    p_batch.add_argument("output_dir", help="출력 디렉토리")
    p_batch.add_argument("--tag", help="국가 태그 (예: USA)")
    p_batch.add_argument("--name", help="인물명 접두사 (예: donald_trump)")

    # search
    p_search = sub.add_parser("search", help="웹 검색 + 자동 처리")
    p_search.add_argument("person_name", help="인물 영문명")
    p_search.add_argument("--native-name", help="현지어 이름")
    p_search.add_argument("--title", help="직함")
    p_search.add_argument("--tag", help="국가 태그")
    p_search.add_argument("--max", type=int, default=5, help="최대 결과 수")
    p_search.add_argument("--output-dir", help="출력 디렉토리")

    # fetch
    p_fetch = sub.add_parser("fetch", help="웹 검색만 (다운로드만)")
    p_fetch.add_argument("person_name", help="인물 영문명")
    p_fetch.add_argument("--native-name", help="현지어 이름")
    p_fetch.add_argument("--title", help="직함")
    p_fetch.add_argument("--tag", help="국가 태그")
    p_fetch.add_argument("--max", type=int, default=10, help="최대 결과 수")
    p_fetch.add_argument("--output-dir", help="출력 디렉토리")

    args = parser.parse_args()
    cmds = {
        "single": cmd_single,
        "batch": cmd_batch,
        "search": cmd_search,
        "fetch": cmd_fetch,
    }
    cmds[args.command](args)


if __name__ == "__main__":
    main()
