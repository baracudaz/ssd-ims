"""Sensor platform for SSD IMS integration."""

import logging
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy, UnitOfPower
from homeassistant.const import Platform
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er, issue_registry as ir
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    CONF_POD_NAME_MAPPING,
    CONF_POINT_OF_DELIVERY,
    DEFAULT_POINT_OF_DELIVERY,
    DOMAIN,
    PORTAL_URL,
    SENSOR_TYPE_ACTUAL_CONSUMPTION,
    SENSOR_TYPE_ACTUAL_SUPPLY,
    SENSOR_TYPE_LABELS,
    SUPPLIER_PRICE_DOMAIN,
)
from .helpers import sanitize_name
from .coordinator import SsdImsDataCoordinator
from .invoice_check import (
    BANDS,
    STATUS_MISMATCH,
    STATUS_OK,
    InvoiceCheck,
    check_invoice,
    parse_date,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SSD IMS sensors from config entry."""
    coordinator: SsdImsDataCoordinator = config_entry.runtime_data

    pod_ids = config_entry.data.get(CONF_POINT_OF_DELIVERY, DEFAULT_POINT_OF_DELIVERY)
    pod_name_mapping = config_entry.data.get(CONF_POD_NAME_MAPPING, {})

    enabled_sensor_types = [SENSOR_TYPE_ACTUAL_CONSUMPTION, SENSOR_TYPE_ACTUAL_SUPPLY]

    sensors = []
    for pod_id in pod_ids:
        friendly_name = pod_name_mapping.get(pod_id, pod_id)
        sensors.append(SsdImsLastUpdateSensor(coordinator, pod_id, friendly_name))
        sensors.extend(
            SsdImsRegisterSensor(coordinator, pod_id, friendly_name, description)
            for description in REGISTER_SENSORS
        )
        for sensor_type in enabled_sensor_types:
            sensors.append(
                SsdImsYesterdaySensor(
                    coordinator,
                    sensor_type,
                    pod_id,
                    friendly_name,
                )
            )
            sensors.append(
                SsdImsCumulativeSensor(
                    coordinator,
                    sensor_type,
                    pod_id,
                    friendly_name,
                )
            )

    # The invoice check needs the supplier's billed consumption sensors;
    # add it for a POD once they exist, also when they appear later.
    checked: set[str] = set()

    @callback
    def _invoice_checks() -> list[SsdImsInvoiceCheckSensor]:
        new = [
            SsdImsInvoiceCheckSensor(
                coordinator, pod_id, pod_name_mapping.get(pod_id, pod_id)
            )
            for pod_id in pod_ids
            if pod_id not in checked and billed_entity_ids(hass, pod_id)
        ]
        checked.update(sensor.pod_id for sensor in new)
        return new

    @callback
    def _registry_updated(event: Event) -> None:
        if event.data["action"] == "create" and (new := _invoice_checks()):
            async_add_entities(new)

    config_entry.async_on_unload(
        hass.bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, _registry_updated)
    )

    async_add_entities([*sensors, *_invoice_checks()])


class SsdImsSensor(CoordinatorEntity[SsdImsDataCoordinator], SensorEntity):
    """Base sensor for SSD IMS data."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SsdImsDataCoordinator,
        pod_id: str,
        friendly_name: str,
    ) -> None:
        """Initialize sensor."""
        super().__init__(coordinator)
        self.pod_id = pod_id
        self.friendly_name = friendly_name

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self.pod_id)},
            name=self.friendly_name,
            manufacturer="Stredoslovenská distribučná, a.s.",
            model="Odberné miesto elektriny",
            configuration_url=PORTAL_URL,
            # The EIC code from the invoice, so the device can be matched to it.
            serial_number=self.pod_id,
        )

    def _setup_entity_naming(self, sensor_name: str) -> None:
        """Set up entity naming."""
        self._attr_name = sensor_name


