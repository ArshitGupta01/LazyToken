"""Explicit task-finish checkpoint for clients without supported lifecycle hooks."""

import features


def complete_task(kn, args, conn):
    if not isinstance(args.get("attempts", ""), str):
        return {"error": "attempts must be text."}
    if args.get("outcome") not in ("success", "failure"):
        return {"error": "outcome must be success or failure."}
    for field in ("task", "resolution", "evidence"):
        if (
            not isinstance(args.get(field), str)
            or not args[field].strip()
            or len(args[field]) > 1200
        ):
            return {"error": field + " must be non-empty text up to 1200 characters."}
    if not args.get("paths"):
        return {"error": "Provide indexed evidence paths; completion cannot invent evidence."}
    # Caller supplies the actual lesson. No inference or automatic trust promotion.
    payload = {
        key: args[key]
        for key in (
            "project",
            "paths",
            "task",
            "evidence",
            "resolution",
            "problem",
            "attempts",
            "commit_ref",
        )
        if key in args
    }
    payload["attempts"] = (
        args.get("attempts", "") + "\nTask outcome (caller-reported): " + args["outcome"]
    ).strip()
    payload["kind"] = args.get("kind", "lesson")
    payload["name"] = args.get("name", args["task"][:160])
    payload["summary"] = args["resolution"]
    result = features.propose(kn, payload, conn)
    if "error" not in result:
        result["review_required"] = True
        result["outcome"] = args["outcome"]
        result["note"] = (
            "Pending suggestion only. Outcome is caller-reported; review the evidence before approving."
        )
    return result
