"""LLM Tools for alarm management."""
import logging
import re
from datetime import datetime

import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm
from homeassistant.util.json import JsonObjectType

from .alarm_storage import AlarmStorage
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class SetAlarmTool(llm.Tool):
    """Tool for setting an alarm."""

    name = "set_alarm"
    description = "Set a new alarm at a specific time. Use this when the user wants to create an alarm or be reminded at a specific time."
    response_instruction = """
    Confirm to the user that the alarm has been set with the time and name.
    Keep your response concise and friendly, in plain text without formatting.
    """

    parameters = vol.Schema(
        {
            vol.Required(
                "time",
                description="The time for the alarm in HH:MM format (24-hour). Example: 07:30 for 7:30 AM, 14:00 for 2:00 PM",
            ): str,
            vol.Required(
                "name",
                description="A descriptive name or label for the alarm. Example: 'Morning alarm', 'Meeting reminder', 'Wake up'",
            ): str,
            vol.Optional(
                "repeat_days",
                description="Optional list of days when alarm should repeat. Use lowercase 3-letter abbreviations: mon, tue, wed, thu, fri, sat, sun. Leave empty for one-time alarm.",
            ): [str],
            vol.Optional(
                "sound",
                description="Optional alarm sound. Options: default, gentle, beep, chime, bell",
            ): str,
            vol.Optional(
                "media_player",
                description="Optional media_player entity ID to play the alarm sound on. If not specified, the default configured media player will be used. Example: 'media_player.bedroom_speaker'",
            ): str,
        }
    )

    def wrap_response(self, response: dict) -> dict:
        response["instruction"] = self.response_instruction
        return response

    def _validate_time(self, time_str: str) -> tuple[bool, str]:
        """Validate time format and return (is_valid, error_message)."""
        pattern = r"^([0-1]?[0-9]|2[0-3]):([0-5][0-9])$"
        if not re.match(pattern, time_str):
            return False, "Time must be in HH:MM format (24-hour). Example: 07:30 or 14:00"
        return True, ""

    def _validate_repeat_days(self, days: list[str] | None) -> tuple[bool, str]:
        """Validate repeat days."""
        if not days:
            return True, ""
        valid_days = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
        for day in days:
            if day.lower() not in valid_days:
                return (
                    False,
                    f"Invalid day: {day}. Use: mon, tue, wed, thu, fri, sat, sun",
                )
        return True, ""

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ) -> JsonObjectType:
        """Call the tool to set an alarm."""
        time_str = tool_input.tool_args["time"]
        name = tool_input.tool_args["name"]
        repeat_days = tool_input.tool_args.get("repeat_days")
        sound = tool_input.tool_args.get("sound", "default")
        media_player = tool_input.tool_args.get("media_player")

        _LOGGER.info("Setting alarm: %s at %s", name, time_str)

        # Validate time
        is_valid, error_msg = self._validate_time(time_str)
        if not is_valid:
            return {"error": error_msg}

        # Validate repeat days
        is_valid, error_msg = self._validate_repeat_days(repeat_days)
        if not is_valid:
            return {"error": error_msg}

        try:
            storage = AlarmStorage()
            alarm_id = storage.add_alarm(
                name=name, time=time_str, repeat_days=repeat_days, sound=sound,
                media_player=media_player,
            )

            # Schedule the alarm
            await self._schedule_alarm(hass, alarm_id, time_str, repeat_days)

            response = {
                "success": True,
                "alarm_id": alarm_id,
                "message": f"Alarm '{name}' set for {time_str}",
            }

            if repeat_days:
                response["message"] += f" on {', '.join(repeat_days)}"

            return self.wrap_response(response)

        except Exception as e:
            _LOGGER.error("Error setting alarm: %s", e)
            return {"error": f"Failed to set alarm: {e!s}"}

    async def _schedule_alarm(
        self,
        hass: HomeAssistant,
        alarm_id: int,
        time_str: str,
        repeat_days: list[str] | None,
    ):
        """Schedule the alarm in Home Assistant."""
        # Get the alarm manager and schedule the alarm
        alarm_manager = hass.data.get(DOMAIN, {}).get("alarm_manager")
        if alarm_manager:
            # Get the full alarm details from storage
            storage = AlarmStorage()
            alarms = storage.get_all_alarms()
            alarm = next((a for a in alarms if a["id"] == alarm_id), None)

            if alarm:
                await alarm_manager._schedule_alarm(alarm)
                _LOGGER.info("Alarm %d scheduled through AlarmManager", alarm_id)
        else:
            _LOGGER.warning("AlarmManager not found, alarm %d not scheduled", alarm_id)


