"""Tests for the SSD IMS sensor entities."""

from unittest.mock import MagicMock

from custom_components.ssd_ims.const import DOMAIN
from custom_components.ssd_ims.sensor import SsdImsSensor


def test_device_shows_eic_code_as_serial_number():
    """The POD's EIC code is the device's serial number."""
    sensor = SsdImsSensor(MagicMock(), "24ZSS0000000000X", "Rodinný dom")

    device_info = sensor.device_info
    assert device_info["identifiers"] == {(DOMAIN, "24ZSS0000000000X")}
    assert device_info["name"] == "Rodinný dom"
    assert device_info["serial_number"] == "24ZSS0000000000X"
