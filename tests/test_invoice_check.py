"""Tests for checking billed kWh against the meter register readings."""

from datetime import date

import pytest
from homeassistant.util import dt as dt_util

from custom_components.ssd_ims.invoice_check import (
    STATUS_METER_REPLACED,
    STATUS_MISMATCH,
    STATUS_NO_READING,
    STATUS_OK,
    check_invoice,
    parse_date,
)
from custom_components.ssd_ims.models import RegistryReading


def _reading(day: date, vt: float, nt: float, serial: str = "M1") -> RegistryReading:
    """A register reading at local midnight starting the given day."""
    return RegistryReading(
        serial_number=serial,
        reading_time=dt_util.start_of_local_day(day),
        consumption_total=vt + nt,
        consumption_tariff1=vt,
        consumption_tariff2=nt,
    )


READINGS = [
    _reading(date(2025, 3, 1), 1000, 5000),
    _reading(date(2025, 9, 1), 1200, 6000),
    _reading(date(2026, 3, 1), 1500, 8000),
]


def test_matching_invoice():
    """Billed kWh equal to the register differences."""
    check = check_invoice(
        READINGS, date(2025, 3, 1), date(2026, 2, 28), {"vt": 500, "nt": 3000}
    )
    assert check.status == STATUS_OK
    assert check.bands["vt"].metered == 500
    assert check.bands["nt"].metered == 3000
    assert check.difference == 0


def test_rounding_to_whole_kwh_still_matches():
    """Bills are in whole kWh; up to 1 kWh (or 1 %) off is a match."""
    readings = [_reading(date(2025, 3, 1), 0.4, 0), _reading(date(2025, 4, 1), 10, 0)]
    check = check_invoice(readings, date(2025, 3, 1), date(2025, 3, 31), {"vt": 10})
    assert check.status == STATUS_OK
    assert check.bands["vt"].difference == pytest.approx(0.4)


def test_mismatch():
    """Billed more than metered in one tariff."""
    check = check_invoice(
        READINGS, date(2025, 3, 1), date(2026, 2, 28), {"vt": 550, "nt": 3000}
    )
    assert check.status == STATUS_MISMATCH
    assert check.bands["vt"].difference == 50
    assert check.bands["vt"].difference_pct == 10
    assert check.bands["nt"].matches
    assert check.difference == 50


def test_period_not_on_a_reading_is_not_compared():
    """A boundary without a register reading would need an estimate."""
    check = check_invoice(
        READINGS, date(2025, 3, 15), date(2026, 2, 28), {"vt": 500, "nt": 3000}
    )
    assert check.status == STATUS_NO_READING
    assert check.difference is None


def test_end_reading_not_published_yet():
    """The reading closing the period isn't available yet."""
    check = check_invoice(READINGS, date(2026, 3, 1), date(2026, 3, 31), {"vt": 1})
    assert check.status == STATUS_NO_READING


def test_meter_replaced_inside_the_period():
    """Counters of different meters can't be subtracted."""
    readings = [
        _reading(date(2025, 3, 1), 1000, 5000),
        _reading(date(2025, 9, 1), 10, 20, serial="M2"),
        _reading(date(2026, 3, 1), 300, 2000, serial="M2"),
    ]
    check = check_invoice(
        readings, date(2025, 3, 1), date(2026, 2, 28), {"vt": 500, "nt": 3000}
    )
    assert check.status == STATUS_METER_REPLACED


def test_single_rate_compares_the_total():
    """A JT bill is compared with both registers together."""
    check = check_invoice(READINGS, date(2025, 3, 1), date(2026, 2, 28), {"jt": 3500})
    assert check.status == STATUS_OK
    assert check.bands["jt"].metered == 3500


@pytest.mark.parametrize(
    "value",
    [date(2025, 3, 1), "2025-03-01", "2025-03-01T00:00:00+01:00"],
)
def test_parse_date(value):
    """Period attributes arrive as dates or ISO strings."""
    assert parse_date(value) == date(2025, 3, 1)


@pytest.mark.parametrize("value", [None, "", "soon", 5])
def test_parse_date_invalid(value):
    """Missing or invalid periods are None."""
    assert parse_date(value) is None
