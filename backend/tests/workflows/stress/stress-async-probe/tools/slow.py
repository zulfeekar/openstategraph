"""A tool that blocks for a fixed time, so concurrency can be measured rather than assumed."""
from __future__ import annotations
import os, time, threading
from pydantic import BaseModel, Field
from openstategraph.abc import BaseTool, ToolResult

SLEEP = float(os.environ.get("STRESS_TOOL_SLEEP", "3"))


class SlowArgs(BaseModel):
    label: str = Field(description="Any short label; it is echoed back.")


class SlowTool(BaseTool):
    """Blocks for a fixed number of seconds, then echoes its label."""

    name = "slow_probe"
    side_effecting = False
    node_type = "tool.slow-probe"
    description = (
        "Waits for a fixed time and returns the label it was given. Call it "
        "exactly once with the label 'ping', then report what it returned."
    )
    Args = SlowArgs

    def _execute(self, args: BaseModel) -> ToolResult:
        started = time.time()
        thread = threading.current_thread().name
        time.sleep(SLEEP)
        return ToolResult(
            content=f"slow_probe returned {getattr(args,'label','')!r} after "
            f"{time.time()-started:.2f}s on thread {thread}"
        )
