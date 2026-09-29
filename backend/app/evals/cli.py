"""
Evaluation CLI.

  uv run python -m app.evals.cli run --dataset evals/datasets/sample.jsonl \\
      --org <org-uuid> --kb <kb-uuid> --output report.json [--retrieval-only] [--agentic]

  uv run python -m app.evals.cli compare baseline.json candidate.json

`compare` exits 1 when any metric regressed, so it can gate CI.
"""

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

from app.evals.dataset import load_dataset
from app.evals.report import EvalReport, compare


def _print_summary(report: EvalReport) -> None:
    print(f"\n{report.dataset}  cases={report.total_cases} failed={report.failed_cases} "
          f"k={report.k} config={report.config}")
    for name, value in report.summary.items():
        print(f"  {name:22s} {'n/a' if value is None else value}")


async def _run(args: argparse.Namespace) -> int:
    from app.core.database import AsyncSessionLocal
    from app.evals.runner import run_eval

    report = await run_eval(
        AsyncSessionLocal,
        uuid.UUID(args.org),
        [uuid.UUID(k) for k in args.kb],
        load_dataset(args.dataset),
        dataset_name=Path(args.dataset).name,
        strategy=args.strategy,
        k=args.k,
        agentic=args.agentic,
        retrieval_only=args.retrieval_only,
        concurrency=args.concurrency,
    )
    if args.output:
        Path(args.output).write_text(report.model_dump_json(indent=2), encoding="utf-8")
    _print_summary(report)
    return 1 if report.failed_cases == report.total_cases else 0


def _compare(args: argparse.Namespace) -> int:
    base = EvalReport.model_validate_json(Path(args.baseline).read_text(encoding="utf-8"))
    cand = EvalReport.model_validate_json(Path(args.candidate).read_text(encoding="utf-8"))
    deltas = compare(base.summary, cand.summary)
    for d in deltas:
        flag = "REGRESSED" if d.regressed else "ok"
        print(f"  {d.metric:22s} {d.baseline:>10} -> {d.candidate:<10} ({d.delta:+}) {flag}")
    regressed = [d.metric for d in deltas if d.regressed]
    if regressed:
        print(f"\nRegressions: {', '.join(regressed)}")
        return 1
    print("\nNo regressions.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="app.evals.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run")
    run.add_argument("--dataset", required=True)
    run.add_argument("--org", required=True)
    run.add_argument("--kb", required=True, nargs="+")
    run.add_argument("--strategy", default="hybrid",
                     choices=["semantic", "keyword", "hybrid", "tree"])
    run.add_argument("--k", type=int, default=5)
    run.add_argument("--agentic", action="store_true")
    run.add_argument("--retrieval-only", action="store_true")
    run.add_argument("--concurrency", type=int, default=2)
    run.add_argument("--output")

    cmp = sub.add_parser("compare")
    cmp.add_argument("baseline")
    cmp.add_argument("candidate")

    args = parser.parse_args()
    code = asyncio.run(_run(args)) if args.cmd == "run" else _compare(args)
    sys.exit(code)


if __name__ == "__main__":
    main()