class ListAlarmsTool(llm.Tool):
    """Tool for listing all alarms."""

    name = "list_alarms"
    description = "List all currently set alarms. Use this when the user asks what alarms are set or wants to see their alarms."
    response_instruction = """
    Present the list of alarms to the user in a clear, conversational way.
    Include the time and name for each alarm.
    If there are no alarms, let the user know in a friendly way.
    Keep your response concise and in plain text without formatting.
    """

    parameters = vol.Schema({})

    def wrap_response(self, response: dict) -> dict:
        response["instruction"] = self.response_instruction
        return response

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ) -> JsonObjectType:
        """Call the tool to list alarms."""
        _LOGGER.info("Listing all alarms")

        try:
            storage = AlarmStorage()
            alarms = storage.get_all_alarms()

            if not alarms:
                return self.wrap_response(
                    {"alarms": [], "message": "No alarms are currently set"}
                )

            alarm_list = []
            for alarm in alarms:
                alarm_info = {
                    "id": alarm["id"],
                    "name": alarm["name"],
                    "time": alarm["time"],
                    "enabled": alarm["enabled"],
                }
                if alarm["repeat_days"]:
                    alarm_info["repeat_days"] = alarm["repeat_days"]
                if alarm["sound"]:
                    alarm_info["sound"] = alarm["sound"]
                if alarm.get("media_player"):
                    alarm_info["media_player"] = alarm["media_player"]
                alarm_list.append(alarm_info)

            return self.wrap_response(
                {
                    "alarms": alarm_list,
                    "count": len(alarms),
                    "message": f"You have {len(alarms)} alarm{'s' if len(alarms) != 1 else ''} set",
                }
            )

        except Exception as e:
            _LOGGER.error("Error listing alarms: %s", e)
            return {"error": f"Failed to list alarms: {e!s}"}


class DeleteAlarmTool(llm.Tool):
    """Tool for deleting alarms."""

    name = "delete_alarm"
    description = "Delete one or more alarms. Use this when the user wants to cancel, remove, or delete an alarm. Can delete by alarm ID, by name, or all alarms."
    response_instruction = """
    Confirm to the user which alarm(s) were deleted.
    Keep your response concise and friendly, in plain text without formatting.
    """

    parameters = vol.Schema(
        {
            vol.Optional(
                "alarm_id",
                description="The specific ID of the alarm to delete. Use this if you know the exact alarm ID from a previous list_alarms call.",
            ): int,
            vol.Optional(
                "name",
                description="Delete alarm(s) by name or partial name match. Example: 'morning' will delete alarms with 'morning' in the name.",
            ): str,
            vol.Optional(
                "delete_all",
                description="Set to true to delete all alarms. Use when user says 'delete all alarms' or 'clear all alarms'.",
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
        """Call the tool to delete alarm(s)."""
        alarm_id = tool_input.tool_args.get("alarm_id")
        name = tool_input.tool_args.get("name")
        delete_all = tool_input.tool_args.get("delete_all", False)

        _LOGGER.info(
            "Deleting alarm: ID=%s, name=%s, delete_all=%s", alarm_id, name, delete_all
        )

        try:
            storage = AlarmStorage()

            if delete_all:
                count = storage.delete_all_alarms()
                # Reschedule all alarms in alarm manager (clears old ones)
                alarm_manager = hass.data.get(DOMAIN, {}).get("alarm_manager")
                if alarm_manager:
                    await alarm_manager.reschedule_all()
                return self.wrap_response(
                    {
                        "success": True,
                        "deleted_count": count,
                        "message": f"Deleted all {count} alarm{'s' if count != 1 else ''}",
                    }
                )

            if alarm_id is not None:
                success = storage.delete_alarm(alarm_id)
                if success:
                    # Reschedule all alarms in alarm manager (removes deleted ones)
                    alarm_manager = hass.data.get(DOMAIN, {}).get("alarm_manager")
                    if alarm_manager:
                        await alarm_manager.reschedule_all()
                    return self.wrap_response(
                        {
                            "success": True,
                            "deleted_count": 1,
                            "message": f"Deleted alarm with ID {alarm_id}",
                        }
                    )
                return {"error": f"Alarm with ID {alarm_id} not found"}

            if name:
                count = storage.delete_alarm_by_name(name)
                if count > 0:
                    return self.wrap_response(
                        {
                            "success": True,
                            "deleted_count": count,
                            "message": f"Deleted {count} alarm{'s' if count != 1 else ''} matching '{name}'",
                        }
                    )
                return {"error": f"No alarms found matching '{name}'"}

            return {
                "error": "Please specify alarm_id, name, or delete_all to delete alarms"
            }

        except Exception as e:
            _LOGGER.error("Error deleting alarm: %s", e)
            return {"error": f"Failed to delete alarm: {e!s}"}
