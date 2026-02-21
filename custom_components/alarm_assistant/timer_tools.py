"""LLM Tools for timer management."""
import logging
import re

import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm
from homeassistant.util.json import JsonObjectType

from .const import DOMAIN
from .timer_storage import TimerStorage

_LOGGER = logging.getLogger(__name__)


class SetTimerTool(llm.Tool):
    """Tool for setting a timer."""

    name = "set_timer"
    description = "Set a countdown timer for a specific duration. Use this when the user wants to set a timer (not an alarm). Timers count down from a duration, while alarms trigger at a specific time."
    response_instruction = """
    Confirm to the user that the timer has been set with the duration and name.
    Keep your response concise and friendly, in plain text without formatting.
    """

    parameters = vol.Schema(
        {
            vol.Required(
                "duration_minutes",
                description="Duration in minutes. For example: 5 for 5 minutes, 30 for 30 minutes. For hours, multiply by 60 (e.g., 120 for 2 hours).",
            ): int,
            vol.Optional(
                "duration_seconds",
                description="Additional seconds to add to the duration. For example: 30 for 30 seconds. Default is 0.",
            ): int,
            vol.Required(
                "name",
                description="A descriptive name for the timer. Example: 'pizza', 'laundry', 'meeting', 'workout'",
            ): str,
            vol.Optional(
                "sound",
                description="Optional timer completion sound. Options: default, gentle, beep, chime, bell, custom",
            ): str,
            vol.Optional(
                "media_player",
                description="Optional media_player entity ID to play the timer sound on. If not specified, the default configured media player will be used. Example: 'media_player.kitchen_speaker'",
            ): str,
        }
    )

    def wrap_response(self, response: dict) -> dict:
        response["instruction"] = self.response_instruction
        return response

    def _format_duration(self, total_seconds: int) -> str:
        """Format duration as human readable string."""
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60

        parts = []
        if hours > 0:
            parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
        if minutes > 0:
            parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
        if seconds > 0:
            parts.append(f"{seconds} second{'s' if seconds != 1 else ''}")

        return " ".join(parts) if parts else "0 seconds"

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ) -> JsonObjectType:
        """Call the tool to set a timer."""
        duration_minutes = tool_input.tool_args["duration_minutes"]
        duration_seconds = tool_input.tool_args.get("duration_seconds", 0)
        name = tool_input.tool_args["name"]
        sound = tool_input.tool_args.get("sound", "default")
        media_player = tool_input.tool_args.get("media_player")

        total_seconds = (duration_minutes * 60) + duration_seconds

        if total_seconds <= 0:
            return {"error": "Duration must be greater than 0"}

        if total_seconds > 86400:  # 24 hours
            return {"error": "Timer duration cannot exceed 24 hours"}

        _LOGGER.info("Setting timer: %s for %d seconds", name, total_seconds)

        try:
            storage = TimerStorage()
            timer_id, end_time = storage.add_timer(
                name=name, duration_seconds=total_seconds, sound=sound,
                media_player=media_player,
            )

            # Schedule the timer
            await self._schedule_timer(hass, timer_id, total_seconds)

            duration_str = self._format_duration(total_seconds)
            response = {
                "success": True,
                "timer_id": timer_id,
                "duration_seconds": total_seconds,
                "end_time": end_time.strftime("%H:%M:%S"),
                "message": f"Timer '{name}' set for {duration_str}",
            }

            return self.wrap_response(response)

        except Exception as e:
            _LOGGER.error("Error setting timer: %s", e)
            return {"error": f"Failed to set timer: {e!s}"}

    async def _schedule_timer(
        self, hass: HomeAssistant, timer_id: int, duration_seconds: int
    ):
        """Schedule the timer in Home Assistant."""
        from homeassistant.helpers.event import async_call_later

        # Store timer scheduling info in hass.data
        if DOMAIN not in hass.data:
            hass.data[DOMAIN] = {}
        if "scheduled_timers" not in hass.data[DOMAIN]:
            hass.data[DOMAIN]["scheduled_timers"] = {}

        # Schedule timer to trigger after duration
        async def timer_callback(now):
            """Handle timer completion."""
            timer_manager = hass.data[DOMAIN].get("timer_manager")
            if timer_manager:
                await timer_manager.trigger_timer(timer_id)

        cancel_func = async_call_later(hass, duration_seconds, timer_callback)
        hass.data[DOMAIN]["scheduled_timers"][timer_id] = cancel_func


