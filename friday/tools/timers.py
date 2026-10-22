"""
Timer tools — background countdown timers that alert on the host machine.
"""

import asyncio
import logging
import sys

logger = logging.getLogger("friday-timers")

# Keep references so tasks aren't garbage-collected
_active_timers: set[asyncio.Task] = set()


async def _alert_after(seconds: float, label: str) -> None:
    """Sleep, then alert the user on the host machine."""
    await asyncio.sleep(seconds)
    logger.info("Timer done: %s", label)

    if sys.platform == "win32":
        try:
            import winsound
            # Three beeps — unmistakable
            for _ in range(3):
                winsound.Beep(880, 300)
                winsound.Beep(0, 100)
            return
        except Exception:
            pass

    # Fallback: terminal bell (works if the server runs in a visible terminal)
    print(f"\aFRIDAY timer done: {label}")


def register(mcp):

    @mcp.tool()
    async def set_timer(minutes: float, label: str = "timer") -> str:
        """
        Start a countdown timer. The host machine beeps when time is up.
        Use when the user says 'set a timer', 'remind me in X minutes', etc.
        minutes: duration in minutes (decimals allowed, e.g. 1.5)
        label: short description of what the timer is for
        """
        if minutes <= 0 or minutes > 24 * 60:
            return "Timers need to be between a split second and 24 hours, boss."

        task = asyncio.create_task(_alert_after(minutes * 60, label))
        _active_timers.add(task)
        task.add_done_callback(_active_timers.discard)

        # Speak-friendly duration
        if minutes == 1:
            spoken = "one minute"
        elif minutes == int(minutes):
            spoken = f"{int(minutes)} minutes"
        else:
            spoken = f"{minutes} minutes"

        return f"Timer set — {spoken}, boss. I'll beep when it's done."

    @mcp.tool()
    async def cancel_timers() -> str:
        """Cancel all running countdown timers."""
        if not _active_timers:
            return "No timers running, boss."
        for task in list(_active_timers):
            task.cancel()
        _active_timers.clear()
        return "All timers cancelled, boss."
