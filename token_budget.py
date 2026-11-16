"""Offline optional tokenizer; no model downloads or tokenizer auto-detection."""

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

CHAT_FRAMING_TOKENS_PER_TURN = 25


class CounterResult(tuple):
    """3-tuple subclass preserving (count_fn, budget_type, fallback) while providing structured metadata."""

    def __new__(
        cls,
        count: Callable[[str], int],
        budget_type: str,
        fallback: str | None,
        is_approximate: bool = True,
        fidelity: str = "approximate_chars_div_4",
        note: str = "",
    ) -> "CounterResult":
        inst = super().__new__(cls, (count, budget_type, fallback))
        inst.count = count
        inst.budget_type = budget_type
        inst.fallback = fallback
        inst.is_approximate = is_approximate
        inst.fidelity = fidelity
        inst.note = note
        return inst

    @property
    def indicators(self) -> dict[str, Any]:
        return {
            "is_approximate": self.is_approximate,
            "fidelity": self.fidelity,
            "note": self.note,
        }


@lru_cache(maxsize=4)
def mcp_schema_overhead(compact: bool = False) -> int:
    """Returns tool catalog token count (~713 compact, ~2,371 full) from mcp_schema.py."""
    import mcp_schema

    tools = mcp_schema.mcp_tools(compact=bool(compact))
    return len(json.dumps(tools)) // 4


def chat_framing_overhead(turns: int = 1) -> int:
    """Returns chat envelope framing tokens (~25 per turn). Clamps negative turns to 0."""
    try:
        t = int(turns)
    except (ValueError, TypeError):
        t = 1
    return max(0, t) * CHAT_FRAMING_TOKENS_PER_TURN


def token_accounting(
    payload_tokens: int,
    compact_mcp: bool | None = False,
    model: str | None = None,
    is_approx: bool = True,
    turns: int = 1,
) -> dict[str, Any]:
    """Returns structured token accounting separating payload from MCP schema overhead and chat framing."""
    try:
        safe_payload = max(0, int(payload_tokens))
    except (ValueError, TypeError):
        safe_payload = 0

    schema_tax = None if compact_mcp is None else mcp_schema_overhead(compact=compact_mcp)
    framing_tax = chat_framing_overhead(turns=turns)
    total_footprint = None if schema_tax is None else safe_payload + schema_tax + framing_tax

    is_approximate = bool(is_approx)
    fidelity = "approximate_chars_div_4" if is_approximate else "exact_offline_tokenizer"

    if is_approximate:
        estimation_note = "approximate chars/4 heuristic"
    else:
        estimation_note = (
            f"exact offline tokenizer ({model})" if model else "exact offline tokenizer"
        )

    return {
        "payload_tokens": safe_payload,
        "mcp_schema_overhead_tokens": schema_tax,
        "chat_framing_overhead_tokens": framing_tax,
        "total_context_footprint_tokens": total_footprint,
        "is_approximate": is_approximate,
        "fidelity": fidelity,
        "budget_scope": "payload",
        "estimation_note": estimation_note,
        "overhead_note": "Schema and framing are estimates; schema is unknown unless the catalog is supplied.",
        "total_is_approximate": True,
    }


@lru_cache(maxsize=2)
def _load(path, size, modified):
    from tokenizers import Tokenizer

    tokenizer = Tokenizer.from_file(path)
    tokenizer.no_truncation()
    tokenizer.no_padding()
    return tokenizer


def counter(args: dict[str, Any], estimate: Callable[[str], int]) -> CounterResult:
    """Configures tokenizer counter, preserving 3-tuple return with structured attributes."""
    model = args.get("model")
    strict = args.get("strict_budget", False)
    if not isinstance(strict, bool) or (
        model is not None and (not isinstance(model, str) or not model.strip() or len(model) > 200)
    ):
        raise ValueError("model must be non-empty text and strict_budget must be boolean.")

    configured = os.environ.get("LAZYTOKEN_TOKENIZER_MODEL")
    source = os.environ.get("LAZYTOKEN_TOKENIZER_FILE")
    reason = "No matching offline tokenizer configured."

    if model and configured == model and source:
        try:
            path = Path(source).resolve()
            stat = path.stat()
            tokenizer = _load(str(path), stat.st_size, stat.st_mtime_ns)
            count_fn = lambda text: len(tokenizer.encode(text, add_special_tokens=False).ids)
            count_fn.is_approximate = False
            count_fn.fidelity = "exact_offline_tokenizer"
            count_fn.budget_type = "tokenizer:" + model
            count_fn.note = f"Offline tokenizer for {model}."
            return CounterResult(
                count_fn,
                "tokenizer:" + model,
                None,
                is_approximate=False,
                fidelity="exact_offline_tokenizer",
                note=f"Offline tokenizer for {model}.",
            )
        except Exception as exc:
            reason = "Offline tokenizer unavailable (" + type(exc).__name__ + ")."

    if strict:
        raise ValueError(reason + " Strict budget refused; configure a matching local tokenizer.")

    fallback_reason = reason if model else None
    count_fn = estimate
    try:
        count_fn.is_approximate = True
        count_fn.fidelity = "approximate_chars_div_4"
        count_fn.budget_type = "estimate: characters / 4; not a tokenizer"
        count_fn.note = "Character-based heuristic (chars/4); approximate planning estimate, not provider-exact."
    except Exception:
        pass

    return CounterResult(
        count_fn,
        "estimate: characters / 4; not a tokenizer",
        fallback_reason,
        is_approximate=True,
        fidelity="approximate_chars_div_4",
        note="Character-based heuristic (chars/4); approximate planning estimate, not provider-exact.",
    )
