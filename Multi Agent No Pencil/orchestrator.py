"""
Orchestrator — command center of the multi-agent system.

Responsibilities:
1. Receive the task and build a structured Execution Plan via a single LLM call
2. Present the plan to the user and BLOCK until they approve or reject it
3. Execute the plan by invoking specialist agents phase by phase
4. Handle parallel execution for phases marked parallel=true
5. Maintain the ProjectContext throughout execution
6. Generate and deliver the final summary
"""
import json
import os
import re
import threading
from typing import Callable, Optional

import ollama

from tools import MODEL, MAX_STEPS, build_file_tree
from context import ProjectContext
from agents import AGENT_REGISTRY, run_specialist_agent

# ── Available agent info (for the planning prompt) ────────────────────────────

_AGENT_DESCRIPTIONS = "\n".join(
    f'  "{aid}": {spec["description"]}'
    for aid, spec in AGENT_REGISTRY.items()
)

_TASK_TYPES = (
    "greenfield | feature_addition | bug_fix | ui_modernization | "
    "legacy_modernization | api_development | database_migration | "
    "performance_optimization | security_audit | cicd_setup | "
    "third_party_integration | data_pipeline | cli_tool | query | other"
)

# ── Discovery Phase ───────────────────────────────────────────────────────────

def _create_discovery_questions(task: str, tree: str, model: str, on_event=None) -> list:
    """
    Pre-planning discovery: analyze the task and file tree to identify genuine ambiguities.
    Returns a list of question dicts, or an empty list if no questions are needed.
    The LLM decides how many questions are needed — no artificial cap.
    """
    def emit(ev_type, **kwargs):
        if on_event:
            on_event({"type": ev_type, **kwargs})

    prompt = f"""You are the Planning Intelligence of a multi-agent software development system.

A user has submitted this task:

TASK: {task}

PROJECT FILE TREE:
{tree}

YOUR JOB: Before creating an execution plan, identify any genuine information gaps or ambiguities
that would significantly affect HOW the plan is built. Generate targeted questions to resolve them.

CRITICAL RULES:
1. READ THE FILE TREE CAREFULLY first. If the project already uses specific tech (Firebase,
   PostgreSQL, Vercel, React, Express, etc.) DO NOT ask about that tech — respect existing choices.
2. Only ask about things that are GENUINELY AMBIGUOUS from the task description + file tree.
3. Do NOT ask questions whose answers are already stated in the task description.
4. Do NOT ask questions whose answers are obvious from the file tree context (language, framework, DB).
5. Do NOT propose changing the user's existing stack/setup unless they explicitly asked to change it.
   If you detect a genuine issue with the current stack, you may suggest an alternative as ONE of
   the choices, but always include "Keep existing (current)" as the first/default option.
6. Ask as many questions as genuinely needed to get a perfect plan — no artificial limit.
7. If the task is completely clear with no ambiguity (e.g. "fix typo on line 5", "add a comment to
   function X", "rename variable Y", simple self-contained bug fixes), return an empty array [].
8. For query/explain tasks ("explain", "what is", "how does", "describe", "why", "show me"),
   ALWAYS return [].

QUESTION CATEGORIES (use these exact strings as the category value):
- SCOPE:       Task boundaries unclear — what exactly is in or out of scope?
- TECH:        Only for genuinely undecided tech choices NOT determinable from the file tree
- QUALITY:     Testing depth, coverage targets, documentation requirements for significant changes
- SECURITY:    Auth strategy, permissions model for new features that need access control
- PERFORMANCE: Speed/scale targets for new endpoints, large queries, or high-traffic paths
- DEPLOYMENT:  Target environment, CI/CD — only for greenfield or infrastructure tasks
- STYLE:       Code conventions/patterns — only when starting fresh or codebase has mixed styles

FOR EACH QUESTION:
- Be specific to THIS task and THIS codebase (mention actual file names/frameworks when relevant)
- First choice should be the recommended or current option (mark with "(recommended)" or "(current)")
- Include a brief impact statement: one sentence on how the answer changes the execution plan

OUTPUT: Respond with ONLY a valid JSON array (possibly empty). No prose, no markdown, no code fences:
[
  {{
    "id": "unique_snake_case_id",
    "question": "Specific question ending with a question mark?",
    "category": "SCOPE|TECH|QUALITY|SECURITY|PERFORMANCE|DEPLOYMENT|STYLE",
    "choices": ["First choice (recommended)", "Second choice", "Third choice"],
    "default": "First choice (recommended)",
    "impact": "One sentence: how this answer changes the execution plan"
  }}
]

If no questions are needed, return exactly: []"""

    try:
        resp = ollama.chat(model=model, messages=[{"role": "user", "content": prompt}])
        content = (
            resp.message.content if hasattr(resp, "message")
            else resp["message"]["content"]
        )
        content = re.sub(r"```(?:json)?\s*", "", content).strip().rstrip("`").strip()

        # Extract JSON array (handles both [] and [...])
        match = re.search(r"\[.*\]", content, re.DOTALL)
        if match:
            questions = json.loads(match.group())
            if isinstance(questions, list):
                return questions
    except Exception as e:
        emit("orchestrator_thinking", text=f"Discovery phase skipped: {e}")

    return []


