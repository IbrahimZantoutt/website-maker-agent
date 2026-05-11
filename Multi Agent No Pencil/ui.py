"""
Multi-Agent Dev System — Web UI

FastAPI + SSE streaming, same dark terminal aesthetic as the single-agent UI,
enhanced with:
  - Phase progress breadcrumb
  - Agent status sidebar (all 9 agents with live status)
  - Full-screen plan approval modal
  - Per-agent color-coded output in the stream
"""
import asyncio
import json
import os
import queue
import threading

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
import uvicorn

from tools import MODEL, MODELS
from agents import AGENT_REGISTRY
from orchestrator import run_orchestrator

app = FastAPI()

# ── Session state (single-user local tool) ────────────────────────────────────
# Per-request queues — replaced on each new stream connection.
# Queue.get() blocks until the matching endpoint puts a result, eliminating
# the stale-event bugs that plagued the threading.Event approach.
_active_plan_appr_q: list = [None]
_active_edit_appr_q: list = [None]
_active_ask_q:       list = [None]


# ── Build the HTML page ───────────────────────────────────────────────────────

def _build_html() -> str:
    model_opts = "\n".join(
        f'<option value="{m}"{"selected" if m == MODEL else ""}>{m}</option>'
        for m in MODELS
    )

    # Agent specs for JS (icon + name + color)
    agent_specs_js = json.dumps({
        aid: {"name": spec["name"], "icon": spec["icon"], "color": spec["color"]}
        for aid, spec in AGENT_REGISTRY.items()
    })

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Multi-Agent Dev System</title>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
:root{{
  --bg:#040d12;--surface:#071520;--surface2:#0a1f2e;--border:#0d3040;
  --text:#9ee8cc;--muted:#3a7a68;
  --accent:#00e5b0;--accent2:#00c896;--accent-glow:rgba(0,229,176,0.18);
  --green:#2dff7a;--red:#ff4455;--yellow:#ffcc44;
  --cyan:#00e8ff;--purple:#b066ff;--orange:#ff8844;
  --teal:#00e5b0;--rose:#ff5577;--pink:#ff8899;
  --glow-sm:0 0 8px rgba(0,229,176,0.4);
  --glow-md:0 0 16px rgba(0,229,176,0.35);
  --glow-lg:0 0 28px rgba(0,229,176,0.3);
}}
body{{background:var(--bg);color:var(--text);font-family:'Cascadia Code','Fira Code',Consolas,monospace;font-size:13px;height:100vh;display:flex;flex-direction:column;overflow:hidden}}

/* ─ Scrollbars ─ */
::-webkit-scrollbar{{width:4px;height:4px}}
::-webkit-scrollbar-track{{background:transparent}}
::-webkit-scrollbar-thumb{{background:var(--border);border-radius:2px}}
::-webkit-scrollbar-thumb:hover{{background:var(--muted)}}

