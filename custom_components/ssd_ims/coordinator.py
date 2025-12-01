"""Data coordinator for SSD IMS integration."""
import asyncio
import logging
import re
import random
from datetime import datetime, timedelta
from typing import Any, Dict

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics, get_last_statistics, statistics_during_period, StatisticMeanType)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import (DataUpdateCoordinator,
                                                      UpdateFailed)
from homeassistant.util import dt as dt_util

from .api_client import SsdImsApiClient
from .const import (API_DELAY_MAX, API_DELAY_MIN,
                    CONF_ENABLE_SUPPLY_SENSORS, CONF_HISTORY_DAYS,
                    CONF_HISTORY_IMPORT_DONE, CONF_POINT_OF_DELIVERY,
                    CONF_SCAN_INTERVAL,
                    DEFAULT_ENABLE_SUPPLY_SENSORS, DEFAULT_HISTORY_DAYS,
                    DEFAULT_POINT_OF_DELIVERY, DEFAULT_SCAN_INTERVAL, DOMAIN,
                    SENSOR_TYPE_ACTUAL_CONSUMPTION, SENSOR_TYPE_ACTUAL_SUPPLY,
                    TIME_PERIODS_CONFIG)
from .models import ChartData, PointOfDelivery

_LOGGER = logging.getLogger(__name__)


def _sanitize_name(name: str) -> str:
    """Sanitize name for use in entity IDs (same as in sensor.py)."""
    # Replace spaces and special characters with underscores
    sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    # Remove multiple consecutive underscores
    sanitized = re.sub(r"_+", "_", sanitized)
    # Remove leading/trailing underscores
    sanitized = sanitized.strip("_")
    return sanitized