class ListTimersTool(llm.Tool):
    """Tool for listing all timers."""

    name = "list_timers"
    description = "List all currently running timers. Use this when the user asks what timers are set or running."
    response_instruction = """
    Present the list of timers to the user in a clear, conversational way.
    Include the name and remaining time for each timer.
    If there are no timers, let the user know in a friendly way.
    Keep your response concise and in plain text without formatting.
    """

    parameters = vol.Schema({})

    def wrap_response(self, response: dict) -> dict:
        response["instruction"] = self.response_instruction
        return response

    def _format_remaining(self, seconds: int) -> str:
        """Format remaining time as human readable string."""
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60

        if hours > 0:
            return f"{hours}h {minutes}m {secs}s"
        elif minutes > 0:
            return f"{minutes}m {secs}s"
        else:
            return f"{secs}s"

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ) -> JsonObjectType:
        """Call the tool to list timers."""
        _LOGGER.info("Listing all timers")

        try:
            storage = TimerStorage()
            timers = storage.get_all_timers()

            if not timers:
                return self.wrap_response(
                    {"timers": [], "message": "No timers are currently running"}
                )

            timer_list = []
            for timer in timers:
                remaining = storage.get_remaining_seconds(timer["id"])
                if remaining is not None and remaining > 0:
                    timer_info = {
                        "id": timer["id"],
                        "name": timer["name"],
                        "remaining_seconds": remaining,
                        "remaining_formatted": self._format_remaining(remaining),
                    }
                    if timer.get("media_player"):
                        timer_info["media_player"] = timer["media_player"]
                    timer_list.append(timer_info)

            if not timer_list:
                return self.wrap_response(
                    {"timers": [], "message": "No timers are currently running"}
                )

            return self.wrap_response(
                {
                    "timers": timer_list,
                    "count": len(timer_list),
                    "message": f"You have {len(timer_list)} timer{'s' if len(timer_list) != 1 else ''} running",
                }
            )

        except Exception as e:
            _LOGGER.error("Error listing timers: %s", e)
            return {"error": f"Failed to list timers: {e!s}"}


class CancelTimerTool(llm.Tool):
    """Tool for cancelling timers."""

    name = "cancel_timer"
    description = "Cancel one or more timers. Use this when the user wants to stop, cancel, or delete a timer. Can cancel by timer ID, by name, or all timers."
    response_instruction = """
    Confirm to the user which timer(s) were cancelled.
    Keep your response concise and friendly, in plain text without formatting.
    """

    parameters = vol.Schema(
        {
            vol.Optional(
                "timer_id",
                description="The specific ID of the timer to cancel. Use this if you know the exact timer ID from a previous list_timers call.",
            ): int,
            vol.Optional(
                "name",
                description="Cancel timer(s) by name or partial name match. Example: 'pizza' will cancel timers with 'pizza' in the name.",
            ): str,
            vol.Optional(
                "cancel_all",
                description="Set to true to cancel all timers. Use when user says 'cancel all timers' or 'stop all timers'.",
            ): bool,
        }
    )

    def wrap_response(self, response: dict) -> dict:
        response["instruction"] = self.response_instruction
        return response

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ) -> JsonObjectType:
        """Call the tool to cancel timer(s)."""
        timer_id = tool_input.tool_args.get("timer_id")
        name = tool_input.tool_args.get("name")
        cancel_all = tool_input.tool_args.get("cancel_all", False)

        _LOGGER.info(
            "Cancelling timer: ID=%s, name=%s, cancel_all=%s",
            timer_id,
            name,
            cancel_all,
        )

        try:
            storage = TimerStorage()

            if cancel_all:
                count = storage.cancel_all_timers()
                # Cancel scheduled callbacks
                if DOMAIN in hass.data and "scheduled_timers" in hass.data[DOMAIN]:
                    for cancel_func in hass.data[DOMAIN]["scheduled_timers"].values():
                        cancel_func()
                    hass.data[DOMAIN]["scheduled_timers"].clear()
                return self.wrap_response(
                    {
                        "success": True,
                        "cancelled_count": count,
                        "message": f"Cancelled all {count} timer{'s' if count != 1 else ''}",
                    }
                )

            if timer_id is not None:
                success = storage.cancel_timer(timer_id)
                if success:
                    # Cancel scheduled callback
                    if (
                        DOMAIN in hass.data
                        and "scheduled_timers" in hass.data[DOMAIN]
                    ):
                        cancel_func = hass.data[DOMAIN]["scheduled_timers"].pop(
                            timer_id, None
                        )
                        if cancel_func:
                            cancel_func()
                    return self.wrap_response(
                        {
                            "success": True,
                            "cancelled_count": 1,
                            "message": f"Cancelled timer with ID {timer_id}",
                        }
                    )
                return {"error": f"Timer with ID {timer_id} not found"}

            if name:
                count = storage.cancel_timer_by_name(name)
                if count > 0:
                    return self.wrap_response(
                        {
                            "success": True,
                            "cancelled_count": count,
                            "message": f"Cancelled {count} timer{'s' if count != 1 else ''} matching '{name}'",
                        }
                    )
                return {"error": f"No timers found matching '{name}'"}

            return {
                "error": "Please specify timer_id, name, or cancel_all to cancel timers"
            }

        except Exception as e:
            _LOGGER.error("Error cancelling timer: %s", e)
            return {"error": f"Failed to cancel timer: {e!s}"}