class SsdImsEnergySensor(SsdImsSensor):
    """Base class for energy sensors."""

    def __init__(
        self,
        coordinator: SsdImsDataCoordinator,
        sensor_type: str,
        pod_id: str,
        friendly_name: str,
    ) -> None:
        """Initialize energy sensor."""
        super().__init__(coordinator, pod_id, friendly_name)
        self.sensor_type = sensor_type
        self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
        self._attr_device_class = SensorDeviceClass.ENERGY

    def _generate_sensor_name(self, suffix: str) -> str:
        """Generate sensor name based on type and suffix."""
        type_name = SENSOR_TYPE_LABELS.get(self.sensor_type, "Energy")
        return f"{type_name} {suffix}"


class SsdImsYesterdaySensor(SsdImsEnergySensor):
    """Sensor for yesterday's values."""

    _attr_entity_registry_enabled_default = True

    def __init__(
        self,
        coordinator: SsdImsDataCoordinator,
        sensor_type: str,
        pod_id: str,
        friendly_name: str,
    ) -> None:
        """Initialize yesterday sensor."""
        super().__init__(coordinator, sensor_type, pod_id, friendly_name)
        # This is a self-contained daily snapshot, replaced once a day, and
        # can legitimately be lower than the previous day's value — not a
        # running total. TOTAL_INCREASING/TOTAL would make HA generate its
        # own long-term statistics for this entity, duplicating (and
        # potentially conflicting with) the external statistics the
        # coordinator writes directly for the Energy dashboard. MEASUREMENT
        # isn't a legal alternative either: HA's ENERGY device class only
        # accepts state_class None, TOTAL, or TOTAL_INCREASING (using
        # MEASUREMENT logs an "impossible" warning and is expected to raise
        # in a future HA version) — so leave state_class unset (None), which
        # also means no HA-generated statistics at all for this entity.

        sensor_name = self._generate_sensor_name("Yesterday")
        sanitized_sensor_name = sanitize_name(sensor_name)
        self._attr_unique_id = f"{pod_id}_{sanitized_sensor_name}_{sensor_type}"
        self._setup_entity_naming(sensor_name)

    @property
    def native_value(self) -> StateType | None:
        """Return sensor value (yesterday's total)."""
        if not self.coordinator.data or not (
            pod_data := self.coordinator.data.get(self.pod_id)
        ):
            return None

        aggregated_data = pod_data.get("aggregated_data", {})
        value = aggregated_data.get(self.sensor_type)
        return float(value) if value is not None else None


class SsdImsCumulativeSensor(SsdImsEnergySensor):
    """Sensor for cumulative total energy imported from statistics."""

    def __init__(
        self,
        coordinator: SsdImsDataCoordinator,
        sensor_type: str,
        pod_id: str,
        friendly_name: str,
    ) -> None:
        """Initialize cumulative sensor."""
        super().__init__(coordinator, sensor_type, pod_id, friendly_name)
        # This one genuinely mirrors an ever-increasing running total read
        # back from the coordinator's own statistics.
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING

        sensor_name = self._generate_sensor_name("Total")
        sanitized_sensor_name = sanitize_name(sensor_name)
        self._attr_unique_id = f"{pod_id}_{sanitized_sensor_name}_{sensor_type}_total"
        self._setup_entity_naming(sensor_name)

    @property
    def native_value(self) -> StateType | None:
        """Return cumulative total from statistics."""
        if not self.coordinator.data or not (
            pod_data := self.coordinator.data.get(self.pod_id)
        ):
            return None

        cumulative_totals = pod_data.get("cumulative_totals", {})
        value = cumulative_totals.get(self.sensor_type)
        return float(value) if value is not None else None