# ── Plan Creation ─────────────────────────────────────────────────────────────

def create_execution_plan(
    task: str,
    cwd: str,
    tree: str,
    model: str,
    on_event=None,
    user_answers: dict = None,
) -> dict:
    """
    Single-shot LLM call that produces a structured JSON execution plan.
    Not an agentic loop — one prompt, one response, parse the JSON.
    Falls back to a sensible default plan if parsing fails.
    Incorporates user_answers from the discovery phase when provided.
    """
    def emit(ev_type, **kwargs):
        if on_event:
            on_event({"type": ev_type, **kwargs})

    emit("orchestrator_thinking", text="Analyzing task and building execution plan\u2026")

    # Build user requirements section from discovery answers
    answers_block = ""
    if user_answers:
        answers_block = "\n\nUSER REQUIREMENTS (captured before planning — incorporate these precisely):\n"
        for q, a in user_answers.items():
            answers_block += f"  \u2022 {q}\n    \u2192 User chose: {a}\n"
        answers_block += "\nUse these answers to make specific, concrete decisions in the plan. They override defaults.\n"

    prompt = f"""You are the Orchestrator of a multi-agent software development system.
Analyze the task below and produce a precise execution plan.

TASK:
{task}

WORKING DIRECTORY: {cwd}

PROJECT FILE TREE:
{tree}{answers_block}

AVAILABLE SPECIALIST AGENTS:
{_AGENT_DESCRIPTIONS}

TASK TYPES: {_TASK_TYPES}

ROUTING RULES:
- Query / question (explain, describe, "what is", "how does", "why"): set task_type="query", phases=[], complexity="simple". NO agents needed — the orchestrator will answer directly.
- Greenfield: skip analysis agents. Use Architect -> execution agents -> QA -> Security.
- Bug fix: Code Analyst -> relevant execution agent -> QA. Security only if bug is security-related.
- Existing codebase with new feature: Code Analyst -> Architect -> execution agents -> QA -> Security.
- Legacy system: Legacy Analyst + Code Analyst (parallel) -> Architect -> all needed execution agents -> QA -> Security.
- Only include agents that are genuinely needed for THIS specific task.
- Execution agents (frontend, backend, integration, devops) can run in parallel if their work is independent.
- QA and Security always run after execution, and can run in parallel with each other.

OUTPUT: Respond with ONLY valid JSON matching this exact schema. No prose, no markdown, just JSON:
{{
  "task_summary": "One clear sentence describing what will be done",
  "task_type": "<one of the task types above>",
  "tech_detected": "Tech stack visible from the file tree (or 'greenfield' if no existing code)",
  "complexity": "simple | medium | complex",
  "risk_level": "low | medium | high",
  "key_files": ["files likely to be created or modified — infer from file tree and task"],
  "assumptions": ["Assumption 1 made from file tree or user answers", "Assumption 2"],
  "out_of_scope": ["Thing that will NOT be done in this task", "Another exclusion if applicable"],
  "phases": [
    {{
      "id": "phase_id",
      "name": "Human-readable phase name",
      "description": "What this phase accomplishes",
      "agents": [
        {{
          "id": "agent_id",
          "task": "Specific, actionable instruction for this agent. Be precise. Reference user choices where relevant."
        }}
      ],
      "parallel": false
    }}
  ],
  "rationale": "2-3 sentences explaining agent choices and how user requirements shaped this plan"
}}
"""

    try:
        resp = ollama.chat(model=model, messages=[{"role": "user", "content": prompt}])
        content = (
            resp.message.content if hasattr(resp, "message")
            else resp["message"]["content"]
        )

        # Strip markdown fences if the model wrapped the JSON
        content = re.sub(r"```(?:json)?\s*", "", content).strip().rstrip("`").strip()

        # Extract JSON object
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            plan = json.loads(match.group())
            emit("orchestrator_thinking", text="Execution plan ready.")
            return plan

    except Exception as e:
        emit("orchestrator_thinking", text=f"Plan parsing error: {e}. Using fallback plan.")

    # Fallback: minimal viable plan
    return {
        "task_summary": task[:120],
        "task_type": "other",
        "tech_detected": "unknown",
        "complexity": "medium",
        "risk_level": "medium",
        "key_files": [],
        "assumptions": [],
        "out_of_scope": [],
        "phases": [
            {
                "id": "analysis",
                "name": "Analysis",
                "description": "Analyze the existing codebase",
                "agents": [{"id": "code_analyst", "task": f"Analyze the codebase for this task: {task}"}],
                "parallel": False,
            },
            {
                "id": "execution",
                "name": "Execution",
                "description": "Implement the required changes",
                "agents": [{"id": "backend", "task": task}],
                "parallel": False,
            },
            {
                "id": "validation",
                "name": "Validation",
                "description": "Test and validate the changes",
                "agents": [
                    {"id": "qa_testing", "task": "Write and run tests for all changes"},
                    {"id": "security",   "task": "Audit all changes for security vulnerabilities"},
                ],
                "parallel": True,
            },
        ],
        "rationale": "Fallback plan: analysis -> execution -> validation.",
    }


