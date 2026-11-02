"""Copy docker-compose.aws.yml and Caddyfile into the UserData of template.yaml.

The template embeds both files as shell heredocs so the instance needs nothing from Git.
Edit the standalone files, then run:  uv run python deploy/aws/sync_template.py
tests/unit/test_aws_deploy_files.py fails while the copies differ. Deterministic, no network.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
TEMPLATE = HERE / "template.yaml"
BLOCKS = {"COMPOSE": HERE / "docker-compose.aws.yml", "CADDYFILE": HERE / "Caddyfile"}


def sync(text: str) -> str:
    for marker, path in BLOCKS.items():
        pattern = re.compile(
            rf"^(?P<indent>[ ]*)(?P<open>.*<<'{marker}'\n)(?P<body>.*?)^(?P=indent){marker}\n",
            re.M | re.S,
        )
        match = pattern.search(text)
        if not match:
            sys.exit(f"heredoc <<'{marker}' not found in {TEMPLATE}")
        indent = match["indent"]
        body = "".join(
            indent + line if line.strip() else "\n"
            for line in path.read_text().splitlines(keepends=True)
        )
        start, end = match.span("body")
        text = text[:start] + body + text[end:]
    return text


def main() -> None:
    old = TEMPLATE.read_text()
    new = sync(old)
    if new != old:
        TEMPLATE.write_text(new)
        print(f"updated {TEMPLATE}")
    else:
        print(f"{TEMPLATE} already in sync")


if __name__ == "__main__":
    main()
