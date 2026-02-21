"""The Voice Alarm Assistant integration."""
from .const import DOMAIN

__all__ = ["DOMAIN"]

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from .alarm_manager import AlarmManager
from .const import ADDON_NAME
from .llm_functions import cleanup_llm_functions, setup_llm_functions
from .timer_manager import TimerManager

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Voice Alarm Assistant integration."""
    hass.data.setdefault(DOMAIN, {})
    _LOGGER.info(f"Setting up {ADDON_NAME} integration")
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Voice Alarm Assistant from a config entry."""
    _LOGGER.info(f"Setting up {ADDON_NAME} for entry: %s", entry.entry_id)

    # Initialize the alarm manager and timer manager
    alarm_manager = AlarmManager(hass)
    timer_manager = TimerManager(hass)
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN]["alarm_manager"] = alarm_manager
    hass.data[DOMAIN]["timer_manager"] = timer_manager
    hass.data[DOMAIN]["ringing_alarms"] = {}

    # Set up LLM functions
    config_data = {**entry.data, **entry.options}
    await setup_llm_functions(hass, config_data)

    # Start the alarm manager
    await alarm_manager.start()

    # Register update listener for options changes
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    _LOGGER.info(f"{ADDON_NAME} successfully set up")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.info(f"Unloading {ADDON_NAME} for entry: %s", entry.entry_id)

    # Stop the alarm manager
    alarm_manager = hass.data[DOMAIN].get("alarm_manager")
    if alarm_manager:
        await alarm_manager.stop()

    # Clean up LLM functions
    await cleanup_llm_functions(hass)

    # Clean up alarm manager and timer manager from hass.data
    hass.data[DOMAIN].pop("alarm_manager", None)
    hass.data[DOMAIN].pop("timer_manager", None)

    _LOGGER.info(f"{ADDON_NAME} successfully unloaded")
    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the config entry when options change."""
    _LOGGER.info(f"Reloading {ADDON_NAME} for entry: %s", entry.entry_id)

    # Update config and reschedule alarms
    config_data = {**entry.data, **entry.options}
    await setup_llm_functions(hass, config_data)

    # Reschedule all alarms with new configuration
    alarm_manager = hass.data[DOMAIN].get("alarm_manager")
    if alarm_manager:
        await alarm_manager.reschedule_all()

    _LOGGER.info(f"{ADDON_NAME} successfully reloaded")
