"""Timer storage and management using in-memory storage."""
import logging
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)


class TimerStorage:
    """Singleton class for managing timers in memory."""

    _instance = None
    _timers = {}
    _next_id = 1

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def add_timer(
        self,
        name: str,
        duration_seconds: int,
        sound: str = "default",
        media_player: str | None = None,
    ) -> tuple[int, datetime]:
        """
        Add a new timer.

        Args:
            name: Name/label for the timer
            duration_seconds: Duration in seconds
            sound: Sound to play when timer completes
            media_player: Optional media player entity ID to play timer sound on

        Returns:
            Tuple of (timer_id, end_time)
        """
        timer_id = self._next_id
        self._next_id += 1

        start_time = datetime.now()
        end_time = start_time + timedelta(seconds=duration_seconds)

        self._timers[timer_id] = {
            "id": timer_id,
            "name": name,
            "duration_seconds": duration_seconds,
            "start_time": start_time,
            "end_time": end_time,
            "sound": sound,
            "active": True,
            "media_player": media_player,
        }

        logger.info(
            "Created timer: %s for %d seconds (ID: %d, ends at: %s)",
            name,
            duration_seconds,
            timer_id,
            end_time.strftime("%H:%M:%S"),
        )
        return timer_id, end_time

    def get_all_timers(self) -> list[dict[str, Any]]:
        """Get all active timers."""
        return [
            timer for timer in self._timers.values()
            if timer["active"]
        ]

    def get_timer(self, timer_id: int) -> dict[str, Any] | None:
        """Get a specific timer by ID."""
        return self._timers.get(timer_id)

    def cancel_timer(self, timer_id: int) -> bool:
        """
        Cancel a timer by ID.

        Args:
            timer_id: The ID of the timer to cancel

        Returns:
            True if timer was cancelled, False if not found
        """
        if timer_id in self._timers:
            self._timers[timer_id]["active"] = False
            logger.info("Cancelled timer with ID: %d", timer_id)
            return True
        logger.warning("Timer with ID %d not found", timer_id)
        return False

    def cancel_timer_by_name(self, name: str) -> int:
        """
        Cancel timer(s) by name.

        Args:
            name: The name of the timer(s) to cancel

        Returns:
            Number of timers cancelled
        """
        count = 0
        for timer in self._timers.values():
            if timer["active"] and name.lower() in timer["name"].lower():
                timer["active"] = False
                count += 1
        logger.info("Cancelled %d timer(s) matching name: %s", count, name)
        return count

    def cancel_all_timers(self) -> int:
        """
        Cancel all timers.

        Returns:
            Number of timers cancelled
        """
        count = 0
        for timer in self._timers.values():
            if timer["active"]:
                timer["active"] = False
                count += 1
        logger.info("Cancelled all timers (%d total)", count)
        return count

    def complete_timer(self, timer_id: int) -> bool:
        """
        Mark a timer as completed (triggered).

        Args:
            timer_id: The ID of the timer

        Returns:
            True if timer was marked complete, False if not found
        """
        if timer_id in self._timers:
            self._timers[timer_id]["active"] = False
            logger.info("Timer %d completed", timer_id)
            return True
        return False

    def get_remaining_seconds(self, timer_id: int) -> int | None:
        """
        Get remaining seconds for a timer.

        Args:
            timer_id: The ID of the timer

        Returns:
            Remaining seconds or None if not found
        """
        timer = self._timers.get(timer_id)
        if not timer or not timer["active"]:
            return None

        remaining = (timer["end_time"] - datetime.now()).total_seconds()
        return max(0, int(remaining))

    def cleanup_completed(self):
        """Remove completed/cancelled timers older than 1 hour."""
        cutoff = datetime.now() - timedelta(hours=1)
        to_remove = [
            tid for tid, timer in self._timers.items()
            if not timer["active"] and timer["end_time"] < cutoff
        ]
        for tid in to_remove:
            del self._timers[tid]
        if to_remove:
            logger.debug("Cleaned up %d old timers", len(to_remove))
