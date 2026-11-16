"""Compute retrieval metrics from manually prepared labels and predictions; does not run agents."""

from __future__ import annotations
import argparse
import json
import math
import sys
from pathlib import Path


def evaluate(cases, k=5):
    if not isinstance(cases, list) or not cases:
        raise ValueError("cases must be a non-empty list")
    if isinstance(k, bool) or not isinstance(k, int) or not 1 <= k <= 100:
        raise ValueError("k must be 1–100")
    details = []
    ids = set()
    labels = {}
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("id"), str) or not case["id"]:
            raise ValueError("Each case needs an id")
        method = case.get("method", "default")
        if not isinstance(method, str) or not method.strip():
            raise ValueError("method must be non-empty text")
        key = (case["id"], method)
        if key in ids:
            raise ValueError("Duplicate case id and method")
        ids.add(key)
        relevant = case.get("relevant")
        predicted = case.get("predicted")
        abstained = case.get("abstained", False)
        tokens = case.get("estimated_tokens")
        if (
            not isinstance(relevant, list)
            or not isinstance(predicted, list)
            or any(not isinstance(x, str) or not x for x in relevant + predicted)
        ):
            raise ValueError("relevant and predicted must be lists of non-empty IDs")
        if len(set(relevant)) != len(relevant) or len(set(predicted)) != len(predicted):
            raise ValueError("Duplicate IDs are not allowed")
        if case["id"] in labels and labels[case["id"]] != set(relevant):
            raise ValueError("Methods must use the same relevance labels for a case")
        labels[case["id"]] = set(relevant)
        if not isinstance(abstained, bool) or (abstained and predicted):
            raise ValueError("Abstained cases cannot include predictions")
        if tokens is not None and (
            isinstance(tokens, bool) or not isinstance(tokens, int) or tokens < 0
        ):
            raise ValueError("estimated_tokens must be a non-negative integer or null")
        hits = [1 if x in set(relevant) else 0 for x in predicted[:k]]
        precision = sum(hits) / k
        recall = sum(hits) / len(relevant) if relevant else None
        first = next((i + 1 for i, v in enumerate(hits) if v), None)
        dcg = sum(hit / math.log2(i + 2) for i, hit in enumerate(hits))
        ideal = sum(1 / math.log2(i + 2) for i in range(min(len(relevant), k)))
        details.append(
            {
                "id": case["id"],
                "method": method,
                "precision_at_k": precision,
                "recall_at_k": recall,
                "reciprocal_rank": (1 / first if first else 0) if relevant else None,
                "ndcg_at_k": dcg / ideal if ideal else None,
                "abstention_correct": abstained == (not bool(relevant)),
                "estimated_tokens": tokens,
            }
        )

    methods_seen = {method for _, method in ids}
    if any(
        {case_id for case_id, name in ids if name == method} != set(labels)
        for method in methods_seen
    ):
        raise ValueError("All methods must evaluate the same case IDs")

    def mean(field, items=details):
        values = [x[field] for x in items if x[field] is not None]
        return sum(values) / len(values) if values else None

    methods = {}
    for method in sorted({x["method"] for x in details}):
        group = [x for x in details if x["method"] == method]
        methods[method] = {
            "cases": len(group),
            "precision_at_k": mean("precision_at_k", group),
            "recall_at_k": mean("recall_at_k", group),
            "mrr_at_k": mean("reciprocal_rank", group),
            "ndcg_at_k": mean("ndcg_at_k", group),
            "abstention_accuracy": sum(x["abstention_correct"] for x in group) / len(group),
            "estimated_tokens_mean": mean("estimated_tokens", group),
        }
    return {
        "k": k,
        "cases": len(details),
        "precision_at_k": mean("precision_at_k"),
        "recall_at_k": mean("recall_at_k"),
        "mrr_at_k": mean("reciprocal_rank"),
        "ndcg_at_k": mean("ndcg_at_k"),
        "abstention_accuracy": sum(x["abstention_correct"] for x in details) / len(details),
        "estimated_tokens_mean": mean("estimated_tokens"),
        "methods": methods,
        "details": details,
        "note": "Metrics use supplied labels and predictions; token counts are estimates. No coding tasks are executed.",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="JSON object with a cases array")
    parser.add_argument("--k", type=int, default=5)
    args = parser.parse_args(argv)
    try:
        payload = json.loads(Path(args.input).read_text(encoding="utf-8-sig"))
        print(json.dumps(evaluate(payload["cases"], args.k), indent=2, ensure_ascii=False))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
