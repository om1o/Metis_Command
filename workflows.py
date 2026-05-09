"""
Workflow engine — Phase 15.

Workflows are directed graphs of nodes connected by edges.
Each node is one of: prompt, specialist, condition, loop, human_review.
Stored as JSON in identity/workflows/.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

_WORKFLOW_DIR = Path(__file__).parent / "identity" / "workflows"
_WORKFLOW_DIR.mkdir(parents=True, exist_ok=True)

# ── Node types ──────────────────────────────────────────────────────────────

NODE_TYPES = {
    "prompt":       {"label": "Prompt",        "icon": "💬", "color": "#7C3AED", "desc": "Send a prompt to the Manager"},
    "specialist":   {"label": "Specialist",    "icon": "🤖", "color": "#3B82F6", "desc": "Delegate to a specialist agent"},
    "condition":    {"label": "Condition",     "icon": "❓", "color": "#F59E0B", "desc": "Branch on a yes/no check"},
    "loop":         {"label": "Loop",          "icon": "🔁", "color": "#22C55E", "desc": "Repeat a sub-graph N times"},
    "human_review": {"label": "Human Review",  "icon": "👤", "color": "#FB7185", "desc": "Pause and wait for user approval"},
    "output":       {"label": "Output",        "icon": "📤", "color": "#A78BFA", "desc": "Collect and emit the final result"},
}

SPECIALIST_OPTIONS = ["researcher", "coder", "thinker", "scholar"]

# ── Data model ───────────────────────────────────────────────────────────────

@dataclass
class WorkflowNode:
    id: str
    type: str          # prompt | specialist | condition | loop | human_review | output
    label: str
    config: dict       # type-specific config
    x: float = 100.0
    y: float = 100.0


@dataclass
class WorkflowEdge:
    id: str
    source: str        # node id
    target: str        # node id
    label: str = ""    # e.g. "yes" / "no" for condition branches


@dataclass
class Workflow:
    id: str
    name: str
    description: str = ""
    nodes: list[WorkflowNode] = field(default_factory=list)
    edges: list[WorkflowEdge] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    run_count: int = 0
    last_run_at: float | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "nodes": [asdict(n) for n in self.nodes],
            "edges": [asdict(e) for e in self.edges],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "run_count": self.run_count,
            "last_run_at": self.last_run_at,
        }

    @staticmethod
    def from_dict(d: dict) -> "Workflow":
        nodes = [WorkflowNode(**n) for n in d.get("nodes", [])]
        edges = [WorkflowEdge(**e) for e in d.get("edges", [])]
        return Workflow(
            id=d["id"],
            name=d.get("name", "Untitled"),
            description=d.get("description", ""),
            nodes=nodes,
            edges=edges,
            created_at=d.get("created_at", time.time()),
            updated_at=d.get("updated_at", time.time()),
            run_count=d.get("run_count", 0),
            last_run_at=d.get("last_run_at"),
        )


# ── Persistence ──────────────────────────────────────────────────────────────

def _path(wf_id: str) -> Path:
    safe = "".join(c for c in wf_id if c.isalnum() or c in "-_")
    return _WORKFLOW_DIR / f"{safe}.json"


def save_workflow(wf: Workflow) -> Workflow:
    wf.updated_at = time.time()
    _path(wf.id).write_text(json.dumps(wf.to_dict(), indent=2), encoding="utf-8")
    return wf


def load_workflow(wf_id: str) -> Workflow | None:
    p = _path(wf_id)
    if not p.exists():
        return None
    return Workflow.from_dict(json.loads(p.read_text(encoding="utf-8")))


def list_workflows() -> list[Workflow]:
    out = []
    for p in sorted(_WORKFLOW_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            out.append(Workflow.from_dict(json.loads(p.read_text(encoding="utf-8"))))
        except Exception:
            pass
    return out


def delete_workflow(wf_id: str) -> bool:
    p = _path(wf_id)
    if p.exists():
        p.unlink()
        return True
    return False


# ── Built-in templates ───────────────────────────────────────────────────────

_TEMPLATES: list[dict] = [
    {
        "id": "tpl-research-summarize",
        "name": "Research → Summarize",
        "description": "The Researcher gathers information, then the Thinker condenses it into a clear summary.",
        "icon": "🔬",
        "nodes": [
            {"id": "n1", "type": "prompt",      "label": "Enter topic",       "config": {"prompt": "What topic should I research?"},         "x": 80,  "y": 120},
            {"id": "n2", "type": "specialist",   "label": "Researcher",        "config": {"specialist": "researcher"},                        "x": 300, "y": 120},
            {"id": "n3", "type": "specialist",   "label": "Thinker",           "config": {"specialist": "thinker"},                           "x": 520, "y": 120},
            {"id": "n4", "type": "output",       "label": "Summary",           "config": {"format": "markdown"},                              "x": 740, "y": 120},
        ],
        "edges": [
            {"id": "e1", "source": "n1", "target": "n2", "label": ""},
            {"id": "e2", "source": "n2", "target": "n3", "label": ""},
            {"id": "e3", "source": "n3", "target": "n4", "label": ""},
        ],
    },
    {
        "id": "tpl-code-review",
        "name": "Code → Review → Test",
        "description": "Coder writes the solution, Scholar reviews it, Thinker suggests tests.",
        "icon": "💻",
        "nodes": [
            {"id": "n1", "type": "prompt",      "label": "Code task",         "config": {"prompt": "Describe what code you need."},            "x": 80,  "y": 120},
            {"id": "n2", "type": "specialist",   "label": "Coder",             "config": {"specialist": "coder"},                              "x": 300, "y": 120},
            {"id": "n3", "type": "specialist",   "label": "Scholar (Review)",  "config": {"specialist": "scholar"},                            "x": 520, "y": 60},
            {"id": "n4", "type": "specialist",   "label": "Thinker (Tests)",   "config": {"specialist": "thinker"},                            "x": 520, "y": 200},
            {"id": "n5", "type": "output",       "label": "Result",            "config": {"format": "markdown"},                               "x": 740, "y": 120},
        ],
        "edges": [
            {"id": "e1", "source": "n1", "target": "n2", "label": ""},
            {"id": "e2", "source": "n2", "target": "n3", "label": ""},
            {"id": "e3", "source": "n2", "target": "n4", "label": ""},
            {"id": "e4", "source": "n3", "target": "n5", "label": ""},
            {"id": "e5", "source": "n4", "target": "n5", "label": ""},
        ],
    },
    {
        "id": "tpl-plan-execute-review",
        "name": "Plan → Execute → Human Review",
        "description": "Thinker creates a plan, Coder executes it, then you approve before the result is finalized.",
        "icon": "📋",
        "nodes": [
            {"id": "n1", "type": "prompt",      "label": "Goal",              "config": {"prompt": "What would you like to accomplish?"},      "x": 80,  "y": 120},
            {"id": "n2", "type": "specialist",   "label": "Thinker (Plan)",   "config": {"specialist": "thinker"},                              "x": 300, "y": 120},
            {"id": "n3", "type": "specialist",   "label": "Coder (Execute)",  "config": {"specialist": "coder"},                               "x": 520, "y": 120},
            {"id": "n4", "type": "human_review", "label": "Approve?",         "config": {"message": "Please review the plan before finalizing."}, "x": 740, "y": 120},
            {"id": "n5", "type": "output",       "label": "Final result",     "config": {"format": "markdown"},                               "x": 960, "y": 120},
        ],
        "edges": [
            {"id": "e1", "source": "n1", "target": "n2", "label": ""},
            {"id": "e2", "source": "n2", "target": "n3", "label": ""},
            {"id": "e3", "source": "n3", "target": "n4", "label": ""},
            {"id": "e4", "source": "n4", "target": "n5", "label": "approved"},
        ],
    },
    {
        "id": "tpl-daily-briefing",
        "name": "Daily Briefing",
        "description": "Researcher pulls news, Thinker writes a summary, Scholar formats the daily report.",
        "icon": "☀️",
        "nodes": [
            {"id": "n1", "type": "prompt",      "label": "Topics",            "config": {"prompt": "What topics should today's briefing cover?"},  "x": 80,  "y": 120},
            {"id": "n2", "type": "specialist",   "label": "Researcher",       "config": {"specialist": "researcher"},                              "x": 300, "y": 120},
            {"id": "n3", "type": "specialist",   "label": "Thinker",          "config": {"specialist": "thinker"},                                 "x": 520, "y": 120},
            {"id": "n4", "type": "specialist",   "label": "Scholar",          "config": {"specialist": "scholar"},                                 "x": 740, "y": 120},
            {"id": "n5", "type": "output",       "label": "Briefing",         "config": {"format": "markdown"},                                    "x": 960, "y": 120},
        ],
        "edges": [
            {"id": "e1", "source": "n1", "target": "n2", "label": ""},
            {"id": "e2", "source": "n2", "target": "n3", "label": ""},
            {"id": "e3", "source": "n3", "target": "n4", "label": ""},
            {"id": "e4", "source": "n4", "target": "n5", "label": ""},
        ],
    },
    {
        "id": "tpl-competitor-analysis",
        "name": "Competitor Analysis",
        "description": "Researcher gathers competitor data, Scholar synthesizes insights, Thinker produces strategic recommendations.",
        "icon": "🔭",
        "nodes": [
            {"id": "n1", "type": "prompt",      "label": "Company / market",  "config": {"prompt": "Which company or market should I analyze?"},   "x": 80,  "y": 120},
            {"id": "n2", "type": "specialist",   "label": "Researcher",       "config": {"specialist": "researcher"},                              "x": 300, "y": 80},
            {"id": "n3", "type": "specialist",   "label": "Scholar",          "config": {"specialist": "scholar"},                                 "x": 520, "y": 80},
            {"id": "n4", "type": "specialist",   "label": "Thinker (Strategy)","config": {"specialist": "thinker"},                               "x": 520, "y": 200},
            {"id": "n5", "type": "output",       "label": "Analysis report",  "config": {"format": "markdown"},                                   "x": 740, "y": 120},
        ],
        "edges": [
            {"id": "e1", "source": "n1", "target": "n2", "label": ""},
            {"id": "e2", "source": "n2", "target": "n3", "label": ""},
            {"id": "e3", "source": "n2", "target": "n4", "label": ""},
            {"id": "e4", "source": "n3", "target": "n5", "label": ""},
            {"id": "e5", "source": "n4", "target": "n5", "label": ""},
        ],
    },
    {
        "id": "tpl-bug-triage",
        "name": "Bug Triage → Fix → Verify",
        "description": "Thinker diagnoses the bug, Coder writes the fix, Scholar checks correctness and edge cases.",
        "icon": "🐛",
        "nodes": [
            {"id": "n1", "type": "prompt",      "label": "Bug description",   "config": {"prompt": "Describe the bug or paste the error message."},  "x": 80,  "y": 120},
            {"id": "n2", "type": "specialist",   "label": "Thinker (Diagnose)","config": {"specialist": "thinker"},                                   "x": 300, "y": 120},
            {"id": "n3", "type": "specialist",   "label": "Coder (Fix)",       "config": {"specialist": "coder"},                                     "x": 520, "y": 120},
            {"id": "n4", "type": "specialist",   "label": "Scholar (Verify)",  "config": {"specialist": "scholar"},                                   "x": 740, "y": 120},
            {"id": "n5", "type": "output",       "label": "Fix report",        "config": {"format": "markdown"},                                      "x": 960, "y": 120},
        ],
        "edges": [
            {"id": "e1", "source": "n1", "target": "n2", "label": ""},
            {"id": "e2", "source": "n2", "target": "n3", "label": ""},
            {"id": "e3", "source": "n3", "target": "n4", "label": ""},
            {"id": "e4", "source": "n4", "target": "n5", "label": ""},
        ],
    },
    {
        "id": "tpl-content-pipeline",
        "name": "Content Pipeline",
        "description": "Researcher gathers sources, Scholar drafts the content, Thinker edits for tone and clarity, then human approval.",
        "icon": "✍️",
        "nodes": [
            {"id": "n1", "type": "prompt",      "label": "Content brief",     "config": {"prompt": "What content do you need? (topic, audience, format)"},  "x": 80,  "y": 120},
            {"id": "n2", "type": "specialist",   "label": "Researcher",       "config": {"specialist": "researcher"},                                       "x": 300, "y": 120},
            {"id": "n3", "type": "specialist",   "label": "Scholar (Draft)",   "config": {"specialist": "scholar"},                                          "x": 520, "y": 120},
            {"id": "n4", "type": "specialist",   "label": "Thinker (Edit)",    "config": {"specialist": "thinker"},                                          "x": 740, "y": 120},
            {"id": "n5", "type": "human_review", "label": "Approve draft?",   "config": {"message": "Review the draft before publishing."},                  "x": 960, "y": 120},
            {"id": "n6", "type": "output",       "label": "Final content",    "config": {"format": "markdown"},                                             "x": 1180,"y": 120},
        ],
        "edges": [
            {"id": "e1", "source": "n1", "target": "n2", "label": ""},
            {"id": "e2", "source": "n2", "target": "n3", "label": ""},
            {"id": "e3", "source": "n3", "target": "n4", "label": ""},
            {"id": "e4", "source": "n4", "target": "n5", "label": ""},
            {"id": "e5", "source": "n5", "target": "n6", "label": "approved"},
        ],
    },
    {
        "id": "tpl-deep-research",
        "name": "Deep Research Loop",
        "description": "Researcher runs multiple passes, each Thinker pass refines the findings until a comprehensive answer is built.",
        "icon": "🧠",
        "nodes": [
            {"id": "n1", "type": "prompt",      "label": "Research question", "config": {"prompt": "What question needs deep research?"},           "x": 80,  "y": 120},
            {"id": "n2", "type": "specialist",   "label": "Researcher (Pass 1)","config": {"specialist": "researcher"},                              "x": 300, "y": 80},
            {"id": "n3", "type": "specialist",   "label": "Researcher (Pass 2)","config": {"specialist": "researcher"},                              "x": 300, "y": 200},
            {"id": "n4", "type": "specialist",   "label": "Thinker (Synthesize)","config": {"specialist": "thinker"},                               "x": 540, "y": 120},
            {"id": "n5", "type": "specialist",   "label": "Scholar (Format)",  "config": {"specialist": "scholar"},                                 "x": 760, "y": 120},
            {"id": "n6", "type": "output",       "label": "Research report",   "config": {"format": "markdown"},                                    "x": 980, "y": 120},
        ],
        "edges": [
            {"id": "e1", "source": "n1", "target": "n2", "label": ""},
            {"id": "e2", "source": "n1", "target": "n3", "label": ""},
            {"id": "e3", "source": "n2", "target": "n4", "label": ""},
            {"id": "e4", "source": "n3", "target": "n4", "label": ""},
            {"id": "e5", "source": "n4", "target": "n5", "label": ""},
            {"id": "e6", "source": "n5", "target": "n6", "label": ""},
        ],
    },
]


def list_templates() -> list[dict]:
    return _TEMPLATES


# ── Workflow runner ───────────────────────────────────────────────────────────

class WorkflowRunResult:
    def __init__(self):
        self.steps: list[dict] = []
        self.output: str = ""
        self.error: str | None = None
        self.duration_ms: int = 0

    def to_dict(self) -> dict:
        return {
            "steps": self.steps,
            "output": self.output,
            "error": self.error,
            "duration_ms": self.duration_ms,
        }


def run_workflow(wf_id: str, inputs: dict[str, Any]) -> WorkflowRunResult:
    """Execute a workflow synchronously. Returns a RunResult."""
    result = WorkflowRunResult()
    t0 = time.time()

    wf = load_workflow(wf_id)
    if not wf:
        result.error = f"Workflow {wf_id!r} not found"
        result.duration_ms = int((time.time() - t0) * 1000)
        return result

    # Build adjacency map
    children: dict[str, list[str]] = {n.id: [] for n in wf.nodes}
    for e in wf.edges:
        children.setdefault(e.source, []).append(e.target)

    # Find start node (no incoming edges)
    targets = {e.target for e in wf.edges}
    roots = [n for n in wf.nodes if n.id not in targets]
    if not roots:
        roots = wf.nodes[:1]

    context: dict[str, str] = dict(inputs)
    visited: set[str] = set()

    def _node_by_id(nid: str) -> WorkflowNode | None:
        return next((n for n in wf.nodes if n.id == nid), None)

    def _execute_node(node: WorkflowNode) -> str:
        """Run a single node and return its output string."""
        if node.type == "prompt":
            prompt_text = node.config.get("prompt", "")
            user_override = inputs.get(node.id) or inputs.get("prompt") or ""
            return user_override or prompt_text

        if node.type == "specialist":
            specialist = node.config.get("specialist", "thinker")
            prev_output = context.get("__last__", "")
            prompt_for_specialist = (
                inputs.get("goal") or inputs.get("prompt") or prev_output or "Proceed."
            )
            try:
                from brain_engine import stream_chat
                chunks = []
                for chunk in stream_chat(prompt_for_specialist, role=specialist):
                    if isinstance(chunk, dict):
                        chunks.append(chunk.get("content", ""))
                    else:
                        chunks.append(str(chunk))
                return "".join(chunks).strip()
            except Exception as e:
                return f"[{specialist} error: {e}]"

        if node.type == "human_review":
            msg = node.config.get("message", "Human review required.")
            return f"[Human review paused: {msg}]"

        if node.type == "condition":
            check = node.config.get("check", "")
            prev = context.get("__last__", "")
            passed = bool(check and check.lower() in prev.lower()) if check else True
            return "yes" if passed else "no"

        if node.type == "loop":
            iterations = int(node.config.get("iterations", 2))
            return f"[Loop: {iterations} iterations scheduled]"

        if node.type == "output":
            return context.get("__last__", "")

        return ""

    def _traverse(node: WorkflowNode):
        if node.id in visited:
            return
        visited.add(node.id)
        step_out = _execute_node(node)
        context["__last__"] = step_out
        context[node.id] = step_out
        result.steps.append({
            "node_id": node.id,
            "node_type": node.type,
            "label": node.label,
            "output": step_out[:2000],
        })
        for child_id in children.get(node.id, []):
            child = _node_by_id(child_id)
            if child:
                _traverse(child)

    try:
        for root in roots:
            _traverse(root)
        result.output = context.get("__last__", "")
    except Exception as e:
        result.error = str(e)

    # Update run stats
    wf.run_count += 1
    wf.last_run_at = time.time()
    save_workflow(wf)

    result.duration_ms = int((time.time() - t0) * 1000)
    return result
