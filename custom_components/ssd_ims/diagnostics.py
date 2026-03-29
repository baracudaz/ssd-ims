"""Diagnostics support for SSD IMS integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from . import SsdImsConfigEntry

TO_REDACT = [CONF_USERNAME, CONF_PASSWORD]


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: SsdImsConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data

    coordinator_data: dict[str, Any] = {}
    for pod_id, pod_data in (getattr(coordinator, "data", None) or {}).items():
        coordinator_data[pod_id] = {
            "last_update": pod_data.get("last_update"),
            "cumulative_totals": pod_data.get("cumulative_totals"),
            "aggregated_data": pod_data.get("aggregated_data"),
        }

    return {
        "entry_data": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
        "pods_discovered": list((getattr(coordinator, "pods", None) or {}).keys()),
        "coordinator_data": coordinator_data,
    }
