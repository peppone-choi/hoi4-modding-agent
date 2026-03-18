"""
Task decomposition and Haiku suitability analysis.
Decision tree for routing tasks to appropriate execution strategy.

한국어/영어 양언어 패턴 매칭으로 채팅 메시지에서 직접 모델 라우팅 결정.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from hoi4_agent.core.orchestration import WorkerTask, WorkerType


class TaskComplexity(Enum):
    TRIVIAL = "trivial"
    SIMPLE = "simple"
    MODERATE = "moderate"
    COMPLEX = "complex"


class ExecutionStrategy(Enum):
    HAIKU_WORKER = "haiku_worker"
    SONNET_DIRECT = "sonnet_direct"
    SONNET_WITH_TOOLS = "sonnet_with_tools"


@dataclass
class TaskAnalysis:
    task_type: str
    complexity: TaskComplexity
    is_template_fillable: bool
    is_data_retrieval: bool
    requires_reasoning: bool
    requires_tools: bool
    estimated_tokens: int
    haiku_suitable: bool
    strategy: ExecutionStrategy
    worker_type: WorkerType | None = None


class TaskDecomposer:
    """Analyzes tasks and determines optimal execution strategy.
    
    한국어 채팅 메시지를 직접 분석하여 Haiku/Sonnet/Opus 라우팅 결정.
    보수적 기준: Haiku로 확실히 처리 가능한 것만 Haiku로 보냄.
    """
    
    # === Haiku 적합 패턴 (단순 조회/검색/읽기) ===
    HAIKU_SUITABLE_PATTERNS = [
        # English
        "fill template", "generate localization", "format output",
        "validate syntax", "search for", "read file",
        "list items", "extract data",
        # 한국어 — 단순 조회/읽기
        "읽어", "읽기", "읽고", "열어",
        "검색", "찾아", "찾기", "찾고",
        "목록", "리스트", "보여",
        "스키마", "확인해",
        "어디", "뭐야", "뭔가", "알려",
        "몇 개", "몇개", "있어?", "있나",
    ]

    # === 복잡 작업 — 반드시 Sonnet 이상 ===
    COMPLEX_TASK_PATTERNS = [
        # English
        "decide", "choose", "design", "architect", "plan",
        "analyze relationship", "compare options",
        "create", "implement", "refactor", "migrate",
        # 한국어 — 생성/수정/분석/다단계
        "추가해", "추가하", "만들어", "만들", "생성",
        "수정해", "수정하", "변경해", "변경하", "바꿔",
        "삭제해", "삭제하", "제거해", "제거하",
        "분석해", "분석하", "계획", "설계",
        "비교해", "비교하", "고쳐", "고치",
        "캐릭터", "인물", "지도자", "장군", "제독",
        "이벤트", "포커스", "디시전",
        "포트레잇", "초상화", "사진",
        "전체", "모든", "일괄", "배치",
    ]
    
    def analyze(self, task_description: str, context: dict | None = None) -> TaskAnalysis:
        """Analyze task and determine execution strategy."""
        task_lower = task_description.lower()
        
        complexity = self._assess_complexity(task_description, context)
        is_template_fillable = self._is_template_fillable(task_lower)
        is_data_retrieval = self._is_data_retrieval(task_lower)
        requires_reasoning = self._requires_reasoning(task_lower)
        requires_tools = self._requires_tools(task_description, context)
        estimated_tokens = self._estimate_tokens(task_description, context)
        
        haiku_suitable = (
            complexity in (TaskComplexity.TRIVIAL, TaskComplexity.SIMPLE)
            and (is_template_fillable or is_data_retrieval)
            and not requires_reasoning
            and estimated_tokens < 1500
        )
        
        if haiku_suitable:
            strategy = ExecutionStrategy.HAIKU_WORKER
            worker_type = self._select_worker_type(task_lower)
        elif requires_tools:
            strategy = ExecutionStrategy.SONNET_WITH_TOOLS
            worker_type = None
        else:
            strategy = ExecutionStrategy.SONNET_DIRECT
            worker_type = None
        
        return TaskAnalysis(
            task_type=self._classify_task_type(task_lower),
            complexity=complexity,
            is_template_fillable=is_template_fillable,
            is_data_retrieval=is_data_retrieval,
            requires_reasoning=requires_reasoning,
            requires_tools=requires_tools,
            estimated_tokens=estimated_tokens,
            haiku_suitable=haiku_suitable,
            strategy=strategy,
            worker_type=worker_type,
        )
    
    def decompose_batch(self, task_description: str, items: list) -> list[WorkerTask]:
        """Decompose batch task into parallel Haiku worker tasks."""
        analysis = self.analyze(task_description)
        
        if not analysis.haiku_suitable or not analysis.worker_type:
            return []
        
        return [
            WorkerTask(
                worker_type=analysis.worker_type,
                input_data={"item": item, "operation": task_description},
                quality_gate=self._select_quality_gate(analysis),
            )
            for item in items
        ]
    
    def _assess_complexity(self, task: str, context: dict | None) -> TaskComplexity:
        """Assess task complexity based on description and context."""
        task_lower = task.lower()
        
        # 복잡 작업 키워드 → 무조건 COMPLEX
        if any(p in task_lower for p in self.COMPLEX_TASK_PATTERNS):
            return TaskComplexity.COMPLEX
        
        # 영어 trivial 힌트
        if any(word in task_lower for word in ["trivial", "simple", "just", "only"]):
            return TaskComplexity.TRIVIAL
        
        # 외부 컨텍스트 의존성 많으면 COMPLEX
        if context and len(context.get("dependencies", [])) > 3:
            return TaskComplexity.COMPLEX
        
        # 긴 메시지 = 복잡할 가능성
        # 한국어는 공백 기준 split이 부정확하므로 글자 수도 참고
        word_count = len(task.split())
        char_count = len(task)
        if word_count > 20 or char_count > 80:
            return TaskComplexity.MODERATE
        
        return TaskComplexity.SIMPLE
    
    def _is_template_fillable(self, task: str) -> bool:
        """Check if task involves template filling."""
        return any(pattern in task for pattern in [
            "fill", "generate", "create from template", "format", "substitute",
            "로컬", "번역", "현지화",
        ])
    
    def _is_data_retrieval(self, task: str) -> bool:
        """Check if task is primarily data retrieval."""
        return any(pattern in task for pattern in [
            # English
            "search", "find", "read", "list", "get", "fetch", "retrieve", "extract",
            # 한국어
            "읽어", "읽기", "읽고", "검색", "찾아", "찾기", "찾고",
            "목록", "보여", "알려", "어디", "뭐야", "있어", "있나",
            "열어", "스키마", "확인",
        ])
    
    def _requires_reasoning(self, task: str) -> bool:
        """Check if task requires complex reasoning (→ must use Sonnet+)."""
        return any(p in task for p in self.COMPLEX_TASK_PATTERNS)
    
    def _requires_tools(self, task: str, context: dict | None) -> bool:
        """Check if task requires tool calls."""
        task_lower = task.lower()
        
        tool_indicators = [
            "file", "search", "validate", "write", "read", "modify", "update",
            "파일", "검색", "검증", "저장", "읽", "수정", "업데이트",
        ]
        
        return any(indicator in task_lower for indicator in tool_indicators)
    
    def _estimate_tokens(self, task: str, context: dict | None) -> int:
        """Estimate token count for task execution.
        
        한국어는 글자당 ~1.5 토큰, 영어는 단어당 ~1.3 토큰.
        """
        # 한국어 비율 추정 (한글 문자 수)
        korean_chars = sum(1 for c in task if '\uac00' <= c <= '\ud7a3')
        total_chars = len(task)
        
        if korean_chars > total_chars * 0.3:
            # 한국어 위주 메시지
            base = total_chars * 1.5
        else:
            # 영어 위주 메시지
            base = len(task.split()) * 1.3
        
        if context:
            context_size = sum(len(str(v)) for v in context.values())
            base += context_size * 0.3
        
        return int(base)
    
    def _classify_task_type(self, task: str) -> str:
        """Classify task into high-level type."""
        if any(k in task for k in ["localization", "loc", "로컬", "번역"]):
            return "localization"
        if any(k in task for k in ["validate", "check", "검증", "확인"]):
            return "validation"
        if any(k in task for k in ["search", "find", "검색", "찾"]):
            return "search"
        if any(k in task for k in ["read", "get", "읽", "열"]):
            return "retrieval"
        if any(k in task for k in ["template", "fill", "템플릿"]):
            return "template"
        if any(k in task for k in ["batch", "multiple", "일괄", "배치"]):
            return "batch"
        return "general"
    
    def _select_worker_type(self, task: str) -> WorkerType:
        """Select appropriate Haiku worker type."""
        if any(k in task for k in ["template", "fill", "템플릿"]):
            return WorkerType.TEMPLATE_FILLER
        if any(k in task for k in ["search", "find", "검색", "찾"]):
            return WorkerType.SEARCH_RUNNER
        if any(k in task for k in ["validate", "check", "검증", "확인"]):
            return WorkerType.VALIDATOR_RUNNER
        if any(k in task for k in ["localization", "loc", "로컬", "번역"]):
            return WorkerType.LOC_GENERATOR
        if any(k in task for k in ["read", "get", "읽", "열"]):
            return WorkerType.FILE_READER
        if any(k in task for k in ["batch", "multiple", "일괄", "배치"]):
            return WorkerType.BATCH_ITERATOR
        
        return WorkerType.FILE_READER
    
    def _select_quality_gate(self, analysis: TaskAnalysis) -> int:
        """Select quality gate level based on task analysis."""
        if analysis.complexity == TaskComplexity.TRIVIAL:
            return 1
        if analysis.is_template_fillable:
            return 2
        if analysis.is_data_retrieval:
            return 2
        return 3


def create_decomposer() -> TaskDecomposer:
    """Factory function to create task decomposer."""
    return TaskDecomposer()
