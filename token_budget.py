"""Offline optional tokenizer; no model downloads or tokenizer auto-detection."""

import os
from pathlib import Path
from functools import lru_cache


@lru_cache(maxsize=2)
def _load(path, size, modified):
    from tokenizers import Tokenizer

    tokenizer = Tokenizer.from_file(path)
    tokenizer.no_truncation()
    tokenizer.no_padding()
    return tokenizer


def counter(args, estimate):
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
            return (
                lambda text: len(tokenizer.encode(text, add_special_tokens=False).ids),
                "tokenizer:" + model,
                None,
            )
        except Exception as exc:
            reason = "Offline tokenizer unavailable (" + type(exc).__name__ + ")."
    if strict:
        raise ValueError(reason + " Strict budget refused; configure a matching local tokenizer.")
    return estimate, "estimate: characters / 4; not a tokenizer", reason if model else None