# ── Final Summary ─────────────────────────────────────────────────────────────

def _generate_summary(task: str, plan: dict, context: ProjectContext, model: str) -> str:
    """Single-shot LLM call to produce the delivery summary."""
    agent_outputs = context.get("agent_outputs", {})
    agents_used = list(agent_outputs.keys())
    agent_names = [AGENT_REGISTRY.get(a, {}).get("name", a) for a in agents_used]

    # Build the full agent outputs section so the LLM knows exactly what was done
    outputs_section = ""
    for aid, output in agent_outputs.items():
        name = AGENT_REGISTRY.get(aid, {}).get("name", aid)
        outputs_section += f"\n\n--- {name} OUTPUT ---\n{output}"

    prompt = f"""You are the Orchestrator. The multi-agent workflow has completed.

ORIGINAL TASK: {task}
TASK TYPE: {plan.get('task_type', 'unknown')}
AGENTS THAT WORKED: {', '.join(agent_names) if agent_names else 'none'}

AGENT OUTPUTS:
{outputs_section.strip() if outputs_section else "No agent outputs recorded."}

Write a concise, professional delivery summary. Cover:
1. What was accomplished (be specific — name files, endpoints, components changed)
2. Key decisions made during execution
3. How to verify the changes (run command, open URL, test steps)
4. Any warnings, known limitations, or follow-up actions needed

Keep it under 20 lines. Be direct and specific. No fluff."""

    try:
        resp = ollama.chat(model=model, messages=[{"role": "user", "content": prompt}])
        return (
            resp.message.content if hasattr(resp, "message")
            else resp["message"]["content"]
        )
    except Exception as e:
        return f"Task completed. Agents used: {', '.join(agent_names)}. Error generating summary: {e}"