class SsdImsLastUpdateSensor(SsdImsSensor):
    def __init__(
        self,
        coordinator: SsdImsDataCoordinator,
        pod_id: str,
        friendly_name: str,
    ) -> None:
        """Initialize last update sensor."""
        super().__init__(coordinator, pod_id, friendly_name)
        self._attr_device_class = SensorDeviceClass.TIMESTAMP

        sensor_name = "Last Update"
        sanitized_sensor_name = sanitize_name(sensor_name)
        self._attr_unique_id = f"{pod_id}_{sanitized_sensor_name}"
        self._setup_entity_naming(sensor_name)

    @property
    def native_value(self) -> datetime | None:
        """Return sensor value (last update timestamp)."""
        if not self.coordinator.data or not (
            pod_data := self.coordinator.data.get(self.pod_id)
        ):
            return None

        last_update_str = pod_data.get("last_update")
        return dt_util.parse_datetime(last_update_str) if last_update_str else None


# (registry data key, entity name, unique-id suffix, is_energy)
REGISTER_SENSORS: tuple[tuple[str, str, str, bool], ...] = (
    ("consumption_vt", "High Tariff Meter Reading", "meter_reading_vt", True),
    ("consumption_nt", "Low Tariff Meter Reading", "meter_reading_nt", True),
    ("max_demand", "Peak Demand", "peak_demand", False),
)


class SsdImsRegisterSensor(SsdImsSensor):
    """Latest monthly meter register reading (Registrové údaje).

    The tariff readings are the meter's cumulative VT (1.8.1) / NT (1.8.2)
    counters; peak demand (1.6.0) is the highest quarter-hour demand of the
    period that ended at the reading. Values change at most a few times a
    month. For the Energy dashboard use the imported
    ``ssd_ims:<pod>_consumption_vt/_nt`` statistics instead, which place each
    month's consumption in the right month.
    """

    def __init__(
        self,
        coordinator: SsdImsDataCoordinator,
        pod_id: str,
        friendly_name: str,
        description: tuple[str, str, str, bool],
    ) -> None:
        """Initialize register sensor."""
        super().__init__(coordinator, pod_id, friendly_name)
        self._data_key, sensor_name, unique_suffix, is_energy = description
        if is_energy:
            self._attr_device_class = SensorDeviceClass.ENERGY
            self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
            self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        else:
            self._attr_device_class = SensorDeviceClass.POWER
            self._attr_native_unit_of_measurement = UnitOfPower.KILO_WATT
            self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_unique_id = f"{pod_id}_{unique_suffix}"
        self._setup_entity_naming(sensor_name)

    def _registry(self) -> dict[str, Any] | None:
        if not self.coordinator.data or not (
            pod_data := self.coordinator.data.get(self.pod_id)
        ):
            return None
        return pod_data.get("registry")

    @property
    def native_value(self) -> StateType | None:
        """Return the latest register value."""
        if not (registry := self._registry()):
            return None
        value = registry.get(self._data_key)
        return float(value) if value is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return reading date and meter serial number."""
        if not (registry := self._registry()):
            return None
        return {
            "reading_time": registry.get("reading_time"),
            "meter_serial_number": registry.get("serial_number"),
        }


def billed_entity_ids(hass: HomeAssistant, pod_id: str) -> dict[str, str]:
    """The supplier's billed consumption sensors of a POD, by tariff band."""
    registry = er.async_get(hass)
    return {
        band: entity_id
        for band in BANDS
        if (
            entity_id := registry.async_get_entity_id(
                Platform.SENSOR,
                SUPPLIER_PRICE_DOMAIN,
                f"ELECTRICITY_{pod_id}_billed_consumption_{band}",
            )
        )
    }


