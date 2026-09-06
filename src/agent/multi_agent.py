"""Internal multi-agent planner and workers.

Jonathan Ai can split a goal across isolated worker chats. Workers share
the durable memory brief but not the parent thread. No other product
(Cursor, Codex, MCP) is required.
"""

from __future__ import annotations

import json
import re
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from src.agent.memory import build_memory_brief, remember_turn
from src.agent.session import empty_token_usage, merge_token_usage
from src.providers.base import BaseProvider, ChatResponse


MAX_WORKERS = 3
WORKER_MODES = {"fast": 2, "balanced": 3, "verified": 3}


def plan_subtasks(goal: str, *, max_workers: int = MAX_WORKERS) -> list[str]:
    """Split a goal into isolated worker prompts without calling the model."""
    text = " ".join(str(goal or "").split())
    if not text:
        return []
    numbered = re.findall(r"(?:^|\n)\s*(?:\d+[\).]|[-*])\s+(.+)", str(goal or ""))
    parts = [item.strip() for item in numbered if item.strip()]
    if not parts:
        chunks = [chunk.strip() for chunk in re.split(r"\s+(?:and then|then|;)\s+", text, flags=re.I) if chunk.strip()]
        parts = chunks if len(chunks) > 1 else [text]
    return parts[: max(1, min(max_workers, MAX_WORKERS))]


def _planner_subtasks(provider: BaseProvider, goal: str, *, max_workers: int) -> list[str]:
    heuristic = plan_subtasks(goal, max_workers=max_workers)
    if len(heuristic) > 1 or provider is None:
        return heuristic
    brief = build_memory_brief()
    system = (
        "You are Jonathan Ai's planner. Return ONLY JSON "
        '{"subtasks":["..."]} with 1-3 short worker prompts. '
        "Do not invent other products or agents.\n\n" + brief
    )
    try:
        response = provider.chat(
            [{"role": "user", "content": f"Split this work into isolated worker prompts:\n{goal}"}],
            tools=None,
            system=system,
        )
        text = response.content if isinstance(response, ChatResponse) else str(response)
        match = re.search(r"\{.*\}", text or "", flags=re.S)
        if not match:
            return heuristic
        data = json.loads(match.group(0))
        items = data.get("subtasks") if isinstance(data, dict) else None
        if isinstance(items, list):
            cleaned = [str(item).strip() for item in items if str(item).strip()]
            if cleaned:
                return cleaned[:max_workers]
    except Exception:
        return heuristic
    return heuristic


def _run_one_worker(
    *,
    provider: BaseProvider,
    parent_session_id: str,
    index: int,
    prompt: str,
) -> dict[str, Any]:
    worker_id = f"worker-{uuid.uuid4().hex[:8]}"
    brief = build_memory_brief(exclude_session_id=parent_session_id)
    system = (
        "You are a Jonathan Ai worker. Complete only your assigned subtask. "
        "Threads stay isolated. Use shared memory if relevant. "
        "Do not require Cursor, Codex, or MCP.\n\n" + brief
    )
    try:
        response = provider.chat(
            [{"role": "user", "content": prompt}],
            tools=None,
            system=system,
        )
        answer = (response.content if isinstance(response, ChatResponse) else str(response)) or ""
        usage = dict(response.usage or {}) if isinstance(response, ChatResponse) else {}
    except Exception as exc:
        answer = f"Worker failed: {exc}"
        usage = {}
    title = prompt.splitlines()[0][:72] or f"Worker {index + 1}"
    try:
        remember_turn(
            session_id=worker_id,
            title=title,
            user_text=prompt,
            assistant_text=answer,
        )
    except Exception:
        pass
    return {
        "worker_id": worker_id,
        "index": index,
        "title": title,
        "prompt": prompt,
        "answer": answer,
        "usage": usage,
    }


def run_internal_workers(
    *,
    provider: BaseProvider,
    goal: str,
    parent_session_id: str = "",
    max_workers: int = MAX_WORKERS,
    mode: str = "balanced",
) -> dict[str, Any]:
    """Plan subtasks and run isolated workers in parallel. No external agents."""
    if provider is None:
        raise ValueError("Connect a provider before running workers.")
    selected_mode = str(mode or "balanced").strip().lower()
    if selected_mode not in WORKER_MODES:
        raise ValueError(f"unknown worker mode: {mode}")
    worker_cap = min(max(1, int(max_workers)), WORKER_MODES[selected_mode], MAX_WORKERS)
    subtasks = _planner_subtasks(provider, goal, max_workers=worker_cap)
    if not subtasks:
        raise ValueError("Goal is empty.")
    results: list[dict[str, Any]] = [None] * len(subtasks)  # type: ignore[list-item]
    workers = min(len(subtasks), worker_cap)
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {
            pool.submit(
                _run_one_worker,
                provider=provider,
                parent_session_id=parent_session_id,
                index=idx,
                prompt=prompt,
            ): idx
            for idx, prompt in enumerate(subtasks)
        }
        for future in as_completed(futures):
            item = future.result()
            results[item["index"]] = item
    answers = [str(item.get("answer") or "") for item in results if item]
    combined = "\n\n".join(
        f"Worker {item['index'] + 1} — {item['title']}\n{item['answer']}"
        for item in results
        if item
    )
    usage = empty_token_usage()
    for item in results:
        if item:
            usage = merge_token_usage(usage, item.get("usage") or {})
    review = ""
    answer = answers[0] if len(answers) == 1 else combined
    if selected_mode == "verified":
        system = (
            "You are Jonathan Ai's independent final verifier. You did not author the worker outputs. "
            "Check them against the original goal, identify conflicts or missing evidence, and return a concise "
            "corrected final answer. Never claim checks you did not perform."
        )
        try:
            response = provider.chat(
                [{"role": "user", "content": f"Goal:\n{goal}\n\nWorker outputs:\n{combined}"}],
                tools=None,
                system=system,
            )
            review = (response.content if isinstance(response, ChatResponse) else str(response)) or ""
            if review:
                answer = review
            if isinstance(response, ChatResponse):
                usage = merge_token_usage(usage, response.usage or {})
        except Exception as exc:
            review = f"Independent verification failed; returning worker evidence unchanged: {exc}"
    return {
        "ok": True,
        "goal": goal,
        "mode": selected_mode,
        "workers": results,
        "combined": combined,
        "review": review,
        "answer": answer,
        "usage": usage,
    }
