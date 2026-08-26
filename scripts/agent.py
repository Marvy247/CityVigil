"""Run the CityVigil agent and show its reasoning.

    CITYVIGIL_CACHE_MODE=replay python3 scripts/agent.py --show-trace
    python3 scripts/agent.py --question "who needs protecting tonight?" --hour 20

The trace is the point. Every decision is printed before the call it justifies, so
the layer choices, the branch on gap cause, and the stopping conditions are all
inspectable rather than asserted.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cityvigil import FortyGuardClient, Settings  # noqa: E402
from cityvigil.agent import AgentBudget, HeatResponseAgent  # noqa: E402

RULE = "=" * 78


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the CityVigil heat-response agent.")
    parser.add_argument(
        "--question",
        default="Who should we protect first, and what is the cheapest way to do it?",
    )
    parser.add_argument("--city", default="phoenix")
    parser.add_argument(
        "--hour",
        type=float,
        default=19.0,
        help="Hour of day at which protection is evaluated (default 19:00)",
    )
    parser.add_argument("--threshold-f", type=float, default=None)
    parser.add_argument("--max-credits", type=int, default=40_000)
    parser.add_argument("--show-trace", action="store_true", help="Print the full reasoning trace")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable output")
    args = parser.parse_args()

    settings = Settings.from_env()
    client = FortyGuardClient(settings)
    agent = HeatResponseAgent(client, budget=AgentBudget(max_credits=args.max_credits))

    if not args.json:
        print(RULE)
        print("CityVigil agent")
        print(RULE)
        print(f"question   : {args.question}")
        print(f"study area : {args.city}")
        print(f"evaluated  : {args.hour:g}:00 local")
        print(f"cache mode : {settings.cache_mode}")
        print(f"\ncapabilities ({len(agent.toolbox)}):")
        for tool in agent.toolbox.describe():
            cost = f"{tool['credits']:,} credits" if tool["credits"] else "no API cost"
            print(f"  - {tool['name']:<22} answers {tool['answers']} ({cost})")
        print()

    result = agent.run(
        args.question,
        city_key=args.city,
        evening_hour=args.hour,
        threshold_f=args.threshold_f,
    )

    if args.json:
        print(json.dumps(result.to_dict(), indent=2, default=str))
        return 0

    if args.show_trace:
        print(RULE)
        print("REASONING TRACE")
        print(RULE)
        print(result.trace.render())
        print()

    print(RULE)
    print("RECOMMENDATION")
    print(RULE)
    print(f"  {result.recommendation}")

    if result.degraded:
        print("\n  Degraded — the agent continued with less than full information:")
        for item in result.degraded:
            print(f"    - {item}")

    print()
    print(RULE)
    print("HOW IT GOT THERE")
    print(RULE)
    print(f"  steps taken      : {len(result.trace)}")
    print(f"  decisions made   : {len(result.trace.of_kind('decide'))}")
    print(f"  tools called     : {result.trace.tools_called()}")
    print(f"  recoveries       : {len(result.trace.of_kind('recover'))}")
    print(f"  credits spent    : {agent.budget.spent_credits:,} of {agent.budget.max_credits:,}")
    if not args.show_trace:
        print("\n  Re-run with --show-trace to see every decision and its reason.")

    out = Path("outputs")
    out.mkdir(parents=True, exist_ok=True)
    (out / "agent_run.json").write_text(
        json.dumps(result.to_dict(), indent=2, default=str), encoding="utf-8"
    )
    print("\nWrote outputs/agent_run.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
