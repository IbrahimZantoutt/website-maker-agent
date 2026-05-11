"""
Orchestrator — planner, spawn plan validation, phase execution.

Flow:
  1. Build file tree + create ProjectContext
  2. Git checkpoint
  3. LLM planner call → spawn plan
  4. Validate spawn plan (deterministic)
  5. User approval gate
  6. Phase: Analysts (if any)
  7. Phase: Execution agents (parallel)
  8. Delivery summary
"""
import json
import os
import re
import threading
from typing import Callable, Optional

import ollama

from config import MODEL, MAX_STEPS
from tools import build_file_tree
from context import ProjectContext
from event_bus import EventBus
from file_registry import FileRegistry
from checkpoint import create_checkpoint, rollback_to_checkpoint
from agent_runtime import AgentRuntime
from agents import AGENT_REGISTRY


# ── Planner Prompt ───────────────────────────────────────────────────────────

_SPAWNING_PROMPT = """You are the Planner of a multi-agent software development system.
You must decide which agents to spawn and how many.

AVAILABLE AGENT TYPES:
- code_analyst: Read-only analysis of existing codebase. Publishes findings.
- frontend: Reads and writes. UI, components, styling, state, routing.
- backend: Reads and writes. APIs, server logic, databases, auth, business logic.

TASK:
{task}

WORKING DIRECTORY: {cwd}

PROJECT FILE TREE:
{tree}

SPAWNING DECISION — reason through each question before producing JSON:

1. Source file count from tree: [count them]. If < 3, no analyst needed.
2. Does the task require UI/component/styling work? Yes/No → spawn or skip frontend.
3. Does the task require API/server/database work? Yes/No → spawn or skip backend.
4. Analyst instances: list each codebase subtree that benefits from parallel analysis.
   Each needs a directory path and a one-sentence analysis focus.
   Max 3.
5. Execution instances: for each type you're spawning, split work into parallel slices BY DOMAIN.
   Split rules:
   - Count the total unique files. If > 10 files for one type, split into 2-3 agents.
   - Split along natural domain boundaries, e.g.:
     * Frontend: (a) layout/global files + data/types, (b) page components, (c) section/UI components
     * Backend: (a) models/DB, (b) API routes, (c) services/auth
   - Shared utility/type files (e.g. types/index.ts, constants.ts) are fine to list in multiple
     agents — they are read once and rarely written. Do NOT merge agents just because they share
     a types file or a single config file.
   - Only merge two slices if they share 3+ files that BOTH agents would WRITE to simultaneously.
   - Each slice needs an id, a list of files it will likely touch, and a one-sentence task.
   - Max 3 per type.
   - PREFER MORE AGENTS over one giant agent. Parallelism is the goal.

Only after reasoning through all five questions produce the spawn_plan JSON.

OUTPUT: Respond with your reasoning THEN a JSON block in this exact format:
```json
{{
  "spawn_plan": {{
    "analyst_instances": [
      {{
        "id": "analyst_0",
        "directory": "src/",
        "focus": "One-sentence analysis focus",
        "likely_files": ["src/file1.py", "src/file2.py"]
      }}
    ],
    "frontend_instances": [
      {{
        "id": "frontend_0",
        "task": "Specific task description",
        "likely_files": ["src/pages/Home.tsx", "src/components/Nav.tsx"]
      }}
    ],
    "backend_instances": [
      {{
        "id": "backend_0",
        "task": "Specific task description",
        "likely_files": ["src/api/routes.py", "src/models.py"]
      }}
    ],
    "spawn_rationale": "2-3 sentences explaining the decisions"
  }}
}}
```

If a type is not needed, use an empty array [].
The JSON MUST be valid. Include the ```json fence markers."""


# ── Spawn Plan Validation ────────────────────────────────────────────────────

