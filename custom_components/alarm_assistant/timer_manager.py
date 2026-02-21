"""Timer manager for handling timer completion."""
import logging

from homeassistant.core import HomeAssistant

from .const import CONF_ALARM_VOLUME, CONF_MEDIA_PLAYER, CONF_TIMER_SOUND, DOMAIN
from .timer_storage import TimerStorage

_LOGGER = logging.getLogger(__name__)


class TimerManager:
    """Manages timer completion actions."""

    def __init__(self, hass: HomeAssistant):
        """Initialize the timer manager."""
        self.hass = hass
        self.storage = TimerStorage()

    async def trigger_timer(self, timer_id: int):
        """Trigger a timer (play sound, send notification, etc.)."""
        timer = self.storage.get_timer(timer_id)
        if not timer or not timer["active"]:
            return

        timer_name = timer["name"]
        timer_sound = timer.get("sound", "default")
        timer_media_player = timer.get("media_player")

        _LOGGER.info("Timer completed: %d (%s)", timer_id, timer_name)

        try:
            # Activate LED ring briefly
            alarm_manager = self.hass.data.get(DOMAIN, {}).get("alarm_manager")
            if alarm_manager:
                await alarm_manager._set_alarm_led()

            # Play timer sound
            await self._play_timer_sound(timer_sound, media_player_override=timer_media_player)

            # Send notification
            await self._send_notification(timer_name)

            # Mark timer as completed
            self.storage.complete_timer(timer_id)

            # Cleanup old timers
            self.storage.cleanup_completed()

            # Schedule LED restore after 30 seconds
            if alarm_manager:
                from homeassistant.helpers.event import async_call_later

                async def restore_led(now):
                    await alarm_manager._restore_led_state()

                async_call_later(self.hass, 30, restore_led)

        except Exception as e:
            _LOGGER.error("Error triggering timer %d: %s", timer_id, e)

    async def _play_timer_sound(self, sound: str, media_player_override: str | None = None):
        """Play the timer sound using a media player."""
        config_data = self.hass.data.get(DOMAIN, {}).get("config", {})
        media_player = media_player_override or config_data.get(CONF_MEDIA_PLAYER)
        volume = config_data.get(CONF_ALARM_VOLUME, 0.5)

        if not media_player:
            _LOGGER.warning("No media player configured for timer sounds")
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
                # Map sound names to file paths
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

            _LOGGER.info("Playing timer sound: %s on %s", sound, media_player)

        except Exception as e:
            _LOGGER.error("Error playing timer sound: %s", e)

    async def _send_notification(self, timer_name: str):
        """Send a notification for the timer."""
        try:
            await self.hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": "Timer Complete",
                    "message": f"Timer '{timer_name}' has finished!",
                    "notification_id": f"timer_{timer_name}",
                },
                blocking=False,
            )
        except Exception as e:
            _LOGGER.error("Error sending timer notification: %s", e)
