"""Check the kWh billed on a settlement invoice against the meter registers.

The supplier bills a settlement period (``period_from`` to ``period_to``,
both inclusive) from meter readings; the distributor's register readings are
taken at local midnight on the 1st of each month. When both period
boundaries fall on a register reading, the metered kWh per tariff is the
difference of the cumulative counters, which is what the bill should match.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from homeassistant.util import dt as dt_util

from .models import RegistryReading

# Status of a check
STATUS_OK: str = "ok"
STATUS_MISMATCH: str = "mismatch"
# A period boundary has no register reading (not the 1st of a month, or the
# reading isn't published yet): nothing to compare without estimating.
STATUS_NO_READING: str = "no_reading"
# The meter was replaced (or its counter reset) inside the period.
STATUS_METER_REPLACED: str = "meter_replaced"

# Bills are in whole kWh: a difference within rounding is a match.
TOLERANCE_KWH: float = 1.0
TOLERANCE_RATIO: float = 0.01

BANDS: tuple[str, ...] = ("vt", "nt", "jt")


@dataclass(frozen=True)
class BandCheck:
    """Billed versus metered kWh of one tariff band."""

    billed: float
    metered: float

    @property
    def difference(self) -> float:
        """Billed minus metered kWh: positive means billed too much."""
        return self.billed - self.metered

    @property
    def difference_pct(self) -> float | None:
        """Difference as a percentage of the metered kWh."""
        if not self.metered:
            return None
        return self.difference / self.metered * 100

    @property
    def matches(self) -> bool:
        """Within billing rounding and a small relative tolerance."""
        return abs(self.difference) <= max(
            TOLERANCE_KWH, TOLERANCE_RATIO * abs(self.metered)
        )


@dataclass(frozen=True)
class InvoiceCheck:
    """Result of checking one settlement period."""

    period_from: date
    period_to: date
    status: str
    bands: Mapping[str, BandCheck]

    @property
    def difference(self) -> float | None:
        """Total billed minus metered kWh, when compared."""
        if not self.bands:
            return None
        return sum(band.difference for band in self.bands.values())


def parse_date(value: object) -> date | None:
    """A period attribute: a date, or an ISO date string."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _reading_at(
    readings: list[RegistryReading], day: date
) -> tuple[int, RegistryReading] | None:
    """The register reading taken at local midnight starting the given day."""
    when = dt_util.start_of_local_day(day)
    for index, reading in enumerate(readings):
        if reading.reading_time == when:
            return index, reading
    return None


def _metered(start: RegistryReading, end: RegistryReading, band: str) -> float | None:
    """kWh between two readings for a tariff band (JT: both registers)."""
    if band == "vt":
        attrs = ("consumption_tariff1",)
    elif band == "nt":
        attrs = ("consumption_tariff2",)
    elif start.consumption_total is not None and end.consumption_total is not None:
        return end.consumption_total - start.consumption_total
    else:
        attrs = ("consumption_tariff1", "consumption_tariff2")
    total = 0.0
    for attr in attrs:
        first, last = getattr(start, attr), getattr(end, attr)
        if first is None or last is None:
            return None
        total += last - first
    return total


def check_invoice(
    readings: list[RegistryReading],
    period_from: date,
    period_to: date,
    billed: Mapping[str, float],
) -> InvoiceCheck:
    """Compare the billed kWh per band with the register differences."""
    ordered = sorted(readings, key=lambda reading: reading.reading_time)
    start = _reading_at(ordered, period_from)
    end = _reading_at(ordered, period_to + timedelta(days=1))
    if start is None or end is None:
        return InvoiceCheck(period_from, period_to, STATUS_NO_READING, {})

    first, last = start[1], end[1]
    inside = ordered[start[0] : end[0] + 1]
    if any(reading.serial_number != first.serial_number for reading in inside):
        return InvoiceCheck(period_from, period_to, STATUS_METER_REPLACED, {})

    bands: dict[str, BandCheck] = {}
    for band in BANDS:
        if band not in billed:
            continue
        metered = _metered(first, last, band)
        if metered is None:
            continue
        if metered < 0:
            return InvoiceCheck(period_from, period_to, STATUS_METER_REPLACED, {})
        bands[band] = BandCheck(billed=billed[band], metered=metered)
    if not bands:
        return InvoiceCheck(period_from, period_to, STATUS_NO_READING, {})

    status = (
        STATUS_OK if all(band.matches for band in bands.values()) else STATUS_MISMATCH
    )
    return InvoiceCheck(period_from, period_to, status, bands)