def _validate_spawn_plan(plan: dict, tree: str, cwd: str) -> dict:
    """
    Deterministic validation pass — no LLM. Fixes:
    1. File overlap between instances of same type
    2. Empty/vague task descriptions
    3. Unnecessary spawning (<3 files → single instance)
    4. Analyst directory sanity
    """
    sp = plan.get("spawn_plan", plan)

    # Check 1: File overlap detection per type
    # Only merge instances that share 3+ files — a single shared types/config file
    # is fine and should not collapse parallel agents into one.
    _MERGE_THRESHOLD = 3
    for key in ("frontend_instances", "backend_instances"):
        instances = sp.get(key, [])
        if len(instances) <= 1:
            continue

        # Count shared files between every pair
        file_sets = [
            {f.replace("\\", "/") for f in inst.get("likely_files", [])}
            for inst in instances
        ]
        pairs_to_merge = set()
        for i in range(len(instances)):
            for j in range(i + 1, len(instances)):
                shared = file_sets[i] & file_sets[j]
                if len(shared) >= _MERGE_THRESHOLD:
                    pairs_to_merge.add((i, j))

        if not pairs_to_merge:
            continue  # No significant overlap — keep all agents separate

        # Build merge groups via union-find
        parent = list(range(len(instances)))

        def _find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for i, j in pairs_to_merge:
            pi, pj = _find(i), _find(j)
            if pi != pj:
                parent[pi] = pj

        groups: dict = {}
        for idx in range(len(instances)):
            root = _find(idx)
            groups.setdefault(root, []).append(idx)

        merged_instances = []
        for root, idxs in groups.items():
            if len(idxs) == 1:
                merged_instances.append(instances[idxs[0]])
            else:
                base = instances[idxs[0]].copy()
                all_files: set = set()
                all_tasks = []
                for idx in idxs:
                    all_files.update(instances[idx].get("likely_files", []))
                    all_tasks.append(instances[idx].get("task", ""))
                base["likely_files"] = list(all_files)
                base["task"] = " AND ".join(t for t in all_tasks if t)
                merged_instances.append(base)
        sp[key] = merged_instances

    # Check 2: Empty task check
    for key in ("frontend_instances", "backend_instances"):
        instances = sp.get(key, [])
        sp[key] = [
            inst for inst in instances
            if inst.get("task", "").strip() and len(inst.get("task", "").split()) >= 3
        ]

    # Check 3: Unnecessary spawn check
    for key in ("frontend_instances", "backend_instances"):
        instances = sp.get(key, [])
        if len(instances) > 1:
            total_files = sum(len(inst.get("likely_files", [])) for inst in instances)
            if total_files < 3:
                # Merge to single instance
                merged = instances[0].copy()
                all_files = set()
                all_tasks = []
                for inst in instances:
                    all_files.update(inst.get("likely_files", []))
                    all_tasks.append(inst.get("task", ""))
                merged["likely_files"] = list(all_files)
                merged["task"] = " AND ".join(t for t in all_tasks if t)
                sp[key] = [merged]

    # Check 4: Analyst directory sanity
    analyst_instances = sp.get("analyst_instances", [])
    for inst in analyst_instances:
        d = inst.get("directory", ".")
        full = os.path.join(cwd, d)
        if not os.path.isdir(full):
            # Remap to closest existing parent
            parts = d.replace("\\", "/").split("/")
            while parts:
                candidate = os.path.join(cwd, *parts)
                if os.path.isdir(candidate):
                    inst["directory"] = "/".join(parts)
                    break
                parts.pop()
            else:
                inst["directory"] = "."

    # Re-number IDs to be sequential
    for key, prefix in [
        ("analyst_instances", "analyst"),
        ("frontend_instances", "frontend"),
        ("backend_instances", "backend"),
    ]:
        for i, inst in enumerate(sp.get(key, [])):
            inst["id"] = f"{prefix}_{i}"

    if "spawn_plan" not in plan:
        plan = {"spawn_plan": sp}
    else:
        plan["spawn_plan"] = sp

    return plan


# ── Plan Parsing ─────────────────────────────────────────────────────────────

def _parse_spawn_plan(response_text: str) -> dict:
    """Extract the spawn_plan JSON from the LLM response."""
    # Try to find JSON block in code fence
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", response_text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Try to find raw JSON object with spawn_plan key
    match = re.search(r'\{\s*"spawn_plan"\s*:', response_text, re.DOTALL)
    if match:
        # Find the matching closing brace
        start = match.start()
        depth = 0
        for i in range(start, len(response_text)):
            if response_text[i] == '{':
                depth += 1
            elif response_text[i] == '}':
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(response_text[start:i + 1])
                    except json.JSONDecodeError:
                        break

    return None


def _generate_summary(task: str, plan: dict, context: ProjectContext, model: str) -> str:
    """Single-shot LLM call for final delivery summary."""
    agent_outputs = context.get("agent_outputs", {})
    outputs_section = ""
    for aid, output in agent_outputs.items():
        outputs_section += f"\n\n--- {aid} OUTPUT ---\n{output}"

    prompt = f"""The multi-agent workflow has completed.

ORIGINAL TASK: {task}
AGENTS USED: {', '.join(agent_outputs.keys()) if agent_outputs else 'none'}

AGENT OUTPUTS:
{outputs_section.strip() if outputs_section else "No outputs."}

Write a concise delivery summary. Cover:
1. What was accomplished (specific files, endpoints, components)
2. Key decisions made
3. How to verify (run commands, test steps)
4. Warnings or follow-up needed

Keep it under 20 lines. Be direct."""

    try:
        resp = ollama.chat(model=model, messages=[{"role": "user", "content": prompt}])
        return resp.message.content if hasattr(resp, "message") else resp["message"]["content"]
    except Exception as e:
        return f"Task completed. Error generating summary: {e}"


