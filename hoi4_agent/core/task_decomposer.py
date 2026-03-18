"""
Task decomposition and Haiku suitability analysis.
Decision tree for routing tasks to appropriate execution strategy.
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
    """Analyzes tasks and determines optimal execution strategy."""
    
    HAIKU_SUITABLE_PATTERNS = [
        "fill template",
        "generate localization",
        "format output",
        "validate syntax",
        "search for",
        "read file",
        "list items",
        "extract data",
    ]
    
    REQUIRES_REASONING_PATTERNS = [
        "decide",
        "choose",
        "design",
        "architect",
        "plan",
        "analyze relationship",
        "compare options",
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
        
        if any(word in task_lower for word in ["trivial", "simple", "just", "only"]):
            return TaskComplexity.TRIVIAL
        
        if any(word in task_lower for word in ["complex", "multiple", "several", "integrate"]):
            return TaskComplexity.COMPLEX
        
        if context and len(context.get("dependencies", [])) > 3:
            return TaskComplexity.COMPLEX
        
        if len(task.split()) > 20:
            return TaskComplexity.MODERATE
        
        return TaskComplexity.SIMPLE
    
    def _is_template_fillable(self, task: str) -> bool:
        """Check if task involves template filling."""
        return any(pattern in task for pattern in [
            "fill", "generate", "create from template", "format", "substitute",
        ])
    
    def _is_data_retrieval(self, task: str) -> bool:
        """Check if task is primarily data retrieval."""
        return any(pattern in task for pattern in [
            "search", "find", "read", "list", "get", "fetch", "retrieve", "extract",
        ])
    
    def _requires_reasoning(self, task: str) -> bool:
        """Check if task requires complex reasoning."""
        return any(pattern in task for pattern in self.REQUIRES_REASONING_PATTERNS)
    
    def _requires_tools(self, task: str, context: dict | None) -> bool:
        """Check if task requires tool calls."""
        task_lower = task.lower()
        
        tool_indicators = [
            "file", "search", "validate", "write", "read", "modify", "update",
        ]
        
        return any(indicator in task_lower for indicator in tool_indicators)
    
    def _estimate_tokens(self, task: str, context: dict | None) -> int:
        """Estimate token count for task execution."""
        base = len(task.split()) * 1.3
        
        if context:
            context_size = sum(len(str(v)) for v in context.values())
            base += context_size * 0.3
        
        return int(base)
    
    def _classify_task_type(self, task: str) -> str:
        """Classify task into high-level type."""
        if "localization" in task or "loc" in task:
            return "localization"
        if "validate" in task or "check" in task:
            return "validation"
        if "search" in task or "find" in task:
            return "search"
        if "read" in task or "get" in task:
            return "retrieval"
        if "template" in task or "fill" in task:
            return "template"
        if "batch" in task or "multiple" in task:
            return "batch"
        return "general"
    
    def _select_worker_type(self, task: str) -> WorkerType:
        """Select appropriate Haiku worker type."""
        if "template" in task or "fill" in task:
            return WorkerType.TEMPLATE_FILLER
        if "search" in task or "find" in task:
            return WorkerType.SEARCH_RUNNER
        if "validate" in task or "check" in task:
            return WorkerType.VALIDATOR_RUNNER
        if "localization" in task or "loc" in task:
            return WorkerType.LOC_GENERATOR
        if "read" in task or "get" in task:
            return WorkerType.FILE_READER
        if "batch" in task or "multiple" in task:
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
