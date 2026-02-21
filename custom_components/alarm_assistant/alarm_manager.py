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
    CONF_LED_COLOR,
    CONF_LED_ENTITY,
    CONF_MEDIA_PLAYER,
    DEFAULT_AUTO_DISMISS_DURATION,
    DEFAULT_LED_COLOR,
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
        alarm_media_player = alarm.get("media_player")

        _LOGGER.info("Triggering alarm %d: %s", alarm_id, alarm_name)

        try:
            # Resolve effective media player
            config_data = self.hass.data.get(DOMAIN, {}).get("config", {})
            effective_media_player = alarm_media_player or config_data.get(CONF_MEDIA_PLAYER)

            # Track ringing alarm with its media player
            if DOMAIN not in self.hass.data:
                self.hass.data[DOMAIN] = {}
            if "ringing_alarms" not in self.hass.data[DOMAIN]:
                self.hass.data[DOMAIN]["ringing_alarms"] = {}

            self.hass.data[DOMAIN]["ringing_alarms"][alarm_id] = {
                "media_player": effective_media_player,
            }

            # Activate LED ring
            await self._set_alarm_led()

            # Play alarm sound
            await self._play_alarm_sound(alarm_sound, media_player_override=alarm_media_player)

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

    async def _play_alarm_sound(self, sound: str, media_player_override: str | None = None):
        """Play the alarm sound using a media player."""
        config_data = self.hass.data.get(DOMAIN, {}).get("config", {})
        media_player = media_player_override or config_data.get(CONF_MEDIA_PLAYER)
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

            # Remove from ringing alarms and get per-alarm media player
            ringing_alarms = self.hass.data.get(DOMAIN, {}).get("ringing_alarms", {})
            alarm_data = ringing_alarms.pop(alarm_id, {})
            media_player = alarm_data.get("media_player") or config_data.get(CONF_MEDIA_PLAYER)

            # Stop media player
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

            # Restore LED if no more ringing alarms
            if not self.hass.data.get(DOMAIN, {}).get("ringing_alarms"):
                await self._restore_led_state()

            # Remove the timer from tracking
            self._auto_dismiss_timers.pop(alarm_id, None)

        # Schedule the auto-dismiss
        cancel_timer = async_call_later(
            self.hass, auto_dismiss_minutes * 60, auto_dismiss_callback
        )
        self._auto_dismiss_timers[alarm_id] = cancel_timer
        _LOGGER.info("Scheduled auto-dismiss for alarm %d in %d minutes", alarm_id, auto_dismiss_minutes)

    async def _save_led_state(self):
        """Save the current LED ring state before changing it."""
        config_data = self.hass.data.get(DOMAIN, {}).get("config", {})
        led_entity = config_data.get(CONF_LED_ENTITY)
        if not led_entity:
            return

        state = self.hass.states.get(led_entity)
        if state:
            saved = {
                "state": state.state,
                "brightness": state.attributes.get("brightness"),
                "rgb_color": state.attributes.get("rgb_color"),
            }
            self.hass.data.setdefault(DOMAIN, {})["saved_led_state"] = saved
            _LOGGER.debug("Saved LED state: %s", saved)

    async def _set_alarm_led(self):
        """Set the LED ring to the alarm color."""
        config_data = self.hass.data.get(DOMAIN, {}).get("config", {})
        led_entity = config_data.get(CONF_LED_ENTITY)
        if not led_entity:
            return

        # Only save state if not already saved (first alarm to ring)
        if "saved_led_state" not in self.hass.data.get(DOMAIN, {}):
            await self._save_led_state()

        led_color = config_data.get(CONF_LED_COLOR, DEFAULT_LED_COLOR)

        try:
            await self.hass.services.async_call(
                "light",
                "turn_on",
                {
                    "entity_id": led_entity,
                    "rgb_color": led_color,
                    "brightness": 255,
                },
                blocking=False,
            )
            _LOGGER.info("Set LED ring to alarm color: %s", led_color)
        except Exception as e:
            _LOGGER.warning("Could not set LED ring: %s", e)

    async def _restore_led_state(self):
        """Restore the LED ring to its previous state."""
        config_data = self.hass.data.get(DOMAIN, {}).get("config", {})
        led_entity = config_data.get(CONF_LED_ENTITY)
        if not led_entity:
            return

        saved = self.hass.data.get(DOMAIN, {}).pop("saved_led_state", None)
        if not saved:
            return

        try:
            if saved["state"] == "off":
                await self.hass.services.async_call(
                    "light",
                    "turn_off",
                    {"entity_id": led_entity},
                    blocking=False,
                )
            else:
                service_data = {"entity_id": led_entity}
                if saved.get("brightness") is not None:
                    service_data["brightness"] = saved["brightness"]
                if saved.get("rgb_color") is not None:
                    service_data["rgb_color"] = list(saved["rgb_color"])
                await self.hass.services.async_call(
                    "light",
                    "turn_on",
                    service_data,
                    blocking=False,
                )
            _LOGGER.info("Restored LED ring state")
        except Exception as e:
            _LOGGER.warning("Could not restore LED ring: %s", e)

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