/* ─ Header ─ */
header{{background:linear-gradient(180deg,#071b28 0%,#040d12 100%);border-bottom:1px solid var(--border);padding:8px 18px;display:flex;align-items:center;gap:12px;flex-shrink:0;box-shadow:0 1px 16px rgba(0,0,0,0.6)}}
header h1{{font-size:14px;letter-spacing:2px;margin-right:auto;background:linear-gradient(90deg,var(--accent),var(--cyan));-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;filter:drop-shadow(0 0 6px rgba(0,229,176,0.5))}}
header .h-sep{{color:var(--border);user-select:none}}
header label{{color:var(--muted);font-size:11px;letter-spacing:.3px}}
select{{background:var(--surface2);color:var(--text);border:1px solid var(--border);border-radius:4px;padding:4px 8px;font-family:inherit;font-size:12px;cursor:pointer;transition:border-color .2s}}
select:focus{{outline:none;border-color:var(--accent);box-shadow:var(--glow-sm)}}
.badge{{background:var(--surface2);border:1px solid var(--border);border-radius:20px;padding:3px 12px;font-size:11px;color:var(--muted);letter-spacing:.3px;transition:all .3s}}

/* ─ Layout ─ */
.layout{{display:flex;flex:1;overflow:hidden}}

/* ─ Sidebar ─ */
.sidebar{{width:240px;background:linear-gradient(180deg,#071a26 0%,#040e16 100%);border-right:1px solid var(--border);display:flex;flex-direction:column;gap:0;padding:0;flex-shrink:0;overflow:hidden;backdrop-filter:blur(4px);transition:width .22s ease}}
.sidebar.collapsed{{width:30px;min-width:30px}}
.sidebar-toggle-btn{{background:transparent;border:none;color:var(--muted);cursor:pointer;font-size:13px;padding:8px;width:100%;text-align:right;flex-shrink:0;transition:color .2s;line-height:1}}
.sidebar-toggle-btn:hover{{color:var(--accent)}}
.sidebar.collapsed .sidebar-toggle-btn{{text-align:center;transform:rotate(180deg)}}
.sidebar-main{{display:flex;flex-direction:column;gap:8px;padding:0 10px 10px;overflow-y:auto;flex:1;min-width:220px}}
.sidebar.collapsed .sidebar-main{{display:none}}
.sidebar-section{{color:var(--muted);font-size:9px;text-transform:uppercase;letter-spacing:1.2px;margin-top:4px;padding-bottom:2px;border-bottom:1px solid rgba(0,229,176,0.08)}}
textarea{{background:rgba(0,0,0,0.35);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:8px;font-family:inherit;font-size:12px;resize:none;width:100%;height:140px;transition:border-color .2s,box-shadow .2s}}
textarea:focus{{outline:none;border-color:var(--accent);box-shadow:var(--glow-sm)}}
.btn-run{{background:linear-gradient(135deg,#00b88a 0%,#007a5e 100%);color:#001a14;border:none;border-radius:5px;padding:8px;font-family:inherit;font-size:13px;cursor:pointer;width:100%;font-weight:700;letter-spacing:.5px;transition:all .2s;box-shadow:0 0 12px rgba(0,184,138,0.3)}}
.btn-run:hover{{background:linear-gradient(135deg,#00e5b0 0%,#009e76 100%);box-shadow:0 0 20px rgba(0,229,176,0.5)}}
.btn-run:disabled{{background:var(--surface2);color:var(--muted);cursor:not-allowed;box-shadow:none}}
.btn-new{{background:transparent;color:var(--muted);border:1px solid var(--border);border-radius:5px;padding:6px;font-family:inherit;font-size:12px;cursor:pointer;width:100%;transition:all .2s}}
.btn-new:hover{{color:var(--accent);border-color:var(--accent);box-shadow:var(--glow-sm)}}
.sidebar hr{{border:none;border-top:1px solid var(--border);margin:4px 0;opacity:.5}}
.hint{{color:var(--muted);font-size:10px;text-align:center;opacity:.7}}

/* ─ Project selector ─ */
.proj-row{{display:flex;gap:4px;align-items:center}}
.proj-input{{background:rgba(0,0,0,0.35);color:var(--text);border:1px solid var(--border);border-radius:5px;padding:5px 7px;font-family:inherit;font-size:11px;flex:1;min-width:0;transition:border-color .2s,box-shadow .2s}}
.proj-input:focus{{outline:none;border-color:var(--accent);box-shadow:var(--glow-sm)}}
.proj-input.ok{{border-color:var(--green);box-shadow:0 0 6px rgba(45,255,122,0.3)}}
.proj-input.err{{border-color:var(--red);box-shadow:0 0 6px rgba(255,68,85,0.3)}}
.proj-check{{background:var(--surface2);color:var(--muted);border:1px solid var(--border);border-radius:5px;padding:5px 8px;font-family:inherit;font-size:12px;cursor:pointer;flex-shrink:0;white-space:nowrap;transition:all .2s}}
.proj-check:hover{{border-color:var(--accent);color:var(--accent);box-shadow:var(--glow-sm)}}
.proj-status{{font-size:10px;min-height:14px;padding:0 2px}}
.proj-status.ok{{color:var(--green)}}
.proj-status.err{{color:var(--red)}}

/* ─ Main panel ─ */
.main{{flex:1;display:flex;flex-direction:column;overflow:hidden}}
.phases{{background:var(--surface);border-bottom:1px solid var(--border);padding:6px 14px;display:flex;align-items:center;gap:0;flex-shrink:0;overflow-x:auto;white-space:nowrap}}
.phase-pill{{font-size:10px;color:var(--muted);padding:2px 11px;border-radius:10px;cursor:default;transition:all .25s;letter-spacing:.3px}}
.phase-pill.active{{color:var(--accent);background:rgba(0,229,176,0.1);border:1px solid rgba(0,229,176,0.35);box-shadow:0 0 8px rgba(0,229,176,0.2),inset 0 0 6px rgba(0,229,176,0.05)}}
.phase-pill.done{{color:var(--green)}}
.phase-sep{{color:var(--border);padding:0 2px;font-size:10px}}
.output{{flex:1;overflow-y:auto;padding:12px 18px;scroll-behavior:smooth}}

/* ─ Output lines ─ */
.ln{{margin:1px 0;line-height:1.6}}
.ln.dim{{color:var(--muted)}}
.ln.think{{color:var(--muted);font-style:italic;font-size:11px;opacity:.7}}
.ln.phase-hdr{{color:var(--accent);margin-top:14px;font-size:11px;letter-spacing:.5px}}
.ln.agent-hdr{{margin-top:10px;font-weight:bold;font-size:12px}}
.ln.agent-step{{color:var(--muted);margin-top:8px;font-size:10px;opacity:.6}}
.ln.call{{white-space:pre-wrap}}
.ln.call .arr{{color:var(--muted)}}
.ln.result{{color:var(--muted);white-space:pre-wrap;padding-left:18px;border-left:2px solid rgba(0,229,176,0.12);margin-left:2px}}
.toggle-btn{{cursor:pointer;color:var(--muted);font-size:10px;margin-left:8px;user-select:none;background:none;border:none;font-family:inherit;padding:0;vertical-align:middle;transition:color .15s}}
.toggle-btn:hover{{color:var(--accent)}}
.result-panel{{padding-left:18px;border-left:2px solid rgba(0,229,176,0.12);margin-left:2px}}
.ln.final-hdr{{color:var(--green);margin-top:16px;font-size:12px;text-shadow:0 0 8px rgba(45,255,122,0.4)}}
.ln.final{{color:var(--green);white-space:pre-wrap}}
.ln.err{{color:var(--red)}}
.ln.plan-ok{{color:var(--green)}}
.ln.plan-no{{color:var(--red)}}
.ln.fallback{{color:var(--yellow);font-size:11px}}
.query-sep{{border:none;border-top:1px solid var(--border);margin:16px 0 10px;opacity:.3}}

.diff{{background:rgba(0,0,0,0.5);border:1px solid var(--border);border-radius:5px;padding:8px 10px;margin:3px 0 3px 20px;font-size:12px;white-space:pre;overflow-x:auto}}
.diff .del{{color:var(--red)}}
.diff .add{{color:var(--green)}}
.diff .meta{{color:var(--muted)}}

/* ─ Ask-user inline (agent execution phase) ─ */
.ln.ask-q{{color:var(--yellow);margin-top:12px;font-size:12px;text-shadow:0 0 6px rgba(255,204,68,0.3)}}
.ln.ask-q::before{{content:'? ';opacity:.7}}
.ln.ask-ans{{color:var(--cyan);padding-left:16px;margin-bottom:4px}}
.ask-container{{padding:6px 0 10px 16px;display:flex;flex-direction:column;gap:6px;max-width:480px}}
.ask-choice{{background:var(--surface2);color:var(--text);border:1px solid var(--border);border-radius:5px;padding:7px 16px;font-family:inherit;font-size:12px;cursor:pointer;text-align:left;transition:all .2s}}
.ask-choice:hover{{border-color:var(--accent);color:var(--accent);box-shadow:var(--glow-sm)}}
.ask-free{{display:flex;gap:6px}}
.ask-input{{background:rgba(0,0,0,0.4);color:var(--text);border:1px solid var(--border);border-radius:5px;padding:6px 10px;font-family:inherit;font-size:12px;flex:1;transition:all .2s}}
.ask-input:focus{{outline:none;border-color:var(--accent);box-shadow:var(--glow-sm)}}
.ask-submit{{background:var(--surface2);color:var(--text);border:1px solid var(--border);border-radius:5px;padding:6px 14px;font-family:inherit;font-size:12px;cursor:pointer;transition:all .2s}}
.ask-submit:hover{{border-color:var(--accent);color:var(--accent);box-shadow:var(--glow-sm)}}

/* ─ Planning-phase discovery question cards ─ */
.dq-card{{margin:10px 0 4px;background:linear-gradient(135deg,rgba(0,229,176,0.06),rgba(0,232,255,0.04));border:1px solid rgba(0,229,176,0.3);border-radius:10px;padding:14px 16px;max-width:560px;box-shadow:0 0 18px rgba(0,229,176,0.08)}}
.dq-header{{display:flex;align-items:center;gap:8px;margin-bottom:10px}}
.dq-cat{{font-size:10px;font-weight:700;letter-spacing:.8px;padding:2px 8px;border-radius:4px;border:1px solid}}
.dq-cat.SCOPE{{color:#79c0ff;border-color:rgba(121,192,255,.4);background:rgba(121,192,255,.1)}}
.dq-cat.TECH{{color:#d2a8ff;border-color:rgba(210,168,255,.4);background:rgba(210,168,255,.1)}}
.dq-cat.QUALITY{{color:#56d364;border-color:rgba(86,211,100,.4);background:rgba(86,211,100,.1)}}
.dq-cat.SECURITY{{color:#ff7b72;border-color:rgba(255,123,114,.4);background:rgba(255,123,114,.1)}}
.dq-cat.PERFORMANCE{{color:#ffa657;border-color:rgba(255,166,87,.4);background:rgba(255,166,87,.1)}}
.dq-cat.DEPLOYMENT{{color:#e3b341;border-color:rgba(227,179,65,.4);background:rgba(227,179,65,.1)}}
.dq-cat.STYLE{{color:#8b949e;border-color:rgba(139,148,158,.4);background:rgba(139,148,158,.1)}}
.dq-count{{margin-left:auto;color:var(--muted);font-size:10px}}
.dq-question{{color:var(--text);font-size:13px;margin-bottom:10px;line-height:1.5}}
.dq-choices{{display:flex;flex-direction:column;gap:5px}}
.dq-choice{{background:rgba(0,0,0,0.3);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:8px 14px;font-family:inherit;font-size:12px;cursor:pointer;text-align:left;transition:all .2s;position:relative}}
.dq-choice:hover:not(:disabled){{border-color:var(--accent);color:var(--accent);background:rgba(0,229,176,0.06);box-shadow:var(--glow-sm)}}
.dq-choice.selected{{border-color:var(--accent);color:var(--accent);background:rgba(0,229,176,0.1);cursor:default}}
.dq-choice.selected::after{{content:' \u2713';font-size:11px;opacity:.8}}
.dq-choice:disabled{{opacity:.5;cursor:default}}
.dq-impact{{margin-top:8px;font-size:10px;color:var(--muted);border-top:1px solid rgba(0,229,176,0.1);padding-top:6px;line-height:1.4}}
.dq-impact::before{{content:'\u25b8 Impact: ';}}
.dq-answered{{color:var(--cyan);font-size:12px;padding:4px 0 8px;padding-left:2px}}
.dq-answered::before{{content:'\u203a '}}

/* ─ Plan approval overlay ─ */
#plan-overlay{{display:none;position:fixed;inset:0;background:rgba(0,5,10,0.92);z-index:100;align-items:center;justify-content:center;padding:20px;backdrop-filter:blur(4px)}}
#plan-overlay.show{{display:flex}}
.plan-modal{{background:linear-gradient(145deg,#071e2c,#040d14);border:1px solid rgba(0,229,176,0.4);border-radius:12px;max-width:800px;width:100%;max-height:90vh;display:flex;flex-direction:column;gap:0;overflow:hidden;box-shadow:0 0 40px rgba(0,229,176,0.15),0 20px 60px rgba(0,0,0,0.8)}}
.plan-top{{padding:18px 20px 14px;border-bottom:1px solid var(--border)}}
.plan-title-row{{display:flex;align-items:center;gap:10px;margin-bottom:8px}}
.plan-title-row h2{{font-size:15px;flex:1;background:linear-gradient(90deg,var(--accent),var(--cyan));-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}}
.badge-type{{background:rgba(0,229,176,0.12);color:var(--accent);border:1px solid rgba(0,229,176,0.3);border-radius:4px;padding:2px 8px;font-size:11px}}
.badge-complexity.simple{{background:rgba(45,255,122,.12);color:var(--green);border:1px solid rgba(45,255,122,.3);border-radius:4px;padding:2px 8px;font-size:11px}}
.badge-complexity.medium{{background:rgba(255,204,68,.12);color:var(--yellow);border:1px solid rgba(255,204,68,.3);border-radius:4px;padding:2px 8px;font-size:11px}}
.badge-complexity.complex{{background:rgba(255,68,85,.12);color:var(--red);border:1px solid rgba(255,68,85,.3);border-radius:4px;padding:2px 8px;font-size:11px}}
.plan-summary-text{{color:var(--text);font-size:12px;line-height:1.5;opacity:.9}}
.plan-body{{flex:1;overflow-y:auto;padding:16px 20px;display:flex;flex-direction:column;gap:10px}}
.plan-phases-label{{color:var(--muted);font-size:9px;text-transform:uppercase;letter-spacing:1px}}
.phase-card{{background:rgba(0,229,176,0.04);border:1px solid rgba(0,229,176,0.12);border-radius:7px;padding:10px 12px;transition:border-color .2s}}
.phase-card:hover{{border-color:rgba(0,229,176,0.25)}}
.phase-card-head{{display:flex;align-items:center;gap:8px;margin-bottom:6px}}
.phase-num{{background:rgba(0,229,176,0.15);color:var(--accent);border:1px solid rgba(0,229,176,0.3);border-radius:50%;width:18px;height:18px;display:flex;align-items:center;justify-content:center;font-size:10px;flex-shrink:0}}
.phase-card-name{{color:var(--text);font-size:12px;font-weight:bold;flex:1}}
.badge-parallel{{background:rgba(0,229,176,0.1);color:var(--teal);border:1px solid rgba(0,229,176,0.25);border-radius:4px;padding:1px 6px;font-size:10px}}
.phase-card-desc{{color:var(--muted);font-size:11px;margin-bottom:8px}}
.agent-chips{{display:flex;flex-wrap:wrap;gap:6px}}
.agent-chip{{display:flex;align-items:center;gap:5px;border-radius:5px;padding:4px 10px;font-size:11px;border:1px solid}}
.plan-rationale{{background:rgba(0,229,176,0.05);border:1px solid rgba(0,229,176,0.18);border-radius:7px;padding:10px 12px}}
.plan-rationale-label{{color:var(--accent);font-size:9px;text-transform:uppercase;letter-spacing:.8px;margin-bottom:4px}}
.plan-rationale-text{{color:var(--muted);font-size:11px;line-height:1.5}}
.badge-risk.low{{background:rgba(45,255,122,.12);color:var(--green);border:1px solid rgba(45,255,122,.3);border-radius:4px;padding:2px 8px;font-size:11px}}
.badge-risk.medium{{background:rgba(255,204,68,.12);color:var(--yellow);border:1px solid rgba(255,204,68,.3);border-radius:4px;padding:2px 8px;font-size:11px}}
.badge-risk.high{{background:rgba(255,68,85,.12);color:var(--red);border:1px solid rgba(255,68,85,.3);border-radius:4px;padding:2px 8px;font-size:11px}}
.plan-meta-row{{display:flex;gap:8px;flex-wrap:wrap}}
.plan-info-block{{background:rgba(0,0,0,0.2);border:1px solid rgba(0,229,176,0.1);border-radius:7px;padding:8px 12px}}
.plan-info-label{{color:var(--accent);font-size:9px;text-transform:uppercase;letter-spacing:.8px;margin-bottom:5px}}
.plan-info-list{{list-style:none;padding:0;margin:0;display:flex;flex-direction:column;gap:3px}}
.plan-info-list li{{color:var(--muted);font-size:11px;line-height:1.4;padding-left:10px;position:relative}}
.plan-info-list li::before{{content:'\u2022';position:absolute;left:0;color:var(--accent);opacity:.5}}
.plan-requirements{{background:rgba(0,232,255,0.04);border:1px solid rgba(0,232,255,0.15);border-radius:7px;padding:10px 12px}}
.plan-req-label{{color:var(--cyan);font-size:9px;text-transform:uppercase;letter-spacing:.8px;margin-bottom:5px}}
.plan-req-item{{font-size:11px;color:var(--muted);line-height:1.6;padding:2px 0}}
.plan-req-item .req-q{{color:var(--text);opacity:.7}}
.plan-req-item .req-a{{color:var(--cyan)}}
.plan-footer{{padding:14px 20px;border-top:1px solid var(--border);display:flex;gap:10px;align-items:center}}
.plan-footer .hint{{flex:1;font-size:11px;color:var(--muted)}}
.btn-approve{{background:linear-gradient(135deg,#00b88a,#007a5e);color:#001a14;border:none;border-radius:6px;padding:9px 28px;font-family:inherit;font-size:13px;cursor:pointer;font-weight:700;transition:all .2s;box-shadow:0 0 12px rgba(0,184,138,0.4)}}
.btn-approve:hover{{background:linear-gradient(135deg,#00e5b0,#009e76);box-shadow:0 0 22px rgba(0,229,176,0.6)}}
.btn-reject{{background:transparent;color:var(--red);border:1px solid rgba(255,68,85,.5);border-radius:6px;padding:9px 20px;font-family:inherit;font-size:13px;cursor:pointer;transition:all .2s}}
.btn-reject:hover{{background:rgba(255,68,85,.08);border-color:var(--red);box-shadow:0 0 10px rgba(255,68,85,0.2)}}

/* ─ Edit approval overlay ─ */
#overlay{{display:none;position:fixed;inset:0;background:rgba(0,5,10,0.88);z-index:50;align-items:center;justify-content:center;backdrop-filter:blur(3px)}}
#overlay.show{{display:flex}}
.approval{{background:linear-gradient(145deg,#071e2c,#040d14);border:1px solid rgba(255,204,68,0.4);border-radius:10px;padding:20px;max-width:740px;width:93%;max-height:84vh;display:flex;flex-direction:column;gap:12px;box-shadow:0 0 30px rgba(255,204,68,0.1),0 20px 50px rgba(0,0,0,0.8)}}
.approval h3{{color:var(--yellow);font-size:13px;text-shadow:0 0 8px rgba(255,204,68,0.3)}}
.ap-path{{color:var(--muted);font-size:11px}}
.approval .diff{{flex:1;overflow-y:auto;max-height:52vh}}
.ap-btns{{display:flex;gap:8px}}
.btn-ok{{background:linear-gradient(135deg,#00b88a,#007a5e);color:#001a14;border:none;border-radius:5px;padding:8px 24px;font-family:inherit;cursor:pointer;font-weight:700;transition:all .2s}}
.btn-ok:hover{{box-shadow:0 0 16px rgba(0,229,176,0.5)}}
.btn-no{{background:linear-gradient(135deg,#cc2233,#991122);color:#fff;border:none;border-radius:5px;padding:8px 24px;font-family:inherit;cursor:pointer;transition:all .2s}}
.btn-no:hover{{box-shadow:0 0 16px rgba(255,68,85,0.4)}}

/* ─ Spinner ─ */
@keyframes spin{{to{{transform:rotate(360deg)}}}}
.spin{{display:inline-block;animation:spin .8s linear infinite}}

/* ─ Agent Viz Panel (right side) ─ */
.viz-panel{{display:flex;flex-direction:row;flex-shrink:0;overflow:hidden;transition:width .28s ease;border-left:1px solid var(--border);background:linear-gradient(180deg,#071a26 0%,#040e16 100%);width:28px}}
.viz-panel.expanded{{width:340px}}
.viz-strip{{width:28px;min-width:28px;display:flex;flex-direction:column;align-items:center;justify-content:center;cursor:pointer;gap:10px;padding:14px 0;transition:background .2s;flex-shrink:0}}
.viz-strip:hover{{background:rgba(0,229,176,0.05)}}
.viz-strip-lbl{{writing-mode:vertical-rl;transform:rotate(180deg);font-size:9px;color:var(--muted);letter-spacing:1.2px;text-transform:uppercase;white-space:nowrap;user-select:none}}
.viz-strip-arrow{{font-size:11px;color:var(--muted);transition:color .2s;line-height:1;user-select:none}}
.viz-strip:hover .viz-strip-arrow{{color:var(--accent)}}
.viz-content{{flex:1;display:flex;flex-direction:column;overflow:hidden;min-width:0}}
.viz-panel-hdr{{display:flex;align-items:center;padding:7px 12px;gap:8px;border-bottom:1px solid var(--border);flex-shrink:0}}
.viz-title{{font-size:9px;color:var(--muted);letter-spacing:1.2px;text-transform:uppercase;flex:1}}
.viz-status{{font-size:9px;color:var(--muted);opacity:.65}}
.viz-svg-wrap{{flex:1;position:relative;overflow:hidden;min-height:0}}
#viz-svg{{position:absolute;top:0;left:0;width:100%;height:100%;display:block}}
</style>
</head>
<body>

<header>
  <h1>&#x2B22; Multi-Agent Dev</h1>
  <span class="h-sep">|</span>
  <label>Model</label>
  <select id="mdl">{model_opts}</select>
  <label>Edit mode</label>
  <select id="mode">
    <option value="auto">Auto &#8212; apply immediately</option>
    <option value="ask">Ask &#8212; confirm every edit</option>
  </select>
  <span class="badge" id="badge">idle</span>
</header>

<div class="layout">

  <!-- ─ Sidebar ─ -->
  <div class="sidebar" id="sidebar">
    <button class="sidebar-toggle-btn" id="sidebar-toggle" onclick="toggleSidebar()" title="Collapse sidebar">&#x25c4;</button>
    <div class="sidebar-main">
      <span class="sidebar-section">Project</span>
      <div class="proj-row">
        <input id="proj" class="proj-input" type="text"
               placeholder="C:\\path\\to\\your\\project"
               oninput="onProjInput()"
               onkeydown="if(event.key==='Enter')validateProject()">
        <button class="proj-check" onclick="validateProject()" title="Validate path">&#10003;</button>
      </div>
      <div id="proj-status" class="proj-status"></div>
      <hr>
      <span class="sidebar-section">Task</span>
      <textarea id="task" placeholder="Describe your task&#8230;&#10;&#10;Examples:&#10;&#8226; Add user auth with JWT&#10;&#8226; Fix the 500 error in checkout&#10;&#8226; Migrate from Express to FastAPI"></textarea>
      <button class="btn-run" id="rbtn" onclick="run()" disabled>&#9654; Run Orchestrator</button>
      <button class="btn-new" id="nbtn" onclick="newSession()">&#10226; New Session</button>
      <div class="hint">Ctrl+Enter to run &nbsp;·&nbsp; Ctrl+K to clear</div>
    </div>
  </div>

  <!-- ─ Main panel ─ -->
  <div class="main">
    <div class="phases" id="phases-bar">
      <!-- populated by JS as phase_change events arrive -->
      <span class="phase-pill" id="pp-intake">Intake</span>
    </div>

    <div class="output" id="out"></div>
  </div>

  <!-- ─ Agent Network Viz (right panel) ─ -->
  <div class="viz-panel" id="viz-panel">
    <div class="viz-strip" onclick="VIZ.toggle()" title="Toggle Agent Network">
      <span class="viz-strip-arrow" id="viz-arrow">&#x25c2;</span>
      <span class="viz-strip-lbl">&#x2B22; Agents</span>
    </div>
    <div class="viz-content">
      <div class="viz-panel-hdr">
        <span class="viz-title">&#x2B22; Agent Network</span>
        <span class="viz-status" id="viz-status">idle</span>
      </div>
      <div class="viz-svg-wrap" id="viz-svg-wrap">
        <svg id="viz-svg"></svg>
      </div>
    </div>
  </div>

</div>

<!-- ─ Plan Approval Overlay ─ -->
<div id="plan-overlay">
  <div class="plan-modal">
    <div class="plan-top">
      <div class="plan-title-row">
        <h2>&#x1F4CB; Execution Plan</h2>
        <span class="badge-type" id="plan-type">&#8230;</span>
        <span class="badge-complexity" id="plan-complexity">&#8230;</span>
        <span class="badge-risk" id="plan-risk" style="display:none">&#8230;</span>
      </div>
      <div class="plan-summary-text" id="plan-summary">&#8230;</div>
    </div>
    <div class="plan-body">
      <div class="plan-phases-label">Phases</div>
      <div id="plan-phases"></div>
      <div class="plan-rationale" id="plan-rationale-wrap" style="display:none">
        <div class="plan-rationale-label">Rationale</div>
        <div class="plan-rationale-text" id="plan-rationale"></div>
      </div>
      <div id="plan-info-blocks" style="display:none">
        <div class="plan-meta-row">
          <div class="plan-info-block" id="plan-files-block" style="display:none;flex:1">
            <div class="plan-info-label">&#x1F4C4; Key Files</div>
            <ul class="plan-info-list" id="plan-files"></ul>
          </div>
          <div class="plan-info-block" id="plan-oos-block" style="display:none;flex:1">
            <div class="plan-info-label">&#x26D4; Out of Scope</div>
            <ul class="plan-info-list" id="plan-oos"></ul>
          </div>
        </div>
        <div class="plan-info-block" id="plan-assumptions-block" style="display:none">
          <div class="plan-info-label">&#x1F9E0; Assumptions</div>
          <ul class="plan-info-list" id="plan-assumptions"></ul>
        </div>
      </div>
      <div class="plan-requirements" id="plan-requirements-wrap" style="display:none">
        <div class="plan-req-label">&#x2713; Requirements Captured</div>
        <div id="plan-requirements"></div>
      </div>
    </div>
    <div class="plan-footer">
      <span class="hint">Review the plan above before proceeding &#8212; agents will execute autonomously.</span>
      <button class="btn-reject" onclick="planDecision(false)">&#10007; Reject</button>
      <button class="btn-approve" onclick="planDecision(true)">&#10003; Approve Plan</button>
    </div>
  </div>
</div>

<!-- ─ Edit Approval Overlay ─ -->
<div id="overlay">
  <div class="approval">
    <h3>&#9888; Proposed file edit</h3>
    <div class="ap-path" id="ap-path"></div>
    <div class="diff" id="ap-diff"></div>
    <div class="ap-btns">
      <button class="btn-ok" onclick="respond(true)">&#10003; Approve</button>
      <button class="btn-no" onclick="respond(false)">&#10007; Reject</button>
    </div>
  </div>
</div>

<script>
const out    = document.getElementById('out');
const rbtn   = document.getElementById('rbtn');
const badge  = document.getElementById('badge');
const phBar  = document.getElementById('phases-bar');
let es              = null;
let lastTool        = null;
let lastAgent       = null;
let lastResultPanel = null;
let validatedProject = '';   // non-empty = a valid project path has been confirmed

const AGENT_SPECS = {agent_specs_js};

// ─ Agent Network Visualization (SVG, right-panel, state-driven) ──────────────

const VIZ = (function() {{
  let svg, nodes = {{}}, expanded = false;
  const NS  = 'http://www.w3.org/2000/svg';
  const GAP = 10;   // px gap between node edge and connection line start/end

  function mkEl(tag, attrs, parent) {{
    const e = document.createElementNS(NS, tag);
    if (attrs) Object.entries(attrs).forEach(function(kv) {{ e.setAttribute(kv[0], String(kv[1])); }});
    if (parent) parent.appendChild(e);
    return e;
  }}

  function hexRgb(hex) {{
    return [parseInt(hex.slice(1,3),16)/255, parseInt(hex.slice(3,5),16)/255, parseInt(hex.slice(5,7),16)/255];
  }}

  function init() {{
    svg = document.getElementById('viz-svg');
    if (!svg) return;
    nodes = {{
      user:         {{label:'You',         color:'#00e8ff', state:'idle'}},
      orchestrator: {{label:'Orchestrator', color:'#00e5b0', state:'idle'}},
    }};
    Object.entries(AGENT_SPECS).forEach(function([id, spec]) {{
      nodes[id] = {{label:spec.name, color:spec.color||'#00e5b0', state:'idle'}};
    }});
    window.addEventListener('resize', function() {{ if (expanded) {{ calcPositions(); render(); }} }});
  }}

  function calcPositions() {{
    if (!svg) return;
    const wrap = document.getElementById('viz-svg-wrap');
    const W = (wrap ? wrap.clientWidth  : 0) || 312;
    const H = (wrap ? wrap.clientHeight : 0) || 500;
    svg.setAttribute('width',  W);
    svg.setAttribute('height', H);

    // Left column: User (top-ish) and Orchestrator (middle)
    const UW=88, UH=36, OW=108, OH=36, AW=152, AH=36;
    const leftCX = 14 + Math.max(UW, OW) / 2;          // ~68
    if (nodes.user) {{
      nodes.user.cx = leftCX; nodes.user.cy = Math.max(H * 0.14, UH/2 + 18);
      nodes.user.w  = UW;     nodes.user.h  = UH;
    }}
    if (nodes.orchestrator) {{
      nodes.orchestrator.cx = leftCX; nodes.orchestrator.cy = H * 0.5;
      nodes.orchestrator.w  = OW;     nodes.orchestrator.h  = OH;
    }}

    // Right column: all agents spread vertically
    const rightCX = W - 14 - AW / 2;
    const ids = Object.keys(AGENT_SPECS);
    const n   = ids.length;
    const topY = AH / 2 + 16;
    const botY = H - AH / 2 - 16;
    ids.forEach(function(id, i) {{
      const cy = n > 1 ? topY + i * (botY - topY) / (n - 1) : H / 2;
      if (nodes[id]) {{ nodes[id].cx = rightCX; nodes[id].cy = cy; nodes[id].w = AW; nodes[id].h = AH; }}
    }});
  }}

  function render() {{
    if (!svg) return;
    const W = parseInt(svg.getAttribute('width'))  || 312;
    const H = parseInt(svg.getAttribute('height')) || 500;
    svg.innerHTML = '';

    // ── Glow filters ────────────────────────────────────────────────────────
    const defs = mkEl('defs', {{}}, svg);
    Object.entries(nodes).forEach(function([id, n]) {{
      const sid = id.replace(/[^a-z0-9]/gi, '_');
      [
        {{s:'idle',    col:n.color,   blur:3,  alpha:0.22, anim:false}},
        {{s:'running', col:n.color,   blur:9,  alpha:0.95, anim:true }},
        {{s:'done',    col:'#2dff7a', blur:12, alpha:0.9,  anim:false}},
        {{s:'error',   col:'#ff4455', blur:9,  alpha:0.88, anim:false}},
        {{s:'asking',  col:'#00e8ff', blur:9,  alpha:0.95, anim:true }},
      ].forEach(function(cfg) {{
        const filt = mkEl('filter', {{id:'gf-'+sid+'-'+cfg.s, x:'-60%', y:'-60%', width:'220%', height:'220%'}}, defs);
        const blEl = mkEl('feGaussianBlur', {{in:'SourceGraphic', result:'blur'}}, filt);
        if (cfg.anim) {{
          mkEl('animate', {{
            attributeName:'stdDeviation',
            values:(cfg.blur*0.38)+';'+cfg.blur+';'+(cfg.blur*0.38),
            dur:'1.6s', repeatCount:'indefinite'
          }}, blEl);
        }} else {{
          blEl.setAttribute('stdDeviation', cfg.blur);
        }}
        const rgb = hexRgb(cfg.col);
        mkEl('feColorMatrix', {{
          in:'blur', type:'matrix', result:'cb',
          values:'0 0 0 0 '+rgb[0]+' 0 0 0 0 '+rgb[1]+' 0 0 0 0 '+rgb[2]+' 0 0 0 '+cfg.alpha+' 0'
        }}, filt);
        const mg = mkEl('feMerge', {{}}, filt);
        mkEl('feMergeNode', {{in:'cb'}}, mg);
        mkEl('feMergeNode', {{in:'SourceGraphic'}}, mg);
      }});
    }});

    // ── Background ──────────────────────────────────────────────────────────
    mkEl('rect', {{x:0, y:0, width:W, height:H, fill:'#040d12'}}, svg);

    // ── Subtle dot grid ─────────────────────────────────────────────────────
    for (let x = 22; x < W; x += 30) {{
      for (let y = 18; y < H; y += 24) {{
        mkEl('circle', {{cx:x, cy:y, r:0.8, fill:'rgba(0,229,176,0.07)'}}, svg);
      }}
    }}

    // ── Connections ─────────────────────────────────────────────────────────
    // User → Orchestrator: vertical bezier
    (function() {{
      const fr = nodes.user, to = nodes.orchestrator;
      if (!fr||!to||!fr.cx) return;
      const active = fr.state==='running' || to.state==='running';
      const x1=fr.cx, y1=fr.cy+fr.h/2+GAP;
      const x2=to.cx, y2=to.cy-to.h/2-GAP;
      const my=(y1+y2)/2;
      const col = fr.color;
      const op  = active ? 0.72 : 0.14;
      const sw  = active ? 1.6  : 1;
      // connector dots on node edges
      mkEl('circle', {{cx:x1, cy:y1-GAP, r:3, fill:col, 'fill-opacity':active?0.85:0.22}}, svg);
      mkEl('circle', {{cx:x2, cy:y2+GAP, r:3, fill:col, 'fill-opacity':active?0.85:0.22}}, svg);
      mkEl('path', {{
        d:'M'+x1+','+y1+' C'+x1+','+my+' '+x2+','+my+' '+x2+','+y2,
        stroke:col, 'stroke-opacity':op, 'stroke-width':sw,
        fill:'none', 'stroke-linecap':'round'
      }}, svg);
    }})();

    // Orchestrator → Agents: horizontal bezier
    Object.keys(AGENT_SPECS).forEach(function(id) {{
      const fr = nodes.orchestrator, to = nodes[id];
      if (!fr||!to||!fr.cx||!to.cx) return;
      const active = fr.state==='running' || to.state==='running';
      const x1=fr.cx+fr.w/2+GAP, y1=fr.cy;
      const x2=to.cx-to.w/2-GAP, y2=to.cy;
      const mx=(x1+x2)/2;
      const col = to.color;
      const op  = active ? 0.72 : 0.14;
      const sw  = active ? 1.6  : 1;
      // connector dots
      mkEl('circle', {{cx:x1-GAP, cy:y1, r:3, fill:fr.color, 'fill-opacity':active?0.85:0.22}}, svg);
      mkEl('circle', {{cx:x2+GAP, cy:y2, r:3, fill:col,      'fill-opacity':active?0.85:0.22}}, svg);
      mkEl('path', {{
        d:'M'+x1+','+y1+' C'+mx+','+y1+' '+mx+','+y2+' '+x2+','+y2,
        stroke:col, 'stroke-opacity':op, 'stroke-width':sw,
        fill:'none', 'stroke-linecap':'round'
      }}, svg);
    }});

    // ── Nodes ────────────────────────────────────────────────────────────────
    Object.entries(nodes).forEach(function([id, n]) {{
      if (!n||!n.cx) return;
      const {{cx, cy, w, state, label, color}} = n;
      const nh  = n.h || 36;
      const col = state==='done' ? '#2dff7a' : state==='error' ? '#ff4455' : color;
      const sid = id.replace(/[^a-z0-9]/gi, '_');
      const fs  = state==='answered' ? 'asking'
                : (['idle','running','done','error','asking'].includes(state) ? state : 'idle');
      const g   = mkEl('g', {{filter:'url(#gf-'+sid+'-'+fs+')'}}, svg);

      // Pill — dark fill, colored border only
      const strokeA = state==='idle' ? 0.28 : 0.9;
      const sw      = state==='running' ? 2 : 1.4;
      mkEl('rect', {{
        x:cx-w/2, y:cy-nh/2, width:w, height:nh, rx:nh/2,
        fill:'#071520', 'fill-opacity':1,
        stroke:col, 'stroke-opacity':strokeA, 'stroke-width':sw
      }}, g);

      // Label
      const lbl = label.length > 16 ? label.slice(0,15)+'\u2026' : label;
      const t   = mkEl('text', {{
        x:cx, y:cy, 'text-anchor':'middle', 'dominant-baseline':'middle',
        fill:col, 'fill-opacity':state==='idle' ? 0.42 : 0.92,
        'font-size':10, 'font-family':'Consolas,monospace'
      }}, g);
      t.textContent = lbl;

      // Error badge
      if (state === 'error') {{
        const bx = cx + w/2 - 2, by = cy - nh/2;
        const bg2 = mkEl('g', {{filter:'drop-shadow(0 0 4px #ff4455)'}}, g);
        mkEl('circle', {{cx:bx, cy:by, r:8, fill:'#ff4455'}}, bg2);
        const et = mkEl('text', {{
          x:bx, y:by, 'text-anchor':'middle', 'dominant-baseline':'middle',
          fill:'#fff', 'font-size':10, 'font-weight':'bold', 'font-family':'sans-serif'
        }}, bg2);
        et.textContent = '!';
      }}
    }});
  }}

  function setNodeState(id, state) {{
    if (!nodes[id]) return;
    nodes[id].state = state;
    const anyRun = Object.keys(AGENT_SPECS).some(function(aid) {{
      return nodes[aid] && nodes[aid].state === 'running';
    }});
    if (nodes.orchestrator) nodes.orchestrator.state = anyRun ? 'running' : 'idle';
    if (expanded) render();
    const lbl = document.getElementById('viz-status');
    if (lbl) lbl.textContent = anyRun ? 'running\u2026' : 'idle';
  }}

  function setUserState(state) {{
    if (!nodes.user) return;
    nodes.user.state = state;
    if (state === 'answered') setTimeout(function() {{ setUserState('idle'); }}, 800);
    if (expanded) render();
  }}

  function toggle() {{
    expanded = !expanded;
    const panel = document.getElementById('viz-panel');
    const arrow = document.getElementById('viz-arrow');
    if (expanded) {{
      panel.classList.add('expanded');
      if (arrow) arrow.textContent = '\u25b8';   // ▸ collapse
      setTimeout(function() {{ calcPositions(); render(); }}, 290);
    }} else {{
      panel.classList.remove('expanded');
      if (arrow) arrow.textContent = '\u25c2';   // ◂ expand
    }}
  }}

  function addPulse(fromId, toId, col) {{
    // State-driven — connection opacity updates automatically via render()
  }}

  function reset() {{
    Object.values(nodes).forEach(function(n) {{ n.state = 'idle'; }});
    if (expanded) render();
    const lbl = document.getElementById('viz-status');
    if (lbl) lbl.textContent = 'idle';
  }}

  return {{init:init, toggle:toggle, setNodeState:setNodeState, setUserState:setUserState, addPulse:addPulse, reset:reset}};
}})();

// ─ Sidebar toggle ────────────────────────────────────────────────────────────

function toggleSidebar() {{
  const sb  = document.getElementById('sidebar');
  const btn = document.getElementById('sidebar-toggle');
  const collapsed = sb.classList.toggle('collapsed');
  btn.innerHTML = collapsed ? '&#x25ba;' : '&#x25c4;';
  btn.title     = collapsed ? 'Expand sidebar' : 'Collapse sidebar';
  btn.style.textAlign = collapsed ? 'center' : 'right';
  // Sidebar width changed — sidebar doesn't affect the right viz panel, no recalc needed
}}

// ─ Project selector ───────────────────────────────────────────────────────────

function onProjInput() {{
  // User changed the input — invalidate any previous validation
  validatedProject = '';
  const inp = document.getElementById('proj');
  inp.classList.remove('ok', 'err');
  document.getElementById('proj-status').className = 'proj-status';
  document.getElementById('proj-status').textContent = '';
  rbtn.disabled = true;
}}

async function validateProject() {{
  const inp  = document.getElementById('proj');
  const stat = document.getElementById('proj-status');
  const raw  = inp.value.trim();
  if (!raw) {{
    stat.className = 'proj-status err';
    stat.textContent = 'Enter a project path first.';
    return;
  }}
  stat.className = 'proj-status';
  stat.textContent = 'Checking\u2026';
  try {{
    const res  = await fetch('/validate_project?' + new URLSearchParams({{path: raw}}));
    const data = await res.json();
    if (data.ok) {{
      validatedProject = data.resolved;
      inp.value = data.resolved;          // normalise to absolute path
      inp.classList.remove('err'); inp.classList.add('ok');
      stat.className = 'proj-status ok';
      stat.textContent = '\u2713 Project set';
      rbtn.disabled = false;
    }} else {{
      validatedProject = '';
      inp.classList.remove('ok'); inp.classList.add('err');
      stat.className = 'proj-status err';
      stat.textContent = data.error || 'Directory not found.';
      rbtn.disabled = true;
    }}
  }} catch(e) {{
    stat.className = 'proj-status err';
    stat.textContent = 'Validation request failed.';
  }}
}}

// ─ Utilities ─────────────────────────────────────────────────────────────────

const esc = s => String(s)
  .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');

function ln(cls, html, color) {{
  const d = document.createElement('div');
  d.className = 'ln ' + cls;
  d.innerHTML = html;
  if (color) d.style.color = color;
  out.appendChild(d);
  out.scrollTop = out.scrollHeight;
  return d;
}}

function setBadge(txt, col) {{
  badge.textContent = txt;
  badge.style.color = col || 'var(--muted)';
}}

function renderDiff(raw) {{
  return (raw || '').split('\\n').map(l => {{
    if (l.startsWith('---')||l.startsWith('+++')) return '<span class="meta">'+esc(l)+'</span>';
    if (l.startsWith('-')) return '<span class="del">'+esc(l)+'</span>';
    if (l.startsWith('+')) return '<span class="add">'+esc(l)+'</span>';
    if (l.startsWith('@@')) return '<span class="meta">'+esc(l)+'</span>';
    return esc(l);
  }}).join('\\n');
}}

function addDiff(raw) {{
  const d = document.createElement('div');
  d.className = 'diff';
  d.innerHTML = renderDiff(raw);
  out.appendChild(d);
  out.scrollTop = out.scrollHeight;
}}

// ─ Agent status sidebar ───────────────────────────────────────────────────────

function setAgentStatus(agentId, status) {{
  const el = document.getElementById('as-' + agentId);
  const row = document.getElementById('ar-' + agentId);
  if (el) {{
    el.className = 'agent-status ' + status;
    if (status === 'running') {{
      el.innerHTML = '<span class="spin">&#9651;</span>';
      if (row) row.classList.add('active');
    }} else if (status === 'done') {{
      el.innerHTML = '&#10003;';
      if (row) row.classList.remove('active');
    }} else if (status === 'error') {{
      el.innerHTML = '&#10007;';
      if (row) row.classList.remove('active');
    }} else {{
      el.innerHTML = '&#9675;';
      if (row) row.classList.remove('active');
    }}
  }}
  VIZ.setNodeState(agentId, status);
}}

// ─ Phase breadcrumb ───────────────────────────────────────────────────────────

const phaseOrder = ['intake','discovery','analysis','design','execution','validation','delivery'];
const phaseNames = {{
  intake:'Intake', discovery:'Discovery', analysis:'Analysis', design:'Design',
  execution:'Execution', validation:'Validation', delivery:'Delivery'
}};
let knownPhases = ['intake'];

function setPhase(phaseId, phaseName) {{
  if (!knownPhases.includes(phaseId)) {{
    knownPhases.push(phaseId);
  }}
  // Re-render breadcrumb
  phBar.innerHTML = '';
  knownPhases.forEach((pid, i) => {{
    if (i > 0) {{
      const sep = document.createElement('span');
      sep.className = 'phase-sep';
      sep.textContent = ' › ';
      phBar.appendChild(sep);
    }}
    const pill = document.createElement('span');
    pill.className = 'phase-pill' + (pid === phaseId ? ' active' : (knownPhases.indexOf(pid) < knownPhases.indexOf(phaseId) ? ' done' : ''));
    pill.textContent = phaseId === pid ? (phaseName || phaseNames[pid] || pid) : (phaseNames[pid] || pid);
    pill.id = 'pp-' + pid;
    phBar.appendChild(pill);
  }});
}}

// ─ Plan modal ────────────────────────────────────────────────────────────────

function showPlan(plan) {{
  // Type badge
  const typeEl = document.getElementById('plan-type');
  typeEl.textContent = (plan.task_type || 'unknown').replace(/_/g, ' ');

  // Complexity badge
  const cx = plan.complexity || 'medium';
  const cxEl = document.getElementById('plan-complexity');
  cxEl.textContent = cx;
  cxEl.className = 'badge-complexity ' + cx;

  // Risk level badge
  const risk = plan.risk_level || '';
  const riskEl = document.getElementById('plan-risk');
  if (risk) {{
    riskEl.textContent = risk + ' risk';
    riskEl.className = 'badge-risk ' + risk;
    riskEl.style.display = '';
  }} else {{
    riskEl.style.display = 'none';
  }}

  // Summary
  document.getElementById('plan-summary').textContent = plan.task_summary || '';

  // Phases
  const phasesEl = document.getElementById('plan-phases');
  phasesEl.innerHTML = '';
  (plan.phases || []).forEach((phase, i) => {{
    const card = document.createElement('div');
    card.className = 'phase-card';

    const head = document.createElement('div');
    head.className = 'phase-card-head';
    const numBadge = document.createElement('span');
    numBadge.className = 'phase-num';
    numBadge.textContent = i + 1;
    const nameLbl = document.createElement('span');
    nameLbl.className = 'phase-card-name';
    nameLbl.textContent = phase.name || phase.id || '';
    head.appendChild(numBadge);
    head.appendChild(nameLbl);
    if (phase.parallel) {{
      const pb = document.createElement('span');
      pb.className = 'badge-parallel';
      pb.textContent = 'parallel';
      head.appendChild(pb);
    }}
    card.appendChild(head);

    if (phase.description) {{
      const desc = document.createElement('div');
      desc.className = 'phase-card-desc';
      desc.textContent = phase.description;
      card.appendChild(desc);
    }}

    const chips = document.createElement('div');
    chips.className = 'agent-chips';
    (phase.agents || []).forEach(a => {{
      const spec = AGENT_SPECS[a.id] || {{}};
      const chip = document.createElement('div');
      chip.className = 'agent-chip';
      chip.style.color = spec.color || '#c9d1d9';
      chip.style.borderColor = (spec.color || '#30363d') + '55';
      chip.style.background = (spec.color || '#30363d') + '11';
      chip.innerHTML = (spec.icon || '&#129302;') + ' <b>' + esc(spec.name || a.id) + '</b>';
      chip.title = a.task || '';
      chips.appendChild(chip);
    }});
    card.appendChild(chips);
    phasesEl.appendChild(card);
  }});

  // Rationale
  if (plan.rationale) {{
    document.getElementById('plan-rationale').textContent = plan.rationale;
    document.getElementById('plan-rationale-wrap').style.display = '';
  }} else {{
    document.getElementById('plan-rationale-wrap').style.display = 'none';
  }}

  // Key files, assumptions, out_of_scope
  let hasInfoBlocks = false;

  const keyFiles = plan.key_files || [];
  const filesBlock = document.getElementById('plan-files-block');
  const filesList = document.getElementById('plan-files');
  if (keyFiles.length > 0) {{
    filesList.innerHTML = '';
    keyFiles.forEach(f => {{
      const li = document.createElement('li');
      li.textContent = f;
      filesList.appendChild(li);
    }});
    filesBlock.style.display = '';
    hasInfoBlocks = true;
  }} else {{
    filesBlock.style.display = 'none';
  }}

  const oosItems = plan.out_of_scope || [];
  const oosBlock = document.getElementById('plan-oos-block');
  const oosList = document.getElementById('plan-oos');
  if (oosItems.length > 0) {{
    oosList.innerHTML = '';
    oosItems.forEach(item => {{
      const li = document.createElement('li');
      li.textContent = item;
      oosList.appendChild(li);
    }});
    oosBlock.style.display = '';
    hasInfoBlocks = true;
  }} else {{
    oosBlock.style.display = 'none';
  }}

  const assumptions = plan.assumptions || [];
  const assumpBlock = document.getElementById('plan-assumptions-block');
  const assumpList = document.getElementById('plan-assumptions');
  if (assumptions.length > 0) {{
    assumpList.innerHTML = '';
    assumptions.forEach(a => {{
      const li = document.createElement('li');
      li.textContent = a;
      assumpList.appendChild(li);
    }});
    assumpBlock.style.display = '';
    hasInfoBlocks = true;
  }} else {{
    assumpBlock.style.display = 'none';
  }}

  document.getElementById('plan-info-blocks').style.display = hasInfoBlocks ? '' : 'none';

  // Requirements summary (answers from discovery phase)
  const userAnswers = plan.user_answers || {{}};
  const reqWrap = document.getElementById('plan-requirements-wrap');
  const reqEl = document.getElementById('plan-requirements');
  const answerKeys = Object.keys(userAnswers);
  if (answerKeys.length > 0) {{
    reqEl.innerHTML = '';
    answerKeys.forEach(q => {{
      const row = document.createElement('div');
      row.className = 'plan-req-item';
      row.innerHTML = '<span class="req-q">' + esc(q) + '</span>'
        + ' &rarr; <span class="req-a">' + esc(userAnswers[q]) + '</span>';
      reqEl.appendChild(row);
    }});
    reqWrap.style.display = '';
  }} else {{
    reqWrap.style.display = 'none';
  }}

  document.getElementById('plan-overlay').classList.add('show');
}}

async function planDecision(approved) {{
  document.getElementById('plan-overlay').classList.remove('show');
  await fetch(approved ? '/plan_approve' : '/plan_reject', {{method: 'POST'}});
  ln(approved ? 'plan-ok' : 'plan-no',
     approved ? '&#10003; Plan approved — starting execution&#8230;'
              : '&#10007; Plan rejected.');
}}

// ─ Session management ─────────────────────────────────────────────────────────

async function newSession() {{
  await fetch('/clear', {{method: 'POST'}});
  out.innerHTML = '';
  phBar.innerHTML = '<span class="phase-pill active" id="pp-intake">Intake</span>';
  knownPhases = ['intake'];
  lastResultPanel = null;
  setBadge('idle', '');
  Object.keys(AGENT_SPECS).forEach(id => setAgentStatus(id, 'idle'));
  VIZ.reset();
  // Keep project validated across sessions — user keeps the same project open
  rbtn.disabled = !validatedProject;
}}

// ─ Run ───────────────────────────────────────────────────────────────────────

function run() {{
  const task = document.getElementById('task').value.trim();
  if (!task) return;
  if (!validatedProject) {{
    const stat = document.getElementById('proj-status');
    stat.className = 'proj-status err';
    stat.textContent = 'Set and validate a project directory first.';
    document.getElementById('proj').classList.add('err');
    return;
  }}
  const model = document.getElementById('mdl').value;
  const mode  = document.getElementById('mode').value;

  document.getElementById('task').value = '';
  if (out.children.length > 0) {{
    const hr = document.createElement('hr');
    hr.className = 'query-sep';
    out.appendChild(hr);
    knownPhases = ['intake'];
  }}

  rbtn.disabled = true;
  setBadge('running\u2026', 'var(--yellow)');
  // Auto-expand viz panel when a run starts
  const vizPanel = document.getElementById('viz-panel');
  if (vizPanel && !vizPanel.classList.contains('expanded')) VIZ.toggle();
  if (es) es.close();

  es = new EventSource('/stream?' + new URLSearchParams({{
    task,
    model,
    edit_mode:    mode,
    project_path: validatedProject,
  }}));

  es.onmessage = e => {{
    const ev = JSON.parse(e.data);
    handle(ev);
  }};

  es.onerror = () => {{
    rbtn.disabled = false;
    setBadge('error', 'var(--red)');
  }};
}}

function handle(ev) {{
  switch (ev.type) {{

    case 'start':
      ln('dim', 'Task : ' + esc(ev.task));
      ln('dim', 'Model: ' + esc(ev.model));
      break;

    case 'phase_change':
      setPhase(ev.phase, ev.phase_name);
      ln('phase-hdr',
         '&#9632; ' + esc(ev.phase_name || ev.phase).toUpperCase()
         + (ev.description ? ' &#8212; ' + esc(ev.description) : ''));
      break;

    case 'orchestrator_thinking':
      ln('think', esc(ev.text || ''));
      break;

    case 'plan_ready':
      ln('dim', 'Execution plan ready. Awaiting your approval\u2026');
      showPlan(ev.plan);
      break;

    case 'plan_approved':
      // handled inline in planDecision()
      break;

    case 'plan_rejected':
      rbtn.disabled = false;
      setBadge('idle', '');
      break;

    case 'agent_start': {{
      lastAgent = ev.agent;
      const spec = AGENT_SPECS[ev.agent] || {{}};
      setAgentStatus(ev.agent, 'running');
      ln('agent-hdr',
         (spec.icon || '&#129302;') + ' ' + esc(ev.agent_name || ev.agent),
         ev.agent_color || 'var(--text)');
      break;
    }}

    case 'agent_step':
      ln('agent-step',
         '\u2500\u2500 step ' + ev.n + ' ' + '\u2500'.repeat(30),
         ev.agent_color || 'var(--muted)');
      break;

    case 'agent_fallback':
      ln('fallback', '[fallback] ' + ev.count + ' inline tool call(s) parsed',
         ev.agent_color);
      break;

    case 'agent_tool_call': {{
      lastTool = ev.name;
      const isWriteEdit = ev.name === 'write_file' || ev.name === 'edit_file';
      const callLine = ln('call',
         '<span class="arr">\u2192</span> <b>' + esc(ev.name) + '</b>(' + esc(ev.args_str) + ')'
         + (!isWriteEdit ? ' <button class="toggle-btn" onclick="toggleResult(this)">\u25b6</button>' : ''),
         ev.agent_color || 'var(--cyan)');
      // Create result panel (hidden for read tools, visible for write/edit)
      const panel = document.createElement('div');
      panel.className = 'result-panel';
      panel.style.display = isWriteEdit ? '' : 'none';
      out.appendChild(panel);
      lastResultPanel = panel;
      out.scrollTop = out.scrollHeight;
      break;
    }}

    case 'agent_tool_result': {{
      if (lastTool === 'read_file') break;
      if (lastTool === 'ask_user') break;
      const txt = ev.preview || '';
      if (lastTool === 'run_shell' || lastTool === 'run') {{
        const hasErr = /\\[error\\]|\\[stderr\\]|traceback|error:|failed|exception/i.test(txt);
        if (!hasErr) break;
        // Show errors even for shell — make panel visible
        if (lastResultPanel) lastResultPanel.style.display = '';
      }}
      const target = lastResultPanel || out;
      const di = txt.indexOf('--- a/');
      if (di !== -1) {{
        const before = txt.slice(0, di).trim();
        if (before) {{
          const bd = document.createElement('div');
          bd.className = 'ln result'; bd.textContent = before;
          target.appendChild(bd);
        }}
        const dd = document.createElement('div');
        dd.className = 'diff'; dd.innerHTML = renderDiff(txt.slice(di));
        target.appendChild(dd);
      }} else {{
        const rd = document.createElement('div');
        rd.className = 'ln result'; rd.textContent = txt;
        target.appendChild(rd);
      }}
      out.scrollTop = out.scrollHeight;
      break;
    }}

    case 'agent_done':
      setAgentStatus(ev.agent, 'done');
      break;

    case 'agent_error':
      setAgentStatus(ev.agent, 'error');
      ln('err', '[' + esc(ev.agent_name || ev.agent) + ' ERROR] ' + esc(ev.error || ''));
      break;

    case 'ask_user': {{
      VIZ.setUserState('asking');

      if (ev.is_planning) {{
        // ── Planning-phase discovery question card ──────────────────────────
        const card = document.createElement('div');
        card.className = 'dq-card';
        card.id = 'ask-box';

        // Header row: category badge + question count
        const hdr = document.createElement('div');
        hdr.className = 'dq-header';
        if (ev.category) {{
          const cat = document.createElement('span');
          cat.className = 'dq-cat ' + ev.category;
          cat.textContent = ev.category;
          hdr.appendChild(cat);
        }}
        if (ev.question_total) {{
          const cnt = document.createElement('span');
          cnt.className = 'dq-count';
          cnt.textContent = 'Question ' + ev.question_index + ' of ' + ev.question_total;
          hdr.appendChild(cnt);
        }}
        card.appendChild(hdr);

        // Question text
        const qtxt = document.createElement('div');
        qtxt.className = 'dq-question';
        qtxt.textContent = ev.question;
        card.appendChild(qtxt);

        // Choice buttons
        const choices = document.createElement('div');
        choices.className = 'dq-choices';
        if (ev.choices && ev.choices.length) {{
          ev.choices.forEach(c => {{
            const btn = document.createElement('button');
            btn.className = 'dq-choice';
            btn.textContent = c;
            btn.onclick = () => {{
              // Mark selected, disable all, then submit
              choices.querySelectorAll('.dq-choice').forEach(b => {{
                b.disabled = true;
                b.classList.remove('selected');
              }});
              btn.classList.add('selected');
              sendAnswer(c);
            }};
            choices.appendChild(btn);
          }});
        }} else {{
          // Free-text fallback for planning questions
          const row = document.createElement('div');
          row.className = 'ask-free';
          const inp = document.createElement('input');
          inp.type = 'text'; inp.className = 'ask-input'; inp.id = 'ask-inp';
          inp.placeholder = 'Type your answer\u2026';
          inp.onkeydown = e => {{ if (e.key === 'Enter' && inp.value.trim()) sendAnswer(inp.value.trim()); }};
          const sbtn = document.createElement('button');
          sbtn.className = 'ask-submit'; sbtn.textContent = 'Confirm';
          sbtn.onclick = () => {{ if (inp.value.trim()) sendAnswer(inp.value.trim()); }};
          row.appendChild(inp); row.appendChild(sbtn);
          choices.appendChild(row);
          setTimeout(() => inp.focus(), 40);
        }}
        card.appendChild(choices);

        // Impact hint
        if (ev.impact) {{
          const impact = document.createElement('div');
          impact.className = 'dq-impact';
          impact.textContent = ev.impact;
          card.appendChild(impact);
        }}

        out.appendChild(card);
        out.scrollTop = out.scrollHeight;

      }} else {{
        // ── Agent execution ask_user (original style) ───────────────────────
        ln('ask-q', esc(ev.question));
        const box = document.createElement('div');
        box.className = 'ask-container';
        box.id = 'ask-box';
        if (ev.choices && ev.choices.length) {{
          ev.choices.forEach(c => {{
            const btn = document.createElement('button');
            btn.className = 'ask-choice';
            btn.textContent = c;
            btn.onclick = () => sendAnswer(c);
            box.appendChild(btn);
          }});
        }} else {{
          const row = document.createElement('div');
          row.className = 'ask-free';
          const inp = document.createElement('input');
          inp.type = 'text'; inp.className = 'ask-input'; inp.id = 'ask-inp';
          inp.placeholder = 'Type your answer\u2026';
          inp.onkeydown = e => {{ if (e.key === 'Enter') sendAnswer(inp.value.trim()); }};
          const btn = document.createElement('button');
          btn.className = 'ask-submit'; btn.textContent = 'Submit';
          btn.onclick = () => sendAnswer(inp.value.trim());
          row.appendChild(inp); row.appendChild(btn);
          box.appendChild(row);
          setTimeout(() => inp.focus(), 40);
        }}
        out.appendChild(box);
        out.scrollTop = out.scrollHeight;
      }}
      break;
    }}

    case 'pending_edit':
      document.getElementById('ap-path').textContent = ev.path;
      document.getElementById('ap-diff').innerHTML   = renderDiff(ev.diff);
      document.getElementById('overlay').classList.add('show');
      break;

    case 'final':
      ln('final-hdr', '\u2500\u2500 FINAL ANSWER ' + '\u2500'.repeat(40));
      ln('final', esc(ev.text));
      break;

    case 'max_steps':
      ln('err', '[max steps reached]');
      break;

    case 'err':
      ln('err', '[ERROR] ' + esc(ev.text || ''));
      break;

    case 'done':
      rbtn.disabled = false;
      setBadge('done', 'var(--green)');
      if (es) es.close();
      break;
  }}
}}

// ─ Toggle tool result panel ───────────────────────────────────────────────────

function toggleResult(btn) {{
  const panel = btn.closest('.ln.call').nextElementSibling;
  if (!panel || !panel.classList.contains('result-panel')) return;
  const open = panel.style.display !== 'none';
  panel.style.display = open ? 'none' : '';
  btn.textContent = open ? '\u25b6' : '\u25bc';
  if (!open) out.scrollTop = out.scrollHeight;
}}

// ─ Edit approval ──────────────────────────────────────────────────────────────

async function respond(ok) {{
  document.getElementById('overlay').classList.remove('show');
  await fetch(ok ? '/approve' : '/reject', {{method: 'POST'}});
}}

// ─ Ask-user answer ────────────────────────────────────────────────────────────

async function sendAnswer(val) {{
  if (!val) return;
  VIZ.setUserState('answered');
  const box = document.getElementById('ask-box');
  if (box) {{
    if (box.classList.contains('dq-card')) {{
      // Discovery card: keep it visible as a record, just remove the id so next
      // question can get a fresh ask-box, and append a compact answered line
      box.removeAttribute('id');
      const ans = document.createElement('div');
      ans.className = 'dq-answered';
      ans.textContent = val;
      box.appendChild(ans);
    }} else {{
      // Agent ask_user: replace box with a simple answered line
      const d = document.createElement('div');
      d.className = 'ln ask-ans';
      d.textContent = '\u203a ' + val;
      box.replaceWith(d);
    }}
  }}
  await fetch('/answer', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{answer: val}})
  }});
}}

// ─ Keyboard shortcuts ────────────────────────────────────────────────────────

document.getElementById('task').addEventListener('keydown', e => {{
  if (e.ctrlKey && e.key === 'Enter') run();
  if (e.ctrlKey && e.key === 'k')    out.innerHTML = '';
}});

VIZ.init();
</script>
</body>
</html>"""

HTML = _build_html()


# ── SSE stream ────────────────────────────────────────────────────────────────

@app.get("/validate_project")
async def validate_project(path: str):
    """Check whether a path is a valid, accessible directory."""
    import os as _os
    resolved = _os.path.abspath(path)
    if _os.path.isdir(resolved):
        return {"ok": True,  "resolved": resolved}
    return         {"ok": False, "resolved": resolved,
                    "error": "Path does not exist or is not a directory."}


@app.get("/stream")
async def stream(task: str, model: str = MODEL, edit_mode: str = "auto",
                 project_path: str = ""):
    log_q       = queue.Queue()
    plan_appr_q = queue.Queue()
    edit_appr_q = queue.Queue()
    ask_q       = queue.Queue()

    # Register queues so the approval/answer endpoints can send responses
    _active_plan_appr_q[0] = plan_appr_q
    _active_edit_appr_q[0] = edit_appr_q
    _active_ask_q[0]       = ask_q

    def on_event(ev: dict):
        log_q.put(ev)

    def plan_approval_fn(plan: dict) -> bool:
        return bool(plan_appr_q.get())

    def approval_fn(path: str, old: str, new: str, diff: str) -> bool:
        on_event({"type": "pending_edit", "path": path, "old": old, "new": new, "diff": diff})
        return bool(edit_appr_q.get())

    def ask_fn(question: str, choices: list, **extra) -> str:
        ev = {"type": "ask_user", "question": question, "choices": choices}
        ev.update(extra)
        on_event(ev)
        return str(ask_q.get())

    def worker():
        try:
            run_orchestrator(
                task,
                model=model,
                on_event=on_event,
                plan_approval_fn=plan_approval_fn,
                edit_approval_fn=approval_fn if edit_mode == "ask" else None,
                ask_user_fn=ask_fn,
                project_path=project_path or None,
            )
        except Exception as e:
            on_event({"type": "err", "text": str(e)})
        finally:
            on_event({"type": "done"})

    threading.Thread(target=worker, daemon=True).start()

    async def generate():
        loop = asyncio.get_event_loop()
        while True:
            ev = await loop.run_in_executor(None, log_q.get)
            yield f"data: {json.dumps(ev)}\n\n"
            if ev.get("type") == "done":
                break

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Plan approval endpoints ───────────────────────────────────────────────────

@app.post("/plan_approve")
def plan_approve():
    q = _active_plan_appr_q[0]
    if q: q.put(True)
    return {"ok": True}


@app.post("/plan_reject")
def plan_reject():
    q = _active_plan_appr_q[0]
    if q: q.put(False)
    return {"ok": True}


# ── Edit approval endpoints ───────────────────────────────────────────────────

@app.post("/approve")
def approve():
    q = _active_edit_appr_q[0]
    if q: q.put(True)
    return {"ok": True}


@app.post("/reject")
def reject():
    q = _active_edit_appr_q[0]
    if q: q.put(False)
    return {"ok": True}


# ── Ask-user answer endpoint ──────────────────────────────────────────────────

@app.post("/answer")
async def answer(req: Request):
    body = await req.json()
    q = _active_ask_q[0]
    if q: q.put(body.get("answer", ""))
    return {"ok": True}


# ── Session clear endpoint ────────────────────────────────────────────────────

@app.post("/clear")
def clear_session():
    return {"ok": True}


# ── Index ─────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def index():
    return HTML


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Multi-Agent Dev System")
    parser.add_argument(
        "--project", "-p",
        default=None,
        help="Path to the project directory the agents should work on. "
             "Defaults to the current working directory.",
    )
    parser.add_argument(
        "--port",
        default=7861,
        type=int,
        help="Port to run the web UI on (default: 7861).",
    )
    args = parser.parse_args()

    if args.project:
        project_path = os.path.abspath(args.project)
        if not os.path.isdir(project_path):
            print(f"[error] Project directory not found: {project_path}")
            raise SystemExit(1)
        os.chdir(project_path)

    project_dir = os.getcwd()
    print(f"Project : {project_dir}")
    print(f"Running \u2192 http://localhost:{args.port}")
    uvicorn.run(app, host="0.0.0.0", port=args.port, log_level="warning")
