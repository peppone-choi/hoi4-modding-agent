"""
Haiku worker orchestration for cost-optimized task execution.
Fan-out/Fan-in pattern with quality gates.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum
from typing import Any


class WorkerType(Enum):
    TEMPLATE_FILLER = "template-filler"
    SEARCH_RUNNER = "search-runner"
    VALIDATOR_RUNNER = "validator-runner"
    LOC_GENERATOR = "loc-generator"
    FILE_READER = "file-reader"
    BATCH_ITERATOR = "batch-iterator"


@dataclass
class WorkerTask:
    worker_type: WorkerType
    input_data: dict[str, Any]
    quality_gate: int


@dataclass
class WorkerResult:
    task: WorkerTask
    output: Any
    success: bool
    error: str | None = None


class HaikuOrchestrator:
    """Orchestrates Haiku worker dispatch and result aggregation."""
    
    def __init__(self, anthropic_client, haiku_model: str = "claude-3-haiku-20240307"):
        self.client = anthropic_client
        self.haiku_model = haiku_model
    
    async def dispatch_worker(self, task: WorkerTask, retry: bool = False) -> WorkerResult:
        """Dispatch single Haiku worker task."""
        try:
            prompt = self._build_worker_prompt(task)
            
            if retry:
                prompt = f"{prompt}\n\nIMPORTANT: Previous attempt failed. Try a different approach."
            
            response = await asyncio.to_thread(
                self.client.messages.create,
                model=self.haiku_model,
                max_tokens=2048,
                temperature=0.3 if retry else 0,
                messages=[{"role": "user", "content": prompt}],
            )
            
            output = response.content[0].text
            
            return WorkerResult(
                task=task,
                output=output,
                success=True,
            )
        except Exception as e:
            return WorkerResult(
                task=task,
                output=None,
                success=False,
                error=str(e),
            )
    
    async def dispatch_with_progressive_retry(self, task: WorkerTask, max_parallel: int = 10) -> WorkerResult:
        """Dispatch Haiku workers with progressive parallelism until success or exhaustion."""
        parallel_counts = [1, 2, 4, 8]
        if max_parallel > 8:
            parallel_counts.append(max_parallel)
        
        last_results = []
        for batch_size in parallel_counts:
            tasks = [self.dispatch_worker(task, retry=True) for _ in range(batch_size)]
            results = await asyncio.gather(*tasks)
            last_results = results
            
            successful = [r for r in results if r.success]
            if successful:
                return successful[0]
        
        return last_results[0] if last_results else WorkerResult(task, None, False, "No attempts made")
    
    async def fan_out(self, tasks: list[WorkerTask]) -> list[WorkerResult]:
        """Fan-out: Execute multiple Haiku tasks in parallel."""
        return await asyncio.gather(*[self.dispatch_worker(task) for task in tasks])
    
    def fan_in(self, results: list[WorkerResult]) -> dict[str, Any]:
        """Fan-in: Aggregate worker results."""
        successful = [r for r in results if r.success]
        failed = [r for r in results if not r.success]
        
        return {
            "total": len(results),
            "successful": len(successful),
            "failed": len(failed),
            "outputs": [r.output for r in successful],
            "errors": [{"task": r.task.worker_type.value, "error": r.error} for r in failed],
        }
    
    def _build_worker_prompt(self, task: WorkerTask) -> str:
        """Build specialized prompt for each worker type."""
        worker_prompts = {
            WorkerType.TEMPLATE_FILLER: self._prompt_template_filler,
            WorkerType.SEARCH_RUNNER: self._prompt_search_runner,
            WorkerType.VALIDATOR_RUNNER: self._prompt_validator_runner,
            WorkerType.LOC_GENERATOR: self._prompt_loc_generator,
            WorkerType.FILE_READER: self._prompt_file_reader,
            WorkerType.BATCH_ITERATOR: self._prompt_batch_iterator,
        }
        
        builder = worker_prompts.get(task.worker_type)
        if not builder:
            raise ValueError(f"Unknown worker type: {task.worker_type}")
        
        return builder(task.input_data)
    
    def _prompt_template_filler(self, data: dict) -> str:
        return f"""Fill this template with the provided data.

Template:
{data['template']}

Data:
{data['data']}

Validation Rules:
{data.get('validation_rules', 'None')}

Output only the filled template, no explanation."""
    
    def _prompt_search_runner(self, data: dict) -> str:
        return f"""Execute search query and return structured results.

Search Type: {data['search_type']}
Query: {data['query']}
Filters: {data.get('filters', {})}

Return JSON array of results with locations."""
    
    def _prompt_validator_runner(self, data: dict) -> str:
        return f"""Validate content against schema and rules.

Content:
{data['content']}

File Type: {data['file_type']}
Validation Level: {data['validation_level']}

Return validation report with errors/warnings."""
    
    def _prompt_loc_generator(self, data: dict) -> str:
        return f"""Generate localization file content.

Base Key: {data['base_key']}
Translations: {data['translations']}
Format: {data['format']}

Output formatted localization content."""
    
    def _prompt_file_reader(self, data: dict) -> str:
        return f"""Read file with intelligent processing.

Path: {data['path']}
Mode: {data['mode']}
Search Pattern: {data.get('search_pattern', 'N/A')}
Max Lines: {data.get('max_lines', 2000)}

Output file content or summary based on mode."""
    
    def _prompt_batch_iterator(self, data: dict) -> str:
        return f"""Process list of items with consistent transforms.

Items: {data['items']}
Operation: {data['operation']}
Template: {data.get('template', 'N/A')}

Return array of processed results."""


async def execute_sonnet_parallel(
    client,
    model: str,
    system_prompt: str | list,
    tools: list,
    messages: list,
    max_tokens: int,
    count: int,
) -> Any:
    """Execute Sonnet calls in parallel, return first success.
    
    Args:
        client: Anthropic client
        model: Sonnet model name
        system_prompt: System prompt
        tools: Tool definitions
        messages: Message history
        max_tokens: Max tokens
        count: Number of parallel calls
    
    Returns:
        First successful response
    
    Raises:
        Exception: If all parallel calls fail
    """
    async def _call_once():
        return await asyncio.to_thread(
            client.messages.create,
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            tools=tools,
            messages=messages,
        )
    
    tasks = [_call_once() for _ in range(count)]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    for result in results:
        if not isinstance(result, Exception):
            return result
    
    # All failed - raise first exception
    raise results[0]


def create_orchestrator(anthropic_client) -> HaikuOrchestrator:
    """Factory function to create Haiku orchestrator."""
    return HaikuOrchestrator(anthropic_client)
