# Website Maker Agent

A production-grade multi-agent system for building complete websites end-to-end. An evolution of a standard multi-agent setup — this version adds checkpoint recovery, an event bus for agent coordination, and a file registry to track every generated artifact and its dependencies.

Runs locally using [Ollama](https://ollama.com).

---

## What Makes This Different

Standard multi-agent systems fail silently — if something goes wrong mid-run, you start from scratch. This system is built to be resilient:

**Checkpoint System**
Every phase of execution is checkpointed. If a run fails or is interrupted, it resumes from the last successful checkpoint rather than restarting from the beginning.

**Event Bus**
Agents communicate through a publish-subscribe event bus instead of direct calls. This decouples agents from each other — an agent publishes what it produced, and any agent that needs it can subscribe. Makes the system easier to extend and debug.

**File Registry**
Every file the system generates is registered with its dependencies tracked. The registry knows which files depend on which, so updates can be propagated correctly across the project.

**Agent Runtime**
Each agent runs inside a lifecycle-managed runtime with execution metrics, error recovery hooks, and structured logging.

---

## Included Agents

| Agent | Responsibilities |
|---|---|
| **Backend** | Express/Node.js server, APIs, database setup |
| **Frontend** | React/TypeScript components, routing, state |
| **Code Analyst** | Code review, quality checks, consistency validation |

The `Multi Agent No Pencil/` subfolder contains the full 10-agent suite from the base system, adapted to run without the Pencil design tool dependency.

---

## Tech Stack

- **LLM:** Ollama (local)
- **Backend:** Python, FastAPI
- **Frontend:** HTML + vanilla JS, Server-Sent Events (SSE)
- **Architecture:** Event-driven multi-agent with checkpoint persistence

---

## Getting Started

### Prerequisites
- Python 3.10+
- [Ollama](https://ollama.com) installed and running

```bash
ollama pull qwen2.5-coder:7b
```

### Setup

```bash
git clone https://github.com/IbrahimZantoutt/website-maker-agent.git
cd website-maker-agent
pip install -r requirements.txt
```

### Run

```bash
python main.py
```

Open [http://localhost:8000](http://localhost:8000) and describe the website you want to build.

---

## Project Structure

```
├── main.py              # Entry point
├── orchestrator.py      # Orchestration logic
├── agent_runtime.py     # Agent lifecycle, metrics, error recovery
├── checkpoint.py        # Save and resume execution state
├── event_bus.py         # Publish-subscribe agent communication
├── file_registry.py     # Generated file tracking and dependency management
├── context.py           # Shared project state
├── config.py            # Model and path configuration
├── tools.py             # Shared tool implementations
├── ui.py                # FastAPI server and frontend
└── agents/
    ├── backend.py
    ├── frontend.py
    └── code_analyst.py
```
