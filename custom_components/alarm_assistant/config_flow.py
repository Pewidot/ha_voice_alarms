"""Config flow for the Voice Alarm Assistant integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

_LOGGER = logging.getLogger(__name__)

from .const import (
    ADDON_NAME,
    ALARM_SOUNDS,
    CONF_ALARM_ENABLED,
    CONF_ALARM_SOUND,
    CONF_ALARM_VOLUME,
    CONF_AUTO_DISMISS_DURATION,
    CONF_LED_COLOR,
    CONF_LED_ENTITY,
    CONF_MEDIA_PLAYER,
    CONF_SNOOZE_DURATION,
    DEFAULT_AUTO_DISMISS_DURATION,
    DEFAULT_LED_COLOR,
    DEFAULT_SNOOZE_DURATION,
    DOMAIN,
    SERVICE_DEFAULTS,
)

if TYPE_CHECKING:  # pragma: no cover
    from homeassistant.config_entries import ConfigEntry, OptionsFlow


class AlarmAssistantConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for the Voice Alarm Assistant integration."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Handle the initial configuration step."""
        errors = {}

        # Check if entry already exists
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is None:
            # Get all media player entities
            media_players = []
            for state in self.hass.states.async_all("media_player"):
                media_players.append(state.entity_id)

            schema = vol.Schema(
                {
                    vol.Required(CONF_ALARM_ENABLED, default=True): bool,
                    vol.Optional(CONF_MEDIA_PLAYER): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="media_player")
                    ),
                    vol.Optional(
                        CONF_ALARM_SOUND, default=SERVICE_DEFAULTS[CONF_ALARM_SOUND]
                    ): vol.In(ALARM_SOUNDS),
                    vol.Optional(
                        CONF_ALARM_VOLUME, default=SERVICE_DEFAULTS[CONF_ALARM_VOLUME]
                    ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
                    vol.Optional(
                        CONF_SNOOZE_DURATION,
                        default=DEFAULT_SNOOZE_DURATION,
                        description="Snooze duration in minutes",
                    ): vol.All(vol.Coerce(int), vol.Range(min=1, max=60)),
                    vol.Optional(
                        CONF_AUTO_DISMISS_DURATION,
                        default=DEFAULT_AUTO_DISMISS_DURATION,
                        description="Auto-dismiss alarm after this many minutes",
                    ): vol.All(vol.Coerce(int), vol.Range(min=1, max=120)),
                    vol.Optional(
                        "custom_sound_path",
                        description="Custom sound file path (e.g., /local/my_sounds/alarm.mp3 or http://...)",
                    ): str,
                    vol.Optional(
                        CONF_LED_ENTITY,
                    ): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="light")
                    ),
                    vol.Optional(
                        CONF_LED_COLOR,
                        default=DEFAULT_LED_COLOR,
                    ): selector.ColorRGBSelector(),
                }
            )

            return self.async_show_form(
                step_id="user",
                data_schema=schema,
                errors=errors,
            )

        # Set a unique ID for this integration instance
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        # Create the entry
        return self.async_create_entry(title=ADDON_NAME, data=user_input, options={})

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Provide an options flow for existing entries."""
        return AlarmAssistantOptionsFlow(config_entry)


class AlarmAssistantOptionsFlow(config_entries.OptionsFlow):
    """Handle an options flow for an existing Voice Alarm Assistant config entry."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize the options flow with the existing entry."""
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Handle the options configuration."""
        errors = {}

        if user_input is not None:
            # Update the config entry with new options
            return self.async_create_entry(data=user_input)

        # Get current values
        data = self._config_entry.data
        opts = self._config_entry.options or {}
        defaults = {**data, **opts}

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_ALARM_ENABLED,
                    default=defaults.get(CONF_ALARM_ENABLED, True),
                ): bool,
                vol.Optional(
                    CONF_MEDIA_PLAYER,
                    default=defaults.get(CONF_MEDIA_PLAYER),
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="media_player")
                ),
                vol.Optional(
                    CONF_ALARM_SOUND,
                    default=defaults.get(CONF_ALARM_SOUND, SERVICE_DEFAULTS[CONF_ALARM_SOUND]),
                ): vol.In(ALARM_SOUNDS),
                vol.Optional(
                    CONF_ALARM_VOLUME,
                    default=defaults.get(CONF_ALARM_VOLUME, SERVICE_DEFAULTS[CONF_ALARM_VOLUME]),
                ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
                vol.Optional(
                    CONF_SNOOZE_DURATION,
                    default=defaults.get(CONF_SNOOZE_DURATION, DEFAULT_SNOOZE_DURATION),
                    description="Snooze duration in minutes",
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=60)),
                vol.Optional(
                    CONF_AUTO_DISMISS_DURATION,
                    default=defaults.get(CONF_AUTO_DISMISS_DURATION, DEFAULT_AUTO_DISMISS_DURATION),
                    description="Auto-dismiss alarm after this many minutes",
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=120)),
                vol.Optional(
                    "custom_sound_path",
                    default=defaults.get("custom_sound_path", ""),
                    description="Custom sound file path (e.g., /local/my_sounds/alarm.mp3)",
                ): str,
                vol.Optional(
                    CONF_LED_ENTITY,
                    default=defaults.get(CONF_LED_ENTITY),
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="light")
                ),
                vol.Optional(
                    CONF_LED_COLOR,
                    default=defaults.get(CONF_LED_COLOR, DEFAULT_LED_COLOR),
                ): selector.ColorRGBSelector(),
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors=errors,
        )
