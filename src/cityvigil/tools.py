"""Tools the agent can call, and the trace that records why it called them.

Design decision: no LLM
-----------------------
The reasoning here is an explicit **policy**, not a language model. That is a
deliberate trade, and worth defending rather than hiding.

An LLM planner would look more impressive in a demo. It would also be
non-deterministic, untestable, dependent on a second API key, and — the fatal
objection for this project — capable of hallucinating a layer choice. CityVigil's
entire credibility argument is that it never asks the wrong question of the
temperature API. A planner that *might* pick ``tcm`` when the question needs
``exceedance`` reintroduces exactly the failure mode the organisers warned about,
and the audit trail would faithfully record a fabricated justification.

So the policy is code: readable, unit-tested, and identical on every run. Every
decision still carries a written rationale, and the planner is swappable behind
:class:`Planner` if an LLM is ever wanted.

What makes this agentic rather than a pipeline
---------------------------------------------
The agent is not a fixed sequence. It:

* chooses which analysis layer answers the question it was asked;
* stops early when the evidence says there is nothing to act on;
* degrades to a reduced answer when a data source is unavailable, rather than
  failing;
* branches on the *diagnosis* — if the gap is caused by closing times it
  simulates extending hours, if by distance it plans new sites, and it says which
  and why;
* enforces its own step and credit budget.

Those are real decision points with consequences, and the trace shows them.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from .errors import CityVigilError

StepKind = Literal["decide", "call", "observe", "recover", "conclude", "budget"]


@dataclass(frozen=True)
class TraceStep:
    """One entry in the agent's visible reasoning trace."""

    step: int
    kind: StepKind
    summary: str
    rationale: str = ""
    tool: str | None = None
    args: dict[str, Any] = field(default_factory=dict)
    result: str | None = None
    duration_s: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "kind": self.kind,
            "summary": self.summary,
            "rationale": self.rationale,
            "tool": self.tool,
            "args": self.args,
            "result": self.result,
            "duration_s": None if self.duration_s is None else round(self.duration_s, 2),
        }

    def render(self) -> str:
        """Human-readable line(s) for CLI output."""
        head = f"[{self.step:>2}] {self.kind.upper():<8} {self.summary}"
        lines = [head]
        if self.tool:
            arg_text = ", ".join(f"{k}={v!r}" for k, v in self.args.items())
            lines.append(f"{'':<14}tool: {self.tool}({arg_text})")
        if self.result:
            lines.append(f"{'':<14}-> {self.result}")
        if self.rationale:
            lines.append(f"{'':<14}why: {self.rationale}")
        return "\n".join(lines)


class Trace:
    """Ordered, append-only record of the agent's decisions and calls."""

    def __init__(self) -> None:
        self._steps: list[TraceStep] = []
        self._counter = 0

    def _next(self) -> int:
        self._counter += 1
        return self._counter

    def add(
        self,
        kind: StepKind,
        summary: str,
        *,
        rationale: str = "",
        tool: str | None = None,
        args: dict[str, Any] | None = None,
        result: str | None = None,
        duration_s: float | None = None,
    ) -> TraceStep:
        entry = TraceStep(
            step=self._next(),
            kind=kind,
            summary=summary,
            rationale=rationale,
            tool=tool,
            args=args or {},
            result=result,
            duration_s=duration_s,
        )
        self._steps.append(entry)
        return entry

    def __len__(self) -> int:
        return len(self._steps)

    def __iter__(self):
        return iter(self._steps)

    @property
    def steps(self) -> list[TraceStep]:
        return list(self._steps)

    def of_kind(self, kind: StepKind) -> list[TraceStep]:
        return [s for s in self._steps if s.kind == kind]

    def tools_called(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for s in self.of_kind("call"):
            if s.tool:
                counts[s.tool] = counts.get(s.tool, 0) + 1
        return dict(sorted(counts.items()))

    def to_list(self) -> list[dict[str, Any]]:
        return [s.to_dict() for s in self._steps]

    def render(self) -> str:
        return "\n".join(s.render() for s in self._steps)


class ToolError(CityVigilError):
    """A tool failed in a way the agent may be able to recover from."""


@dataclass
class Tool:
    """A capability the agent can invoke.

    ``answers`` states, in plain language, the question this tool addresses. The
    policy matches on it, and it is what gets written into the trace as the reason
    the tool was selected — so a tool that cannot say what it answers cannot be
    chosen.
    """

    name: str
    answers: str
    run: Callable[..., Any]
    #: Approximate credit cost, so the agent can respect a budget.
    credits: int = 0

    def __call__(self, **kwargs: Any) -> Any:
        return self.run(**kwargs)


class ToolBox:
    """Registry of available tools, with lookup by name."""

    def __init__(self, tools: list[Tool] | None = None) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools or []:
            self.register(tool)

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool {tool.name!r} is already registered")
        self._tools[tool.name] = tool

    def __contains__(self, name: object) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError:
            raise ToolError(
                f"no tool named {name!r}; available: {sorted(self._tools)}"
            ) from None

    @property
    def names(self) -> list[str]:
        return sorted(self._tools)

    def describe(self) -> list[dict[str, Any]]:
        """What the agent can do, for the trace header and the UI."""
        return [
            {"name": t.name, "answers": t.answers, "credits": t.credits}
            for t in (self._tools[n] for n in self.names)
        ]

    def invoke(self, name: str, trace: Trace, **kwargs: Any) -> Any:
        """Call a tool, timing it and recording the call in the trace.

        Failures are recorded as ``recover`` steps and re-raised as
        :class:`ToolError` so the policy can decide what to do rather than crash.
        """
        tool = self.get(name)
        started = time.monotonic()
        try:
            value = tool(**kwargs)
        except Exception as exc:  # noqa: BLE001 - the policy decides how to handle it
            trace.add(
                "recover",
                f"{name} failed",
                rationale=f"{type(exc).__name__}: {exc}",
                tool=name,
                args=kwargs,
                duration_s=time.monotonic() - started,
            )
            raise ToolError(f"{name} failed: {exc}") from exc
        return value