class SsdImsDataCoordinator(DataUpdateCoordinator):
    """Data coordinator for SSD IMS integration."""

    def __init__(
        self, hass: HomeAssistant, api_client: SsdImsApiClient, config: Dict[str, Any], entry: ConfigEntry
    ) -> None:
        """Initialize coordinator."""
        self.api_client = api_client
        self.config = config
        self.entry = entry
        self.pods: Dict[str, PointOfDelivery] = {}  # pod_id -> PointOfDelivery
        self._last_data_date: str | None = None  # Track the last date we fetched data for
        self._history_import_done: bool = entry.data.get(CONF_HISTORY_IMPORT_DONE, False)

        scan_interval = timedelta(
            minutes=config.get("scan_interval", DEFAULT_SCAN_INTERVAL)
        )

        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=scan_interval)

    async def update_config(self, new_config: Dict[str, Any]) -> None:
        """Update coordinator configuration and trigger data refresh."""
        old_config = self.config.copy()
        self.config.update(new_config)
        
        # Check if sensor configuration changed
        sensor_config_changed = (
            old_config.get(CONF_ENABLE_SUPPLY_SENSORS) != new_config.get(CONF_ENABLE_SUPPLY_SENSORS)
        )
        
        # Check if scan interval changed
        scan_interval_changed = (
            old_config.get(CONF_SCAN_INTERVAL) != new_config.get(CONF_SCAN_INTERVAL)
        )
        
        # Update scan interval if changed
        if scan_interval_changed:
            new_scan_interval = new_config.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            self.update_interval = timedelta(minutes=new_scan_interval)
            _LOGGER.info("Updated scan interval to %d minutes", new_scan_interval)
        
        # Trigger immediate data refresh if sensor configuration changed
        if sensor_config_changed:
            _LOGGER.info(
                "Sensor configuration changed (supply: %s), triggering immediate data refresh",
                new_config.get(CONF_ENABLE_SUPPLY_SENSORS)
            )
            await self.async_request_refresh()
        else:
            _LOGGER.debug("No sensor configuration changes detected")

    def _get_random_api_delay(self) -> float:
        """Get random API delay between configured min and max values."""
        # Generate random delay between API_DELAY_MIN and API_DELAY_MAX
        delay = random.uniform(API_DELAY_MIN, API_DELAY_MAX)
        # Ensure minimum of 1 second (hardcoded as requested)
        return max(0.3, delay)

    async def _import_history_statistics(self, pod_id: str, pod_name: str, history_days: int) -> None:
        """Import past data into Home Assistant statistics."""
        try:
            # Get sensor configuration to determine which sensor types to import
            enable_supply_sensors = self.config.get(
                CONF_ENABLE_SUPPLY_SENSORS, DEFAULT_ENABLE_SUPPLY_SENSORS
            )

            # Build list of enabled sensor types for history import
            enabled_sensor_types = [SENSOR_TYPE_ACTUAL_CONSUMPTION]  # Always enabled
            if enable_supply_sensors:
                enabled_sensor_types.append(SENSOR_TYPE_ACTUAL_SUPPLY)

            _LOGGER.info(
                "Importing %d days of past data for POD %s (sensor types: %s)",
                history_days,
                pod_id,
                enabled_sensor_types
            )

            now = dt_util.now()
            # Calculate the start date (N days ago from yesterday)
            end_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
            start_date = end_date - timedelta(days=history_days)

            _LOGGER.debug(
                "History import range for POD %s: %s to %s",
                pod_id,
                start_date,
                end_date
            )

            # Initialize statistics only for enabled sensor types
            statistics = {sensor_type: [] for sensor_type in enabled_sensor_types}

            for day_offset in range(history_days, 0, -1):
                day_end_local = end_date - timedelta(days=day_offset - 1)
                day_start = day_end_local - timedelta(days=1)
                # Convert end date to UTC (23:00 UTC = midnight local time)
                from datetime import timezone
                day_end = day_end_local.astimezone(timezone.utc)

                try:
                    # Add delay before each API call
                    if day_offset < history_days:
                        delay = self._get_random_api_delay()
                        _LOGGER.debug(
                            "Sleeping %.2f seconds before fetching past data for %s",
                            delay,
                            day_start.strftime("%Y-%m-%d")
                        )
                        await asyncio.sleep(delay)

                    # Fetch data for this day
                    chart_data = await self.api_client.get_chart_data(
                        pod_id, day_start, day_end
                    )
                    _LOGGER.debug(
                        "API response for history date %s: %s",
                        day_start.strftime("%Y-%m-%d"),
                        chart_data,
                    )

                    # Import hourly statistics (aggregate 15-minute intervals into hours)
                    if chart_data and chart_data.metering_datetime:
                        # Aggregate 15-minute data into hourly buckets (only for enabled sensor types)
                        hourly_data = {sensor_type: {} for sensor_type in enabled_sensor_types}

                        # Parse timestamps and aggregate into hours
                        for i, timestamp_str in enumerate(chart_data.metering_datetime):
                            try:
                                # Parse the timestamp (UTC)
                                # NOTE: API timestamps represent the END of each 15-minute interval
                                # So we need to subtract 15 minutes to get the start of the interval
                                timestamp_end_utc = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                                timestamp_start_utc = timestamp_end_utc - timedelta(minutes=15)

                                # Round down to the top of the hour (keep in UTC - HA expects UTC timestamps)
                                hour_timestamp = timestamp_start_utc.replace(minute=0, second=0, microsecond=0)

                                # Log first and last timestamp conversion for debugging
                                if i == 0:
                                    _LOGGER.debug(
                                        "First timestamp: END=%s -> START=%s -> Hour bucket=%s",
                                        timestamp_end_utc.isoformat(),
                                        timestamp_start_utc.isoformat(),
                                        hour_timestamp.isoformat()
                                    )
                                if i == len(chart_data.metering_datetime) - 1:
                                    _LOGGER.debug(
                                        "Last timestamp: END=%s -> START=%s -> Hour bucket=%s",
                                        timestamp_end_utc.isoformat(),
                                        timestamp_start_utc.isoformat(),
                                        hour_timestamp.isoformat()
                                    )

                                # Aggregate data only for enabled sensor types
                                if SENSOR_TYPE_ACTUAL_CONSUMPTION in enabled_sensor_types and i < len(chart_data.actual_consumption):
                                    value = chart_data.actual_consumption[i]
                                    if value is not None:
                                        if hour_timestamp not in hourly_data[SENSOR_TYPE_ACTUAL_CONSUMPTION]:
                                            hourly_data[SENSOR_TYPE_ACTUAL_CONSUMPTION][hour_timestamp] = 0.0
                                        hourly_data[SENSOR_TYPE_ACTUAL_CONSUMPTION][hour_timestamp] += value * 0.25

                                if SENSOR_TYPE_ACTUAL_SUPPLY in enabled_sensor_types and i < len(chart_data.actual_supply):
                                    value = chart_data.actual_supply[i]
                                    if value is not None:
                                        if hour_timestamp not in hourly_data[SENSOR_TYPE_ACTUAL_SUPPLY]:
                                            hourly_data[SENSOR_TYPE_ACTUAL_SUPPLY][hour_timestamp] = 0.0
                                        hourly_data[SENSOR_TYPE_ACTUAL_SUPPLY][hour_timestamp] += value * 0.25

                            except Exception as e:
                                _LOGGER.warning(
                                    "Failed to parse timestamp %s: %s",
                                    timestamp_str,
                                    e
                                )
                                continue

                        # Add hourly statistics to the collection (will be converted to cumulative later)
                        for sensor_type, hours in hourly_data.items():
                            for hour_timestamp, hourly_value in sorted(hours.items()):
                                statistics[sensor_type].append({
                                    "start": hour_timestamp,
                                    "hourly_value": hourly_value,  # Store hourly value temporarily
                                })
                                # Log the first few hourly aggregations for debugging
                                if len(statistics[sensor_type]) <= 3:
                                    _LOGGER.debug(
                                        "Hour %s: %.3f kWh (%s)",
                                        hour_timestamp.isoformat(),
                                        hourly_value,
                                        sensor_type
                                    )

                        _LOGGER.debug(
                            "Past data for %s: %d intervals aggregated into %d hours, API sum=%.3f kWh, aggregated sum=%.3f kWh",
                            day_start.strftime("%Y-%m-%d"),
                            len(chart_data.metering_datetime),
                            len(hourly_data.get(SENSOR_TYPE_ACTUAL_CONSUMPTION, {})),
                            chart_data.sum_actual_consumption or 0.0,
                            sum(hourly_data.get(SENSOR_TYPE_ACTUAL_CONSUMPTION, {}).values())
                        )

                except Exception as e:
                    _LOGGER.warning(
                        "Failed to fetch past data for %s: %s",
                        day_start.strftime("%Y-%m-%d"),
                        e
                    )
                    continue

            # Convert hourly values to cumulative sums
            for sensor_type in statistics:
                cumulative_sum = 0.0
                cumulative_stats = []
                # Sort by timestamp to ensure proper cumulative calculation
                for stat in sorted(statistics[sensor_type], key=lambda x: x["start"]):
                    cumulative_sum += stat["hourly_value"]
                    cumulative_stats.append({
                        "start": stat["start"],
                        "sum": cumulative_sum,
                    })
                statistics[sensor_type] = cumulative_stats

            # Import statistics into Home Assistant
            for sensor_type, stats in statistics.items():
                if not stats:
                    continue

                # Build statistic_id using sensor_type directly
                # Map sensor types to their statistic name components
                statistic_type_names = {
                    SENSOR_TYPE_ACTUAL_CONSUMPTION: "actual_consumption",
                    SENSOR_TYPE_ACTUAL_SUPPLY: "actual_supply",
                }

                statistic_type = statistic_type_names.get(sensor_type, sensor_type)

                # Sanitize the friendly name
                sanitized_friendly_name = _sanitize_name(pod_name)

                # Build statistic_id for external statistics
                # Format: domain:statistic_name (both must be slugs - lowercase, no double underscores)
                statistic_name = f"{sanitized_friendly_name}_{statistic_type}".lower()
                statistic_id = f"{DOMAIN}:{statistic_name}"

                # Determine unit based on sensor type
                if sensor_type in [SENSOR_TYPE_ACTUAL_CONSUMPTION, SENSOR_TYPE_ACTUAL_SUPPLY]:
                    unit = "kWh"
                    device_class = "energy"
                else:
                    unit = "kVARh"
                    device_class = None

                metadata = {
                    "mean_type": StatisticMeanType.NONE,
                    "has_sum": True,
                    "name": f"{pod_name} {sensor_type.replace('_', ' ').title()}",
                    "source": DOMAIN,
                    "statistic_id": statistic_id,
                    "unit_of_measurement": unit,
                    "unit_class": "energy",
                }

                _LOGGER.info(
                    "Importing %d past statistics for %s into statistic_id: %s",
                    len(stats),
                    sensor_type,
                    statistic_id
                )

                _LOGGER.debug(
                    "Importing statistics for %s with metadata: %s and %d stats",
                    statistic_id,
                    metadata,
                    len(stats),
                )
                # Import the statistics
                async_add_external_statistics(self.hass, metadata, stats)

            _LOGGER.info(
                "Successfully imported past data for POD %s",
                pod_id
            )

        except Exception as e:
            _LOGGER.error(
                "Error importing past statistics for POD %s: %s",
                pod_id,
                e
            )
            raise

    async def _import_current_statistics(self, pod_data_dict: Dict[str, Any]) -> None:
        """Import current 15-minute interval statistics from recently fetched data."""
        try:
            # Get sensor configuration to determine which sensor types to import
            enable_supply_sensors = self.config.get(
                CONF_ENABLE_SUPPLY_SENSORS, DEFAULT_ENABLE_SUPPLY_SENSORS
            )

            # Build list of enabled sensor types for statistics import
            enabled_sensor_types = [SENSOR_TYPE_ACTUAL_CONSUMPTION]  # Always enabled
            if enable_supply_sensors:
                enabled_sensor_types.append(SENSOR_TYPE_ACTUAL_SUPPLY)

            for pod_id, pod_data in pod_data_dict.items():
                # Get friendly name for this POD
                pod_name_mapping = self.config.get("pod_name_mapping", {})
                pod_name = pod_name_mapping.get(pod_id, pod_id)

                # Get chart data for yesterday (the current period we're tracking)
                chart_data = pod_data.get("chart_data_yesterday")
                if not chart_data or not chart_data.metering_datetime:
                    _LOGGER.debug(
                        "No chart data available for current statistics import for POD %s",
                        pod_id
                    )
                    continue

                # Aggregate 15-minute data into hourly buckets (only for enabled sensor types)
                hourly_data = {sensor_type: {} for sensor_type in enabled_sensor_types}

                # Parse timestamps and aggregate into hours
                for i, timestamp_str in enumerate(chart_data.metering_datetime):
                    try:
                        # Parse the timestamp (UTC)
                        # NOTE: API timestamps represent the END of each 15-minute interval
                        # So we need to subtract 15 minutes to get the start of the interval
                        timestamp_end_utc = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                        timestamp_start_utc = timestamp_end_utc - timedelta(minutes=15)

                        # Round down to the top of the hour (keep in UTC - HA expects UTC timestamps)
                        hour_timestamp = timestamp_start_utc.replace(minute=0, second=0, microsecond=0)

                        # Aggregate data only for enabled sensor types
                        if SENSOR_TYPE_ACTUAL_CONSUMPTION in enabled_sensor_types and i < len(chart_data.actual_consumption):
                            value = chart_data.actual_consumption[i]
                            if value is not None:
                                if hour_timestamp not in hourly_data[SENSOR_TYPE_ACTUAL_CONSUMPTION]:
                                    hourly_data[SENSOR_TYPE_ACTUAL_CONSUMPTION][hour_timestamp] = 0.0
                                hourly_data[SENSOR_TYPE_ACTUAL_CONSUMPTION][hour_timestamp] += value * 0.25

                        if SENSOR_TYPE_ACTUAL_SUPPLY in enabled_sensor_types and i < len(chart_data.actual_supply):
                            value = chart_data.actual_supply[i]
                            if value is not None:
                                if hour_timestamp not in hourly_data[SENSOR_TYPE_ACTUAL_SUPPLY]:
                                    hourly_data[SENSOR_TYPE_ACTUAL_SUPPLY][hour_timestamp] = 0.0
                                hourly_data[SENSOR_TYPE_ACTUAL_SUPPLY][hour_timestamp] += value * 0.25
                    except Exception as e:
                        _LOGGER.warning(
                            "Failed to parse timestamp %s for current statistics: %s",
                            timestamp_str,
                            e
                        )
                        continue

                # Convert hourly aggregates to cumulative statistics list (only for enabled sensor types)
                statistics_to_import = {sensor_type: [] for sensor_type in enabled_sensor_types}

                for sensor_type, hours in hourly_data.items():
                    # Build statistic_id to fetch the last stat
                    statistic_type_names = {
                        SENSOR_TYPE_ACTUAL_CONSUMPTION: "actual_consumption",
                        SENSOR_TYPE_ACTUAL_SUPPLY: "actual_supply",
                    }
                    statistic_type = statistic_type_names.get(sensor_type, sensor_type)
                    sanitized_friendly_name = _sanitize_name(pod_name)
                    statistic_name = f"{sanitized_friendly_name}_{statistic_type}".lower()
                    statistic_id = f"{DOMAIN}:{statistic_name}"

                    # Get the last known statistic to continue the cumulative sum
                    last_stats = await get_instance(self.hass).async_add_executor_job(
                        get_last_statistics, self.hass, 1, statistic_id, True, {"sum"}
                    )
                    
                    cumulative_sum = 0.0
                    last_stat_timestamp = None
                    if last_stats and statistic_id in last_stats:
                        last_stat = last_stats[statistic_id][0]
                        cumulative_sum = last_stat.get("sum", 0.0)
                        last_stat_timestamp = last_stat.get("start")
                        _LOGGER.debug(
                            "Found last statistic for %s. Sum: %.3f, Timestamp: %s",
                            statistic_id,
                            cumulative_sum,
                            last_stat_timestamp.isoformat() if last_stat_timestamp else "None"
                        )

                    for hour_timestamp, hourly_value in sorted(hours.items()):
                        # Only add stats for hours after the last recorded stat
                        if last_stat_timestamp and hour_timestamp <= last_stat_timestamp:
                            continue

                        # Add hourly value to cumulative sum
                        cumulative_sum += hourly_value
                        statistics_to_import[sensor_type].append({
                            "start": hour_timestamp,
                            "sum": cumulative_sum,
                        })

                # Import statistics for each sensor type
                for sensor_type, stats in statistics_to_import.items():
                    if not stats:
                        continue

                    # Build statistic_id using sensor_type directly
                    # Map sensor types to their statistic name components
                    statistic_type_names = {
                        SENSOR_TYPE_ACTUAL_CONSUMPTION: "actual_consumption",
                        SENSOR_TYPE_ACTUAL_SUPPLY: "actual_supply",
                    }

                    statistic_type = statistic_type_names.get(sensor_type, sensor_type)

                    # Sanitize the friendly name
                    sanitized_friendly_name = _sanitize_name(pod_name)

                    # Build statistic_id
                    statistic_name = f"{sanitized_friendly_name}_{statistic_type}".lower()
                    statistic_id = f"{DOMAIN}:{statistic_name}"

                    # Determine unit and device_class
                    if sensor_type in [SENSOR_TYPE_ACTUAL_CONSUMPTION, SENSOR_TYPE_ACTUAL_SUPPLY]:
                        unit = "kWh"
                        device_class = "energy"
                    else:
                        unit = "kVARh"
                        device_class = None

                    metadata = {
                        "mean_type": StatisticMeanType.NONE,
                        "has_sum": True,
                        "name": f"{pod_name} {sensor_type.replace('_', ' ').title()}",
                        "source": DOMAIN,
                        "statistic_id": statistic_id,
                        "unit_of_measurement": unit,
                        "unit_class": "energy",
                    }

                    _LOGGER.debug(
                        "Importing %d hourly statistics for %s (POD: %s) into statistic_id: %s",
                        len(stats),
                        sensor_type,
                        pod_id,
                        statistic_id
                    )

                    _LOGGER.debug(
                        "Importing statistics for %s with metadata: %s and %d stats",
                        statistic_id,
                        metadata,
                        len(stats),
                    )
                    # Import the statistics
                    async_add_external_statistics(self.hass, metadata, stats)

                _LOGGER.info(
                    "Successfully imported current hourly statistics for POD %s",
                    pod_id
                )

        except Exception as e:
            _LOGGER.error(
                "Error importing current statistics: %s",
                e
            )
            # Don't raise - we don't want to break the update cycle

    async def _fetch_cumulative_totals_from_statistics(self, pod_data_dict: Dict[str, Any]) -> None:
        """Fetch cumulative totals from external statistics and add to pod data for sensors."""
        try:
            # Get sensor configuration
            enable_supply_sensors = self.config.get(
                CONF_ENABLE_SUPPLY_SENSORS, DEFAULT_ENABLE_SUPPLY_SENSORS
            )

            # Build list of enabled sensor types
            enabled_sensor_types = [SENSOR_TYPE_ACTUAL_CONSUMPTION]
            if enable_supply_sensors:
                enabled_sensor_types.append(SENSOR_TYPE_ACTUAL_SUPPLY)

            for pod_id, pod_data in pod_data_dict.items():
                # Get friendly name for this POD
                pod_name_mapping = self.config.get("pod_name_mapping", {})
                pod_name = pod_name_mapping.get(pod_id, pod_id)

                # Initialize cumulative_totals dict if not exists
                if "cumulative_totals" not in pod_data:
                    pod_data["cumulative_totals"] = {}

                for sensor_type in enabled_sensor_types:
                    # Build statistic_id (same as used in import)
                    statistic_type_names = {
                        SENSOR_TYPE_ACTUAL_CONSUMPTION: "actual_consumption",
                        SENSOR_TYPE_ACTUAL_SUPPLY: "actual_supply",
                    }
                    statistic_type = statistic_type_names.get(sensor_type, sensor_type)
                    sanitized_friendly_name = _sanitize_name(pod_name)
                    statistic_name = f"{sanitized_friendly_name}_{statistic_type}".lower()
                    statistic_id = f"{DOMAIN}:{statistic_name}"

                    # Fetch the last statistic value
                    last_stats = await get_instance(self.hass).async_add_executor_job(
                        get_last_statistics, self.hass, 1, statistic_id, True, {"sum"}
                    )

                    if last_stats and statistic_id in last_stats:
                        last_stat = last_stats[statistic_id][0]
                        cumulative_total = last_stat.get("sum", 0.0)
                        pod_data["cumulative_totals"][sensor_type] = cumulative_total
                        _LOGGER.debug(
                            "Fetched cumulative total for %s (%s): %.3f kWh",
                            pod_id,
                            sensor_type,
                            cumulative_total
                        )
                    else:
                        # No statistics yet, use 0
                        pod_data["cumulative_totals"][sensor_type] = 0.0
                        _LOGGER.debug(
                            "No statistics found for %s (%s), using 0.0",
                            pod_id,
                            sensor_type
                        )

        except Exception as e:
            _LOGGER.error(
                "Error fetching cumulative totals from statistics: %s",
                e
            )
            # Don't raise - we don't want to break the update cycle

    async def _async_update_data(self) -> Dict[str, Any]:
        """Fetch data from API."""
        try:
            _LOGGER.info("Starting data update for SSD IMS integration")

            # Get POD configuration - now using stable pod_ids instead of pod_texts
            pod_ids = self.config.get(CONF_POINT_OF_DELIVERY, DEFAULT_POINT_OF_DELIVERY)
            if not pod_ids:
                _LOGGER.info("No PODs configured, discovering available PODs")
                # Discover PODs if not configured
                await self._discover_pods()
                pod_ids = list(self.pods.keys())
                _LOGGER.info("Discovered %d PODs: %s", len(pod_ids), pod_ids)
            else:
                _LOGGER.info("Using configured PODs: %s", pod_ids)
                _LOGGER.debug("Available POD IDs: %s", list(self.pods.keys()))

                # Check if we need to discover PODs (e.g., if configured PODs are not
                # found)
                if not self.pods:
                    _LOGGER.info("No PODs discovered yet, discovering available PODs")
                    await self._discover_pods()

                # Check if any configured PODs are not found
                missing_pods = [pod for pod in pod_ids if pod not in self.pods]
                if missing_pods:
                    _LOGGER.warning("Some configured PODs not found: %s", missing_pods)
                    _LOGGER.debug("Available PODs: %s", list(self.pods.keys()))
                    _LOGGER.debug("Configured PODs: %s", pod_ids)

                    # Remove missing PODs from the list
                    pod_ids = [pod for pod in pod_ids if pod in self.pods]
                    _LOGGER.info("Using available PODs: %s", pod_ids)

            # Use Home Assistant's configured timezone for correct local time calculations
            now = dt_util.now()
            yesterday_date = (now - timedelta(days=1)).strftime("%Y-%m-%d")

            _LOGGER.debug("Current time in HA timezone: %s", now)

            # Check if we need to import past data on first run
            if not self._history_import_done:
                history_days = self.config.get(CONF_HISTORY_DAYS, DEFAULT_HISTORY_DAYS)

                # Only import if history_days > 0 (user enabled import)
                if history_days > 0:
                    _LOGGER.info(
                        "First run detected: will import %d days of past data after fetching current data",
                        history_days
                    )

                    # Import past data for each POD
                    for pod_id in pod_ids:
                        pod = self.pods.get(pod_id)
                        if pod:
                            # Get friendly name for this POD
                            pod_name_mapping = self.config.get("pod_name_mapping", {})
                            pod_name = pod_name_mapping.get(pod_id, pod_id)

                            try:
                                await self._import_history_statistics(pod_id, pod_name, history_days)
                            except Exception as e:
                                _LOGGER.error(
                                    "Failed to import past data for POD %s: %s",
                                    pod_id,
                                    e
                                )
                                # Continue with other PODs even if one fails
                                continue

                    _LOGGER.info("Past data import completed")
                else:
                    _LOGGER.info("Past data import skipped (disabled by user)")

                # Mark past data import as done (whether imported or skipped)
                self._history_import_done = True
                new_data = dict(self.entry.data)
                new_data[CONF_HISTORY_IMPORT_DONE] = True
                self.hass.config_entries.async_update_entry(self.entry, data=new_data)
                _LOGGER.info("Past data import marked as done")

            # Smart polling: Check if we already have data for yesterday
            # Data is only available up to yesterday and released once per day
            if self._last_data_date == yesterday_date and self.data:
                _LOGGER.info(
                    "Already have data for yesterday (%s), skipping API poll to reduce load",
                    yesterday_date
                )
                return self.data

            _LOGGER.info("Fetching new data for yesterday (%s)", yesterday_date)

            # Fetch data for each POD
            all_pod_data = {}

            for pod_index, pod_id in enumerate(pod_ids):
                _LOGGER.debug("Processing POD: %s", pod_id)
                try:
                    pod = self.pods.get(pod_id)
                    if not pod:
                        _LOGGER.warning(
                            "POD %s not found in discovered PODs, skipping", pod_id
                        )
                        _LOGGER.debug("Available PODs: %s", list(self.pods.keys()))
                        continue

                    # Calculate date ranges and fetch data for each configured period
                    chart_data_by_period = {}
                    period_info = {}
                    
                    _LOGGER.debug("Using random API delay between %s-%s seconds between requests", API_DELAY_MIN, API_DELAY_MAX)
                    
                    for period_index, (period_key, config) in enumerate(TIME_PERIODS_CONFIG.items()):
                        try:
                            # Use the callback to calculate date range
                            calculate_range = config["calculate_range"]
                            period_start, period_end = calculate_range(now)
                            
                            period_info[period_key] = {
                                "start": period_start,
                                "end": period_end,
                                "days": (period_end - period_start).days,
                                "display_name": config["display_name"]
                            }
                            
                            # Add delay before API call (except for first request)
                            if period_index > 0:
                                delay = self._get_random_api_delay()
                                _LOGGER.debug(
                                    "Sleeping %.2f seconds before fetching %s data for POD %s",
                                    delay, period_key, pod_id
                                )
                                await asyncio.sleep(delay)
                            
                            # Fetch chart data for this period
                            _LOGGER.debug("Fetching %s data for POD %s", period_key, pod_id)
                            chart_data_by_period[period_key] = await self.api_client.get_chart_data(
                                pod_id, period_start, period_end
                            )
                            _LOGGER.debug(
                                "API response for %s: %s",
                                period_key,
                                chart_data_by_period[period_key],
                            )
                            
                        except Exception as e:
                            _LOGGER.error(
                                "Error calculating date range for period %s: %s", 
                                period_key, e
                            )
                            continue

                    _LOGGER.debug(
                        "Time periods for POD %s: %s",
                        pod_id,
                        {k: f"{v['start']} to {v['end']} ({v['days']} days)" 
                         for k, v in period_info.items()}
                    )

                    # Log chart data summary for debugging
                    for period_key, chart_data in chart_data_by_period.items():
                        _LOGGER.debug(
                            "%s data for POD %s: metering_datetime count=%d, sum_actual_consumption=%s",
                            TIME_PERIODS_CONFIG[period_key]["display_name"],
                            pod_id,
                            len(chart_data.metering_datetime),
                            chart_data.sum_actual_consumption,
                        )

                    # Aggregate data by time periods using configurable chart data
                    aggregated_data = self._aggregate_data(chart_data_by_period)

                    _LOGGER.debug(
                        "Aggregated data for POD %s: %s", pod_id, aggregated_data
                    )

                    # Store POD data using stable pod_id as key
                    pod_data = {
                        "session_pod_id": pod.value,  # Store session pod_id for internal reference
                        "pod_text": pod.text,  # Store original text for reference
                        "aggregated_data": aggregated_data,
                        "last_update": now.isoformat(),
                    }
                    
                    # Add chart data for each period dynamically
                    for period_key, chart_data in chart_data_by_period.items():
                        pod_data[f"chart_data_{period_key}"] = chart_data
                    
                    all_pod_data[pod_id] = pod_data

                    # Add delay between PODs (except for last POD)
                    if pod_index < len(pod_ids) - 1:
                        delay = self._get_random_api_delay()
                        _LOGGER.debug(
                            "Sleeping %.2f seconds before processing next POD",
                            delay
                        )
                        await asyncio.sleep(delay)

                except Exception as e:
                    error_msg = str(e)
                    _LOGGER.error(
                        "Error fetching data for POD %s: %s", pod_id, error_msg
                    )

                    # Check if this is an authentication error
                    if any(
                        auth_error in error_msg.lower()
                        for auth_error in [
                            "not authenticated",
                            "authentication failed",
                            "session expired",
                            "re-authentication failed",
                            "text/html",
                        ]
                    ):
                        _LOGGER.error(
                            "Authentication error detected, stopping data update"
                        )
                        raise ConfigEntryAuthFailed("Authentication failed") from e

                    # Continue with other PODs for non-auth errors
                    continue

            # Import 15-minute statistics for all successfully fetched PODs
            await self._import_current_statistics(all_pod_data)

            # Fetch cumulative totals from external statistics for each POD and sensor type
            await self._fetch_cumulative_totals_from_statistics(all_pod_data)

            # Update the last data date to track when we successfully fetched data
            self._last_data_date = yesterday_date
            _LOGGER.info(
                "Data update completed successfully for %d PODs (data date: %s)",
                len(all_pod_data),
                yesterday_date
            )
            return all_pod_data

        except ConfigEntryAuthFailed:
            # Re-raise authentication failures
            raise
        except Exception as e:
            _LOGGER.error("Error updating data: %s", e)
            if "Not authenticated" in str(e) or "Authentication failed" in str(e):
                raise ConfigEntryAuthFailed("Authentication failed") from e
            raise UpdateFailed(f"Error updating data: {e}") from e

    async def _discover_pods(self) -> None:
        """Discover points of delivery."""
        try:
            pods = await self.api_client.get_points_of_delivery()
            if not pods:
                raise Exception("No points of delivery found")

            _LOGGER.debug(
                "Raw PODs from API: %s", [(pod.text, pod.value) for pod in pods]
            )

            # Store PODs by stable pod.id instead of text for stable identification
            self.pods = {}
            for pod in pods:
                try:
                    pod_id = pod.id  # Use stable 16-20 char ID
                    self.pods[pod_id] = pod
                except ValueError as e:
                    _LOGGER.warning(
                        "Skipping POD with invalid ID format: %s - %s", pod.text, e
                    )
                    continue

            _LOGGER.info("Discovered %d PODs", len(self.pods))
            _LOGGER.debug(
                "POD mapping (id -> value): %s",
                {pod_id: pod.value for pod_id, pod in self.pods.items()},
            )

        except Exception as e:
            error_msg = str(e)
            _LOGGER.error("Error discovering PODs: %s", error_msg)

            # Check if this is an authentication error
            if any(
                auth_error in error_msg.lower()
                for auth_error in [
                    "not authenticated",
                    "authentication failed",
                    "session expired",
                    "re-authentication failed",
                    "text/html",
                ]
            ):
                raise ConfigEntryAuthFailed(
                    "Authentication failed during POD discovery"
                ) from e

            raise

    def _aggregate_data(self, chart_data_by_period: Dict[str, ChartData]) -> Dict[str, Dict[str, float]]:
        """Aggregate data by different time periods using configurable chart data."""
        aggregated = {}
        
        # Get sensor configuration options
        enable_supply_sensors = self.config.get(
            CONF_ENABLE_SUPPLY_SENSORS, DEFAULT_ENABLE_SUPPLY_SENSORS
        )

        # Create list of enabled sensor types
        enabled_sensor_types = [SENSOR_TYPE_ACTUAL_CONSUMPTION]  # Always enabled

        if enable_supply_sensors:
            enabled_sensor_types.append(SENSOR_TYPE_ACTUAL_SUPPLY)
        
        for period_key, chart_data in chart_data_by_period.items():
            period_name = TIME_PERIODS_CONFIG[period_key]["display_name"]
            aggregated[period_key] = {}
            
            if chart_data and hasattr(chart_data, "sum_actual_consumption"):
                # Extract only enabled sensor values for this period
                if SENSOR_TYPE_ACTUAL_CONSUMPTION in enabled_sensor_types:
                    aggregated[period_key][SENSOR_TYPE_ACTUAL_CONSUMPTION] = (
                        chart_data.sum_actual_consumption or 0.0
                    )
                
                if SENSOR_TYPE_ACTUAL_SUPPLY in enabled_sensor_types:
                    aggregated[period_key][SENSOR_TYPE_ACTUAL_SUPPLY] = (
                        chart_data.sum_actual_supply or 0.0
                    )

                # Debug log only for enabled sensors
                debug_msg = f"{period_name} chart data summaries: actual_consumption={chart_data.sum_actual_consumption}"
                if enable_supply_sensors:
                    debug_msg += f", actual_supply={chart_data.sum_actual_supply}"
                
                _LOGGER.debug(debug_msg)
            else:
                # Fallback: set enabled sensor values to 0 if no chart data available
                for sensor_type in enabled_sensor_types:
                    aggregated[period_key][sensor_type] = 0.0
                _LOGGER.warning("No %s chart data available, setting %s values to 0", period_name, period_key)

        return aggregated
