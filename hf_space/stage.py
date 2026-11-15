"""Create a new self-contained Space directory without publishing it."""

import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULES = (
    "kn.py",
    "broker.py",
    "features.py",
    "learning.py",
    "data_ops.py",
    "token_budget.py",
    "mcp_schema.py",
    "source_index.py",
    "frameworks.py",
    "onboarding.py",
)


def stage(target):
    target = Path(target).resolve()
    target.mkdir(parents=True, exist_ok=False)
    for name in MODULES:
        shutil.copy2(ROOT / name, target / name)
    for name in ("app.py", "README.md", "requirements.txt"):
        shutil.copy2(ROOT / "hf_space" / name, target / name)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", help="New empty destination directory")
    stage(parser.parse_args().target)
