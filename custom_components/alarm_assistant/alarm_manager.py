"""Alarm manager for scheduling and triggering alarms."""
import asyncio
import logging
from datetime import datetime, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.util import dt as dt_util

from .alarm_storage import AlarmStorage
from .const import (
    CONF_ALARM_SOUND,
    CONF_ALARM_VOLUME,
    CONF_AUTO_DISMISS_DURATION,
    CONF_MEDIA_PLAYER,
    DEFAULT_AUTO_DISMISS_DURATION,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class AlarmManager:
    """Manages alarm scheduling and triggering."""

    def __init__(self, hass: HomeAssistant):
        """Initialize the alarm manager."""
        self.hass = hass
        self.storage = AlarmStorage()
        self._scheduled_timers = {}
        self._auto_dismiss_timers = {}
        self._running = False

    async def start(self):
        """Start the alarm manager and schedule all alarms."""
        if self._running:
            return

        self._running = True
        _LOGGER.info("Starting alarm manager")

        # Load and schedule all enabled alarms
        alarms = self.storage.get_enabled_alarms()
        for alarm in alarms:
            await self._schedule_alarm(alarm)

        _LOGGER.info("Alarm manager started with %d active alarms", len(alarms))

    async def stop(self):
        """Stop the alarm manager and cancel all scheduled alarms."""
        _LOGGER.info("Stopping alarm manager")
        self._running = False

        # Cancel all scheduled timers
        for timer_cancel in self._scheduled_timers.values():
            timer_cancel()
        self._scheduled_timers.clear()

        # Cancel all auto-dismiss timers
        for timer_cancel in self._auto_dismiss_timers.values():
            timer_cancel()
        self._auto_dismiss_timers.clear()

    async def _schedule_alarm(self, alarm: dict):
        """Schedule a single alarm."""
        alarm_id = alarm["id"]
        time_str = alarm["time"]
        repeat_days = alarm.get("repeat_days")

        try:
            # Parse the alarm time
            hour, minute = map(int, time_str.split(":"))

            # Calculate next trigger time
            next_trigger = self._calculate_next_trigger(hour, minute, repeat_days)

            if next_trigger:
                # Schedule the alarm
                timer_cancel = async_track_point_in_time(
                    self.hass,
                    lambda now: self.hass.async_create_task(
                        self._trigger_alarm(alarm)
                    ),
                    next_trigger,
                )
                self._scheduled_timers[alarm_id] = timer_cancel
                _LOGGER.info(
                    "Scheduled alarm %d (%s) for %s",
                    alarm_id,
                    alarm["name"],
                    next_trigger,
                )

        except Exception as e:
            _LOGGER.error("Error scheduling alarm %d: %s", alarm_id, e)

    def _calculate_next_trigger(
        self, hour: int, minute: int, repeat_days: list[str] | None
    ) -> datetime | None:
        """Calculate the next trigger time for an alarm."""
        now = dt_util.now()

        # Create a timezone-aware datetime for today at the alarm time
        # Start with the beginning of today in local timezone
        today_start = dt_util.start_of_local_day()
        alarm_time = today_start.replace(hour=hour, minute=minute, second=0, microsecond=0)

        if repeat_days:
            # Repeating alarm - find next occurrence
            day_map = {
                "mon": 0,
                "tue": 1,
                "wed": 2,
                "thu": 3,
                "fri": 4,
                "sat": 5,
                "sun": 6,
            }
            target_days = [day_map[day.lower()] for day in repeat_days if day.lower() in day_map]

            if not target_days:
                return None

            # Find the next day that matches
            for days_ahead in range(8):  # Check up to 7 days ahead + today
                check_time = today_start + timedelta(days=days_ahead)
                check_time = check_time.replace(hour=hour, minute=minute, second=0, microsecond=0)

                if check_time.weekday() in target_days and check_time > now:
                    return check_time

            return None
        else:
            # One-time alarm
            if alarm_time > now:
                return alarm_time
            else:
                # If time has passed today, schedule for tomorrow
                tomorrow_time = today_start + timedelta(days=1)
                alarm_time = tomorrow_time.replace(hour=hour, minute=minute, second=0, microsecond=0)
                return alarm_time

    async def _trigger_alarm(self, alarm: dict):
        """Trigger an alarm (play sound, send notification, etc.)."""
        alarm_id = alarm["id"]
        alarm_name = alarm["name"]
        alarm_sound = alarm.get("sound", "default")

        _LOGGER.info("Triggering alarm %d: %s", alarm_id, alarm_name)

        try:
            # Track ringing alarm
            if DOMAIN not in self.hass.data:
                self.hass.data[DOMAIN] = {}
            if "ringing_alarms" not in self.hass.data[DOMAIN]:
                self.hass.data[DOMAIN]["ringing_alarms"] = []

            self.hass.data[DOMAIN]["ringing_alarms"].append(alarm_id)

            # Play alarm sound
            await self._play_alarm_sound(alarm_sound)

            # Send notification (optional)
            await self._send_notification(alarm_name, alarm_id)

            # Schedule auto-dismiss after configured duration
            await self._schedule_auto_dismiss(alarm_id)

            # If it's a one-time alarm, disable it
            if not alarm.get("repeat_days"):
                self.storage.toggle_alarm(alarm_id, False)
                _LOGGER.info("Disabled one-time alarm %d", alarm_id)
            else:
                # Reschedule repeating alarm for next occurrence
                await self._schedule_alarm(alarm)

        except Exception as e:
            _LOGGER.error("Error triggering alarm %d: %s", alarm_id, e)

    async def _play_alarm_sound(self, sound: str):
        """Play the alarm sound using a media player."""
        config_data = self.hass.data.get(DOMAIN, {}).get("config", {})
        media_player = config_data.get(CONF_MEDIA_PLAYER)
        volume = config_data.get(CONF_ALARM_VOLUME, 0.5)

        if not media_player:
            _LOGGER.warning("No media player configured for alarm sounds")
            return

        try:
            # Get custom file path if sound is "custom"
            if sound == "custom":
                custom_path = config_data.get("custom_sound_path")
                if custom_path:
                    sound_file = custom_path
                else:
                    sound_file = "/local/alarm_sounds/custom.mp3"
            else:
                # Map sound names to file paths or URLs
                sound_map = {
                    "default": "/local/alarm_sounds/default.mp3",
                    "gentle": "/local/alarm_sounds/gentle.mp3",
                    "beep": "/local/alarm_sounds/beep.mp3",
                    "chime": "/local/alarm_sounds/chime.mp3",
                    "bell": "/local/alarm_sounds/bell.mp3",
                }
                sound_file = sound_map.get(sound, sound_map["default"])

            # Set volume
            await self.hass.services.async_call(
                "media_player",
                "volume_set",
                {"entity_id": media_player, "volume_level": volume},
                blocking=True,
            )

            # Play sound
            await self.hass.services.async_call(
                "media_player",
                "play_media",
                {
                    "entity_id": media_player,
                    "media_content_id": sound_file,
                    "media_content_type": "music",
                },
                blocking=False,
            )

            _LOGGER.info("Playing alarm sound: %s on %s", sound, media_player)

        except Exception as e:
            _LOGGER.error("Error playing alarm sound: %s", e)

    async def _send_notification(self, alarm_name: str, alarm_id: int):
        """Send a notification for the alarm."""
        try:
            await self.hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": "Alarm",
                    "message": f"Alarm '{alarm_name}' is ringing!",
                    "notification_id": f"alarm_{alarm_id}",
                },
                blocking=False,
            )
        except Exception as e:
            _LOGGER.error("Error sending alarm notification: %s", e)

    async def _schedule_auto_dismiss(self, alarm_id: int):
        """Schedule automatic dismissal of a ringing alarm."""
        from homeassistant.helpers.event import async_call_later

        # Get auto-dismiss duration from config or use default
        config_data = self.hass.data.get(DOMAIN, {}).get("config", {})
        auto_dismiss_minutes = config_data.get(
            CONF_AUTO_DISMISS_DURATION, DEFAULT_AUTO_DISMISS_DURATION
        )

        async def auto_dismiss_callback(now):
            """Callback to automatically dismiss the alarm."""
            _LOGGER.info("Auto-dismissing alarm %d after %d minutes", alarm_id, auto_dismiss_minutes)

            # Remove from ringing alarms list
            if DOMAIN in self.hass.data:
                ringing_alarms = self.hass.data[DOMAIN].get("ringing_alarms", [])
                if alarm_id in ringing_alarms:
                    ringing_alarms.remove(alarm_id)

            # Stop media player
            media_player = config_data.get(CONF_MEDIA_PLAYER)
            if media_player:
                try:
                    await self.hass.services.async_call(
                        "media_player",
                        "media_stop",
                        {"entity_id": media_player},
                        blocking=False,
                    )
                except Exception as e:
                    _LOGGER.warning("Could not stop media player during auto-dismiss: %s", e)

            # Dismiss notification
            try:
                await self.hass.services.async_call(
                    "persistent_notification",
                    "dismiss",
                    {"notification_id": f"alarm_{alarm_id}"},
                    blocking=False,
                )
            except Exception as e:
                _LOGGER.warning("Could not dismiss notification during auto-dismiss: %s", e)

            # Remove the timer from tracking
            self._auto_dismiss_timers.pop(alarm_id, None)

        # Schedule the auto-dismiss
        cancel_timer = async_call_later(
            self.hass, auto_dismiss_minutes * 60, auto_dismiss_callback
        )
        self._auto_dismiss_timers[alarm_id] = cancel_timer
        _LOGGER.info("Scheduled auto-dismiss for alarm %d in %d minutes", alarm_id, auto_dismiss_minutes)

    async def reschedule_all(self):
        """Reschedule all alarms (useful after configuration changes)."""
        _LOGGER.info("Rescheduling all alarms")

        # Cancel existing timers
        for timer_cancel in self._scheduled_timers.values():
            timer_cancel()
        self._scheduled_timers.clear()

        # Reload and reschedule
        alarms = self.storage.get_enabled_alarms()
        for alarm in alarms:
            await self._schedule_alarm(alarm)