# ── Main Orchestrator ────────────────────────────────────────────────────────

def run_orchestrator(
    task: str,
    model: str = MODEL,
    on_event: Optional[Callable] = None,
    plan_approval_fn: Optional[Callable] = None,
    project_path: Optional[str] = None,
    parallel_mode: bool = False,
) -> dict:
    """
    Main entry point. Returns {summary, checkpoint_hash, success}.
    """
    def emit(ev_type: str, **kwargs):
        if on_event:
            on_event({"type": ev_type, **kwargs})

    cwd = (project_path or os.getcwd()).replace("\\", "/")
    if not os.path.isdir(cwd):
        emit("error", text=f"Project path does not exist: {cwd}")
        return {"summary": "Error: invalid project path", "success": False}

    # ── Phase 0: Intake ──────────────────────────────────────────────────
    emit("phase_change", phase="intake", phase_name="Intake",
         description="Scanning project structure")

    tree = build_file_tree(cwd)
    emit("start", task=task, model=model)

    # ── Phase 1: Git Checkpoint ──────────────────────────────────────────
    emit("phase_change", phase="checkpoint", phase_name="Checkpoint",
         description="Creating git checkpoint for rollback")

    checkpoint_hash = create_checkpoint(cwd, task)
    if checkpoint_hash:
        emit("checkpoint_created", hash=checkpoint_hash)
    else:
        emit("checkpoint_skipped", reason="Git not available or not a git repo")

    # ── Phase 2: Planning ────────────────────────────────────────────────
    emit("phase_change", phase="planning", phase_name="Planning",
         description="Analyzing task and deciding which agents to spawn")

    sequential_constraint = (
        "\n\nSEQUENTIAL MODE ACTIVE: Spawn at most 1 instance per agent type "
        "(1 analyst, 1 frontend, 1 backend). Do NOT split work into multiple instances."
        if not parallel_mode else ""
    )
    prompt = _SPAWNING_PROMPT.format(task=task, cwd=cwd, tree=tree) + sequential_constraint

    try:
        resp = ollama.chat(model=model, messages=[{"role": "user", "content": prompt}])
        response_text = resp.message.content if hasattr(resp, "message") else resp["message"]["content"]
    except Exception as e:
        emit("error", text=f"Planner LLM call failed: {e}")
        return {"summary": f"Planner error: {e}", "success": False}

    emit("planner_reasoning", text=response_text)

    raw_plan = _parse_spawn_plan(response_text)
    if not raw_plan:
        # Fallback: single backend agent
        raw_plan = {
            "spawn_plan": {
                "analyst_instances": [],
                "frontend_instances": [],
                "backend_instances": [{
                    "id": "backend_0",
                    "task": task,
                    "likely_files": [],
                }],
                "spawn_rationale": "Fallback: could not parse planner output.",
            }
        }

    # Validate
    validated_plan = _validate_spawn_plan(raw_plan, tree, cwd)
    sp = validated_plan.get("spawn_plan", validated_plan)

    # Sequential mode: collapse to at most 1 agent per type
    if not parallel_mode:
        for key in ("analyst_instances", "frontend_instances", "backend_instances"):
            instances = sp.get(key, [])
            if len(instances) > 1:
                merged = instances[0].copy()
                all_files: set = set()
                all_tasks = []
                for inst in instances:
                    all_files.update(inst.get("likely_files", []))
                    all_tasks.append(inst.get("task", inst.get("focus", "")))
                merged["likely_files"] = list(all_files)
                task_key = "focus" if "focus" in instances[0] else "task"
                merged[task_key] = " AND ".join(t for t in all_tasks if t)
                sp[key] = [merged]

    emit("plan_ready", plan=sp)

    # ── User Approval Gate ───────────────────────────────────────────────
    if plan_approval_fn:
        approved = plan_approval_fn(sp)
        if not approved:
            emit("plan_rejected")
            return {"summary": "Plan rejected by user.", "success": False, "checkpoint_hash": checkpoint_hash}
        emit("plan_approved")
    else:
        emit("plan_approved")

    # ── Initialize shared infrastructure ─────────────────────────────────
    ctx = ProjectContext(task=task, cwd=cwd)
    ctx.update("plan", sp)

    bus = EventBus()
    registry = FileRegistry(bus)

    # Register UI callback on bus so events flow to SSE
    bus.register("_ui", lambda event: emit("bus_event", event=event))

    # Track all agent instances for peer awareness
    all_agents: dict = {}

    # Queues for user→agent messaging
    agent_queues: dict = {}

    # ── Phase 3: Analysis ────────────────────────────────────────────────
    analysts = sp.get("analyst_instances", [])
    if analysts:
        emit("phase_change", phase="analysis", phase_name="Analysis",
             description=f"Spawning {len(analysts)} analyst(s)")

        # Register analysts in all_agents
        for inst in analysts:
            aid = inst["id"]
            all_agents[aid] = {
                "type": "code_analyst",
                "task": inst.get("focus", ""),
                "likely_files": inst.get("likely_files", []),
                "status": "STARTING",
                "current_action": "",
            }

        # Run analysts (sequential — they're read-only so no conflicts, but
        # parallel is fine too for large codebases)
        for inst in analysts:
            aid = inst["id"]
            directory = inst.get("directory", ".")
            focus = inst.get("focus", "Analyze the codebase")
            analysis_task = (
                f"Analyze the codebase at directory: {os.path.join(cwd, directory)}\n"
                f"Focus: {focus}\n"
                f"Original user task: {task}"
            )

            runtime = AgentRuntime(
                instance_id=aid,
                agent_type="code_analyst",
                task=analysis_task,
                context_str=ctx.to_json(),
                model=model,
                bus=bus,
                registry=registry,
                all_agents=all_agents,
                on_event=on_event,
                likely_files=inst.get("likely_files", []),
            )
            agent_queues[aid] = runtime.user_message_queue

            output = runtime.run()
            ctx.record_agent_output(aid, output)

    # ── Phase 4: Execution ───────────────────────────────────────────────
    frontend_instances = sp.get("frontend_instances", [])
    backend_instances = sp.get("backend_instances", [])
    exec_instances = []

    for inst in frontend_instances:
        exec_instances.append(("frontend", inst))
    for inst in backend_instances:
        exec_instances.append(("backend", inst))

    if exec_instances:
        emit("phase_change", phase="execution", phase_name="Execution",
             description=f"Spawning {len(exec_instances)} execution agent(s)")

        # Register in all_agents
        for agent_type, inst in exec_instances:
            aid = inst["id"]
            all_agents[aid] = {
                "type": agent_type,
                "task": inst.get("task", ""),
                "likely_files": inst.get("likely_files", []),
                "status": "STARTING",
                "current_action": "",
            }

        # Build context string with analysis results
        context_str = ctx.to_json()

        # Run in parallel
        results = {}
        errors = {}
        lock = threading.Lock()

        def _run_exec(agent_type: str, inst: dict):
            aid = inst["id"]
            agent_task = (
                f"{inst.get('task', task)}\n\n"
                f"Original user task: {task}\n"
                f"Working directory: {cwd}"
            )

            runtime = AgentRuntime(
                instance_id=aid,
                agent_type=agent_type,
                task=agent_task,
                context_str=context_str,
                model=model,
                bus=bus,
                registry=registry,
                all_agents=all_agents,
                on_event=on_event,
                likely_files=inst.get("likely_files", []),
            )
            agent_queues[aid] = runtime.user_message_queue

            try:
                output = runtime.run()
                with lock:
                    results[aid] = output
            except Exception as e:
                with lock:
                    errors[aid] = str(e)
                emit("agent_error", agent=aid, error=str(e))

        if parallel_mode:
            threads = [
                threading.Thread(target=_run_exec, args=(at, inst), daemon=True)
                for at, inst in exec_instances
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=600)  # 10 min cap
        else:
            for at, inst in exec_instances:
                _run_exec(at, inst)

        for aid, output in results.items():
            ctx.record_agent_output(aid, output)

    # ── Phase 5: Delivery ────────────────────────────────────────────────
    emit("phase_change", phase="delivery", phase_name="Delivery",
         description="Generating final summary")

    ctx_dir = os.path.join(cwd, "project_context")
    ctx.save(ctx_dir)

    summary = _generate_summary(task, sp, ctx, model)
    emit("final", text=summary, checkpoint_hash=checkpoint_hash)

    # Cleanup
    bus.clear()

    return {
        "summary": summary,
        "checkpoint_hash": checkpoint_hash,
        "success": True,
        "agent_queues": agent_queues,
    }
