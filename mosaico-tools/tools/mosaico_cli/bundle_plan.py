"""Inspect a local bundle through the public Iris CLI before device admission."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .errors import BuildError
from .gateway import ensure_iris_tools
from .runtime import RunContext


def inspect_bundle_plan(context: RunContext, bundle: Path) -> dict[str, Any]:
    python, tool = ensure_iris_tools(context)
    result = context.run(
        [str(python), str(tool), "bundle", "--json", "inspect", str(bundle)], timeout=60
    )
    if result.returncode:
        raise BuildError(
            "System Update bundle validation failed.",
            details={"bundle": str(bundle), "log": str(context.log_path)},
        )
    try:
        plan = json.loads(result.stdout)
        components = plan["components"]
        for item in components:
            context.status(
                f"write: {item['file']} ({item['kind']}) -> 0x{item['target_offset']:x}, "
                f"{item['size']} bytes, SHA-256 {item['sha256']}"
            )
    except (ValueError, TypeError, KeyError) as error:
        raise BuildError("Invalid System Update inspection response.") from error
    context.note("system update plan: " + json.dumps(plan, sort_keys=True))
    return plan