class SsdImsInvoiceCheckSensor(SsdImsSensor):
    """kWh billed on the last settlement invoice minus the metered kWh.

    The billed kWh come from the supplier integration's billed consumption
    sensors, the metered kWh from the register readings at the boundaries of
    the billed period. A difference beyond billing rounding raises a repair
    issue, removed again once an invoice matches.
    """

    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_suggested_display_precision = 1
    _attr_icon = "mdi:receipt-text-check-outline"

    def __init__(
        self,
        coordinator: SsdImsDataCoordinator,
        pod_id: str,
        friendly_name: str,
    ) -> None:
        """Initialize invoice check sensor."""
        super().__init__(coordinator, pod_id, friendly_name)
        self._attr_unique_id = f"{pod_id}_invoice_check"
        self._setup_entity_naming("Invoice Check")
        self._check: InvoiceCheck | None = None
        self._watched: frozenset[str] = frozenset()
        self._unsub_billed: Any = None

    @property
    def _issue_id(self) -> str:
        return f"invoice_mismatch_{self.pod_id}"

    async def async_added_to_hass(self) -> None:
        """Watch the billed consumption sensors and check the invoice."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.hass.bus.async_listen(
                er.EVENT_ENTITY_REGISTRY_UPDATED, self._async_registry_updated
            )
        )
        self.async_on_remove(self._unwatch_billed)
        self._watch_billed()
        self._update_check()

    @callback
    def _unwatch_billed(self) -> None:
        if self._unsub_billed:
            self._unsub_billed()
            self._unsub_billed = None

    @callback
    def _watch_billed(self) -> None:
        entity_ids = frozenset(billed_entity_ids(self.hass, self.pod_id).values())
        if entity_ids == self._watched:
            return
        self._unwatch_billed()
        self._watched = entity_ids
        if entity_ids:
            self._unsub_billed = async_track_state_change_event(
                self.hass, list(entity_ids), self._async_billed_changed
            )

    @callback
    def _async_registry_updated(self, event: Event) -> None:
        self._watch_billed()

    @callback
    def _async_billed_changed(self, event: Event) -> None:
        self._update_check()
        self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Recheck with the latest register readings."""
        self._update_check()
        super()._handle_coordinator_update()

    @callback
    def _update_check(self) -> None:
        """Compare the billed kWh with the register readings."""
        billed: dict[str, float] = {}
        period_from = period_to = None
        for band, entity_id in billed_entity_ids(self.hass, self.pod_id).items():
            state = self.hass.states.get(entity_id)
            if state is None:
                continue
            try:
                billed[band] = float(state.state)
            except ValueError:
                continue
            period_from = parse_date(state.attributes.get("period_from"))
            period_to = parse_date(state.attributes.get("period_to"))
        readings = self.coordinator.registry_readings(self.pod_id)
        if not billed or period_from is None or period_to is None or not readings:
            self._check = None
            return
        self._check = check_invoice(readings, period_from, period_to, billed)
        self._update_issue(self._check)

    @callback
    def _update_issue(self, check: InvoiceCheck) -> None:
        """Raise a repair issue on a mismatch, remove it once one matches."""
        if check.status == STATUS_OK:
            ir.async_delete_issue(self.hass, DOMAIN, self._issue_id)
            return
        if check.status != STATUS_MISMATCH:
            return
        details = "; ".join(
            f"{band.upper()}: {band_check.billed:g} kWh billed, "
            f"{band_check.metered:g} kWh metered"
            for band, band_check in check.bands.items()
        )
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            self._issue_id,
            is_fixable=False,
            is_persistent=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="invoice_mismatch",
            translation_placeholders={
                "name": self.friendly_name,
                "period_from": check.period_from.isoformat(),
                "period_to": check.period_to.isoformat(),
                "details": details,
            },
        )

    @property
    def native_value(self) -> StateType | None:
        """Total billed minus metered kWh."""
        if self._check is None or (difference := self._check.difference) is None:
            return None
        return round(difference, 3)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Status, billed period and the compared values per tariff."""
        if self._check is None:
            return None
        attrs: dict[str, Any] = {
            "status": self._check.status,
            "period_from": self._check.period_from.isoformat(),
            "period_to": self._check.period_to.isoformat(),
        }
        for band, band_check in self._check.bands.items():
            pct = band_check.difference_pct
            attrs.update(
                {
                    f"billed_{band}": band_check.billed,
                    f"metered_{band}": round(band_check.metered, 3),
                    f"difference_{band}": round(band_check.difference, 3),
                    f"difference_{band}_pct": None if pct is None else round(pct, 2),
                }
            )
        return attrs