# ── Direct Query Answer ───────────────────────────────────────────────────────

def _answer_query(task: str, cwd: str, tree: str, model: str) -> str:
    """Single-shot LLM answer for questions that need no code changes."""
    extras = []
    for fname in ["README.md", "README.txt", "readme.md",
                  "package.json", "pyproject.toml", "requirements.txt"]:
        fpath = os.path.join(cwd, fname)
        if os.path.exists(fpath):
            try:
                with open(fpath, encoding="utf-8") as f:
                    extras.append(f"=== {fname} ===\n{f.read(2000)}")
            except Exception:
                pass

    context = f"FILE TREE:\n{tree}"
    if extras:
        context += "\n\n" + "\n\n".join(extras)

    prompt = (
        f"You are a helpful software development assistant.\n\n"
        f"QUESTION: {task}\n\n"
        f"PROJECT CONTEXT:\n{context}\n\n"
        f"Answer directly and concisely. Be specific about what you find."
    )
    try:
        resp = ollama.chat(model=model, messages=[{"role": "user", "content": prompt}])
        return resp.message.content if hasattr(resp, "message") else resp["message"]["content"]
    except Exception as e:
        return f"[Error generating answer: {e}]"


# ── Main Orchestrator ─────────────────────────────────────────────────────────

def run_orchestrator(
    task: str,
    model: str = MODEL,
    max_steps: int = MAX_STEPS,
    on_event=None,
    plan_approval_fn: Optional[Callable] = None,
    edit_approval_fn: Optional[Callable] = None,
    ask_user_fn: Optional[Callable] = None,
    project_path: Optional[str] = None,
) -> str:
    """
    Main orchestration entry point. Runs in a worker thread (called from ui.py).

    Flow:
      Intake -> Plan -> [USER APPROVAL GATE] -> Execute phases -> Delivery
    """
    def emit(ev_type: str, **kwargs):
        if on_event:
            on_event({"type": ev_type, **kwargs})

    # ── Phase 0: Intake & Triage ───────────────────────────────────────────────
    emit("phase_change", phase="intake", phase_name="Intake & Triage",
         description="Analyzing the task and project structure")

    cwd = (project_path if project_path else os.getcwd()).replace("\\", "/")
    tree = build_file_tree(cwd)

    emit("start", task=task, model=model)

    # ── Phase 0.5: Discovery & Requirements ───────────────────────────────────
    # Before planning, identify genuine ambiguities and ask the user to resolve them.
    # The LLM decides how many questions are needed (0 for clear/simple tasks).
    user_answers: dict = {}
    if ask_user_fn:
        emit("phase_change", phase="discovery", phase_name="Discovery",
             description="Identifying requirements and ambiguities before planning")
        emit("orchestrator_thinking", text="Scanning task for ambiguities before planning\u2026")
        questions = _create_discovery_questions(task, tree, model, on_event)
        total = len(questions)
        if total > 0:
            emit("orchestrator_thinking",
                 text=f"Found {total} question{'s' if total != 1 else ''} to clarify. "
                      "Let me ask before building the plan.")
            for idx, q in enumerate(questions):
                answer = ask_user_fn(
                    q["question"],
                    q.get("choices", []),
                    is_planning=True,
                    category=q.get("category", ""),
                    impact=q.get("impact", ""),
                    question_index=idx + 1,
                    question_total=total,
                )
                user_answers[q["question"]] = answer
            emit("orchestrator_thinking",
                 text="All requirements captured. Building optimised execution plan\u2026")
        else:
            emit("orchestrator_thinking", text="Task is clear. Building execution plan\u2026")

    # ── Phase 1: Create Execution Plan ────────────────────────────────────────
    plan = create_execution_plan(task, cwd, tree, model, on_event, user_answers or None)

    # Attach user answers to plan so the UI can show them in the approval modal
    if user_answers:
        plan["user_answers"] = user_answers

    # ── USER APPROVAL GATE ────────────────────────────────────────────────────
    # Queries need no approval — no code changes, just answer directly.
    if plan.get("task_type") == "query":
        emit("plan_approved")
    else:
        emit("plan_ready", plan=plan)
        if plan_approval_fn:
            approved = plan_approval_fn(plan)
            if not approved:
                emit("plan_rejected")
                return "Plan rejected by user. Modify your task and try again."
            emit("plan_approved")
        else:
            # No approval function = auto-approve (CLI mode)
            emit("plan_approved")

    # ── Fast path: direct answer for query tasks ──────────────────────────────
    if plan.get("task_type") == "query":
        emit("phase_change", phase="delivery", phase_name="Answering",
             description="Generating direct answer from project context")
        answer = _answer_query(task, cwd, tree, model)
        emit("final", text=answer)
        return answer

    # ── Initialize ProjectContext ──────────────────────────────────────────────
    ctx = ProjectContext(task=task, cwd=cwd)
    ctx.update("task_type",     plan.get("task_type", ""))
    ctx.update("tech_detected", plan.get("tech_detected", ""))
    ctx.update("plan",          plan)
    if user_answers:
        ctx.update("user_answers", user_answers)

    ctx_dir = os.path.join(cwd, "project_context")
    ctx.save(ctx_dir)

    # ── Execute Phases ─────────────────────────────────────────────────────────
    phases = plan.get("phases", [])

    for phase in phases:
        phase_id   = phase.get("id",   "phase")
        phase_name = phase.get("name", phase_id)
        phase_desc = phase.get("description", "")
        agents     = phase.get("agents", [])
        is_parallel = phase.get("parallel", False)

        emit("phase_change",
             phase=phase_id, phase_name=phase_name, description=phase_desc)

        # Rebuild context string before each phase so agents see cumulative output
        context_str = ctx.to_json()

        if is_parallel and len(agents) > 1:
            # ── Parallel execution ─────────────────────────────────────────────
            results: dict = {}
            errors:  dict = {}
            lock = threading.Lock()

            def _run_agent(agent_info, _results=results, _errors=errors, _lock=lock):
                aid   = agent_info["id"]
                atask = agent_info.get("task", task)
                try:
                    out = run_specialist_agent(
                        aid, atask, context_str, model, max_steps,
                        on_event, edit_approval_fn, ask_user_fn,
                    )
                    with _lock:
                        _results[aid] = out
                except Exception as e:
                    with _lock:
                        _errors[aid] = str(e)
                    emit("agent_error", agent=aid,
                         agent_name=AGENT_REGISTRY.get(aid, {}).get("name", aid),
                         error=str(e))

            threads = [
                threading.Thread(target=_run_agent, args=(ai,), daemon=True)
                for ai in agents
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=300)  # 5-minute cap per parallel phase; daemon threads exit with process

            for aid, out in results.items():
                ctx.record_agent_output(aid, out)

        else:
            # ── Sequential execution ───────────────────────────────────────────
            for agent_info in agents:
                aid   = agent_info["id"]
                atask = agent_info.get("task", task)
                try:
                    out = run_specialist_agent(
                        aid, atask, context_str, model, max_steps,
                        on_event, edit_approval_fn, ask_user_fn,
                    )
                    ctx.record_agent_output(aid, out)
                    # Update context so next agent sees this agent's output
                    context_str = ctx.to_json()
                except Exception as e:
                    emit("agent_error",
                         agent=aid,
                         agent_name=AGENT_REGISTRY.get(aid, {}).get("name", aid),
                         error=str(e))

        # Persist context after each phase
        ctx.save(ctx_dir)

    # ── Delivery ───────────────────────────────────────────────────────────────
    emit("phase_change", phase="delivery", phase_name="Delivery",
         description="Synthesizing results and preparing final summary")

    summary = _generate_summary(task, plan, ctx, model)
    emit("final", text=summary)
    return summary
