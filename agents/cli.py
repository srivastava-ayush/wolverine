"""Local interface for runs and explicit approvals."""
import argparse
import json
import os
from pathlib import Path

from agents.orchestrator import Orchestrator
from core.state import Store


def main():
    parser = argparse.ArgumentParser(description="Human-approved GitHub issue repair")
    sub = parser.add_subparsers(dest="action", required=True)
    start = sub.add_parser("investigate")
    start.add_argument("repo")
    start.add_argument("issue", type=int)
    start.add_argument("--requester", required=True)
    start.add_argument("--image", required=True, help="Prebuilt Docker image with dependencies installed")
    start.add_argument("--test-argv", required=True, help='JSON argv, e.g. ["python","-m","pytest","-q"]')
    show = sub.add_parser("show")
    show.add_argument("run_id")
    approval = sub.add_parser("approve")
    approval.add_argument("run_id")
    approval.add_argument("--requester", required=True)
    approval.add_argument("--diff-hash", required=True)
    args = parser.parse_args()
    store = Store(Path(os.getenv("HEALER_STATE_DIR", ".healer")))
    if args.action == "show":
        run = store.load(args.run_id)
        print(json.dumps(run.as_dict(), indent=2))
        if run.status == "awaiting_approval":
            print(f"\nInspect diff locally: git -C {store.directory(run.id) / 'checkout'} diff")
        return
    worker = Orchestrator(store)
    if args.action == "investigate":
        run = worker.investigate(args.repo, args.issue, args.requester,
                                 json.loads(args.test_argv), args.image)
    else:
        run = worker.approve(args.run_id, args.requester, args.diff_hash)
    print(json.dumps({"id": run.id, "status": run.status, "summary": run.summary,
                      "diff_hash": run.diff_hash, "pr_url": run.pr_url, "error": run.error}, indent=2))


if __name__ == "__main__":
    main()
