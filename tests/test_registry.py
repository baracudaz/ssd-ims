"""Tests for tariff register readings (Registrové údaje): parsing, API client,
counter → delta conversion and statistics import."""

import asyncio
from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import ClientSession

from custom_components.ssd_ims.api_client import SsdImsApiClient
from custom_components.ssd_ims.const import (
    CONF_POD_NAME_MAPPING,
    CONF_PRICE_NT,
    CONF_PRICE_VT,
)
from custom_components.ssd_ims.coordinator import SsdImsDataCoordinator
from custom_components.ssd_ims.models import REGISTRY_COLUMNS, RegistryReading

POD_ID = "99XXX1234560000G"


def _reading(
    when: datetime,
    vt: float,
    nt: float,
    serial: str = "M1",
    max_demand: float = 3.0,
) -> RegistryReading:
    return RegistryReading(
        serial_number=serial,
        reading_time=when,
        max_demand=max_demand,
        consumption_total=vt + nt,
        consumption_tariff1=vt,
        consumption_tariff2=nt,
        supply_total=0.0,
    )


class TestRegistryReadingModel:
    def test_from_row_parses_portal_row(self):
        row = [
            "340016976",
            "2026-10-31T23:00:00.0000000Z",
            3.244,
            6295.263,
            350.743,
            5944.52,
            0,
        ]
        reading = RegistryReading.from_row(row)
        assert reading.serial_number == "340016976"
        assert reading.reading_time == datetime(2026, 10, 31, 23, tzinfo=UTC)
        assert reading.max_demand == 3.244
        assert reading.consumption_tariff1 == 350.743
        assert reading.consumption_tariff2 == 5944.52
        assert reading.supply_total == 0

    def test_from_row_keeps_seconds_of_ad_hoc_reading(self):
        reading = RegistryReading.from_row(
            ["1", "2026-10-24T18:21:10.0000000Z", None, None, 1.0, 2.0, None]
        )
        assert reading.reading_time == datetime(2026, 10, 24, 18, 21, 10, tzinfo=UTC)
        assert reading.max_demand is None

    def test_from_row_rejects_short_row(self):
        with pytest.raises(ValueError):
            RegistryReading.from_row(["1", "2026-10-31T23:00:00Z"])


class TestGetRegistryData:
    @pytest.fixture
    async def api_client(self):
        session = ClientSession()
        client = SsdImsApiClient(session)
        client._authenticated = True
        pod = MagicMock()
        pod.id = POD_ID
        pod.value = "session_value"
        pod.text = f"{POD_ID} (Home)"
        client._pods_cache = [pod]
        client._pods_cache_ts = datetime.now(UTC)
        yield client
        await session.close()

    async def test_request_payload_and_sorted_parsing(self, api_client):
        response_body = {
            "columns": [],
            "page": {"totalRows": 3, "currentPage": 1, "pageSize": 500},
            "rows": [
                {"values": ["M1", "2026-10-31T23:00:00.0000000Z", 3, 30, 3, 27, 0]},
                {"values": ["M1", "2026-09-30T22:00:00.0000000Z", 2, 20, 2, 18, 0]},
                {"values": ["garbage"]},
            ],
        }
        with patch.object(api_client._session, "request") as mock_request:
            mock_response = AsyncMock()
            mock_response.json = AsyncMock(return_value=response_body)
            mock_response.status = 200
            mock_response.headers = {"content-type": "application/json"}
            mock_request.return_value.__aenter__.return_value = mock_response

            readings = await api_client.get_registry_data(
                POD_ID,
                datetime(2025, 10, 1, tzinfo=UTC),
                datetime(2026, 11, 9, tzinfo=UTC),
            )

        # Unparseable row skipped, remaining rows sorted by time.
        assert [r.consumption_tariff1 for r in readings] == [2, 3]

        payload = mock_request.call_args.kwargs["json"]
        assert [c["member"] for c in payload["columns"]] == list(REGISTRY_COLUMNS)
        pod_filter = payload["filters"][0]
        assert pod_filter["member"] == "pointOfDeliveryId"
        assert pod_filter["value"] == "session_value"
        assert payload["filters"][1]["value"] == "2025-10-01T00:00:00.000Z"
        assert payload["filters"][2]["value"] == "2026-11-09T00:00:00.000Z"

    async def test_unexpected_response_raises(self, api_client):
        with patch.object(api_client._session, "request") as mock_request:
            mock_response = AsyncMock()
            mock_response.json = AsyncMock(return_value={"unexpected": True})
            mock_response.status = 200
            mock_response.headers = {"content-type": "application/json"}
            mock_request.return_value.__aenter__.return_value = mock_response

            with pytest.raises(RuntimeError):
                await api_client.get_registry_data(
                    POD_ID, datetime(2025, 1, 1, tzinfo=UTC), datetime.now(UTC)
                )


class TestRegistryDeltas:
    def test_hour_aligned_reading_closes_previous_hour(self):
        # 00:00 local (Bratislava, CET) on 1 Nov = 23:00 UTC on 31 Oct
        bucket = SsdImsDataCoordinator._registry_bucket(
            datetime(2026, 10, 31, 23, tzinfo=UTC)
        )
        assert bucket == datetime(2026, 10, 31, 22, tzinfo=UTC)

    def test_ad_hoc_reading_belongs_to_its_own_hour(self):
        bucket = SsdImsDataCoordinator._registry_bucket(
            datetime(2026, 10, 24, 18, 21, 10, tzinfo=UTC)
        )
        assert bucket == datetime(2026, 10, 24, 18, tzinfo=UTC)

    def test_counters_become_deltas_including_mid_month_reading(self):
        readings = [
            _reading(datetime(2026, 10, 31, 23, tzinfo=UTC), 350.743, 5944.52),
            _reading(datetime(2026, 9, 30, 22, tzinfo=UTC), 329.492, 5725.716),
            _reading(datetime(2026, 10, 24, 18, 21, 10, tzinfo=UTC), 345.081, 5879.8),
        ]
        deltas = SsdImsDataCoordinator._registry_deltas(readings, "consumption_tariff1")
        assert [b for b, _ in deltas] == [
            datetime(2026, 10, 24, 18, tzinfo=UTC),
            datetime(2026, 10, 31, 22, tzinfo=UTC),
        ]
        assert deltas[0][1] == pytest.approx(345.081 - 329.492)
        assert deltas[1][1] == pytest.approx(350.743 - 345.081)

    def test_no_delta_across_meter_replacement(self):
        readings = [
            _reading(datetime(2026, 1, 31, 23, tzinfo=UTC), 100, 1000),
            _reading(datetime(2026, 2, 28, 23, tzinfo=UTC), 5, 50, serial="M2"),
            _reading(datetime(2026, 3, 31, 22, tzinfo=UTC), 15, 150, serial="M2"),
        ]
        deltas = SsdImsDataCoordinator._registry_deltas(readings, "consumption_tariff2")
        assert deltas == [(datetime(2026, 3, 31, 21, tzinfo=UTC), 100)]

    def test_counter_going_backwards_is_skipped(self):
        readings = [
            _reading(datetime(2026, 1, 31, 23, tzinfo=UTC), 100, 1000),
            _reading(datetime(2026, 2, 28, 23, tzinfo=UTC), 90, 1100),
        ]
        assert (
            SsdImsDataCoordinator._registry_deltas(readings, "consumption_tariff1")
            == []
        )

    def test_missing_values_are_ignored(self):
        readings = [
            _reading(datetime(2026, 1, 31, 23, tzinfo=UTC), 100, 1000),
            RegistryReading(
                serial_number="M1", reading_time=datetime(2026, 2, 28, 23, tzinfo=UTC)
            ),
            _reading(datetime(2026, 3, 31, 22, tzinfo=UTC), 130, 1300),
        ]
        deltas = SsdImsDataCoordinator._registry_deltas(readings, "consumption_tariff1")
        assert deltas == [(datetime(2026, 3, 31, 21, tzinfo=UTC), 30)]


def _make_coordinator(api_client, config, data=None):
    coordinator = SsdImsDataCoordinator.__new__(SsdImsDataCoordinator)
    coordinator.hass = MagicMock()
    # HA currency deliberately not EUR: costs must still be in EUR
    coordinator.hass.config.currency = "GBP"
    coordinator.api_client = api_client
    coordinator.config = config
    coordinator.entry = MagicMock()
    coordinator.pods = {POD_ID: MagicMock()}
    coordinator._last_successful_data_date = None
    coordinator._stats_lock = asyncio.Lock()
    coordinator._registry_lock = asyncio.Lock()
    coordinator._last_registry_fetch_date = None
    coordinator.data = data
    return coordinator


async def _run_executor(fn, *args, **kwargs):
    return fn(*args, **kwargs)


SEP = datetime(2026, 8, 31, 22, tzinfo=UTC)  # 1 Sep 00:00 local
OCT = datetime(2026, 9, 30, 22, tzinfo=UTC)  # 1 Oct 00:00 local
NOV = datetime(2026, 10, 31, 23, tzinfo=UTC)  # 1 Nov 00:00 local
READINGS = [_reading(SEP, 10, 100), _reading(OCT, 20, 210), _reading(NOV, 25, 300)]


async def _run_registry_update(coordinator, last_stats=None, today=date(2026, 11, 8)):
    """Run _update_registry with recorder access mocked; return (data, add mock)."""
    last_stats = last_stats or {}

    def fake_last_stats(hass, n, statistic_id, convert, types):
        return last_stats.get(statistic_id, {})

    all_pod_data: dict = {POD_ID: {}}
    with (
        patch(
            "custom_components.ssd_ims.coordinator.get_instance"
        ) as mock_get_instance,
        patch(
            "custom_components.ssd_ims.coordinator.get_last_statistics",
            side_effect=fake_last_stats,
        ),
        patch(
            "custom_components.ssd_ims.coordinator.async_add_external_statistics"
        ) as mock_add_stats,
    ):
        mock_instance = MagicMock()
        mock_instance.async_add_executor_job = AsyncMock(side_effect=_run_executor)
        mock_get_instance.return_value = mock_instance
        await coordinator._update_registry([POD_ID], all_pod_data, today)
    return all_pod_data, mock_add_stats


def _imported(mock_add_stats) -> dict[str, list[dict]]:
    return {
        call.args[1]["statistic_id"]: call.args[2]
        for call in mock_add_stats.call_args_list
    }


class TestRegistryImport:
    async def test_first_import_energy_and_cost(self):
        client = MagicMock()
        client.get_registry_data = AsyncMock(return_value=READINGS)
        coordinator = _make_coordinator(
            client,
            {
                CONF_POD_NAME_MAPPING: {POD_ID: "Home"},
                CONF_PRICE_VT: 0.25,
                CONF_PRICE_NT: 0.1,
            },
        )

        data, mock_add_stats = await _run_registry_update(coordinator)
        imported = _imported(mock_add_stats)

        vt = imported["ssd_ims:home_consumption_vt"]
        assert [s["start"] for s in vt] == [
            datetime(2026, 9, 30, 21, tzinfo=UTC),
            datetime(2026, 10, 31, 22, tzinfo=UTC),
        ]
        assert [s["sum"] for s in vt] == [10, 15]
        assert [s["sum"] for s in imported["ssd_ims:home_consumption_nt"]] == [
            110,
            200,
        ]
        assert [s["sum"] for s in imported["ssd_ims:home_cost_vt"]] == [2.5, 3.75]
        assert [s["sum"] for s in imported["ssd_ims:home_cost_nt"]] == pytest.approx(
            [11.0, 20.0]
        )

        cost_meta = next(
            c.args[1]
            for c in mock_add_stats.call_args_list
            if c.args[1]["statistic_id"] == "ssd_ims:home_cost_vt"
        )
        assert cost_meta["unit_of_measurement"] == "EUR"
        assert cost_meta["unit_class"] is None

        registry = data[POD_ID]["registry"]
        assert registry["consumption_vt"] == 25
        assert registry["consumption_nt"] == 300
        assert registry["max_demand"] == 3.0
        assert registry["serial_number"] == "M1"
        assert coordinator._last_registry_fetch_date == date(2026, 11, 8)

    async def test_no_cost_statistics_without_prices(self):
        client = MagicMock()
        client.get_registry_data = AsyncMock(return_value=READINGS)
        coordinator = _make_coordinator(client, {})

        _, mock_add_stats = await _run_registry_update(coordinator)

        assert set(_imported(mock_add_stats)) == {
            f"ssd_ims:{POD_ID.lower()}_consumption_vt",
            f"ssd_ims:{POD_ID.lower()}_consumption_nt",
        }

    async def test_only_newer_deltas_are_appended_to_existing_sum(self):
        client = MagicMock()
        client.get_registry_data = AsyncMock(return_value=READINGS)
        coordinator = _make_coordinator(
            client, {CONF_POD_NAME_MAPPING: {POD_ID: "Home"}}
        )
        last = {
            "ssd_ims:home_consumption_vt": {
                "ssd_ims:home_consumption_vt": [
                    {
                        "start": datetime(2026, 9, 30, 21, tzinfo=UTC).timestamp(),
                        "sum": 10.0,
                    }
                ]
            }
        }

        _, mock_add_stats = await _run_registry_update(coordinator, last_stats=last)
        vt = _imported(mock_add_stats)["ssd_ims:home_consumption_vt"]

        assert vt == [{"start": datetime(2026, 10, 31, 22, tzinfo=UTC), "sum": 15.0}]

    async def test_nothing_new_imports_nothing(self):
        client = MagicMock()
        client.get_registry_data = AsyncMock(return_value=READINGS)
        coordinator = _make_coordinator(
            client, {CONF_POD_NAME_MAPPING: {POD_ID: "Home"}}
        )
        latest = {"start": datetime(2026, 10, 31, 22, tzinfo=UTC).timestamp(), "sum": 1}
        last = {
            sid: {sid: [latest]}
            for sid in ("ssd_ims:home_consumption_vt", "ssd_ims:home_consumption_nt")
        }

        _, mock_add_stats = await _run_registry_update(coordinator, last_stats=last)

        mock_add_stats.assert_not_called()

    async def test_fetched_once_per_day_and_previous_reading_carried_over(self):
        client = MagicMock()
        client.get_registry_data = AsyncMock(return_value=READINGS)
        previous = {"consumption_vt": 1.0}
        coordinator = _make_coordinator(
            client, {}, data={POD_ID: {"registry": previous}}
        )
        coordinator._last_registry_fetch_date = date(2026, 11, 8)

        data, mock_add_stats = await _run_registry_update(coordinator)

        client.get_registry_data.assert_not_called()
        mock_add_stats.assert_not_called()
        assert data[POD_ID]["registry"] is previous

    async def test_fetch_error_keeps_previous_reading_and_retries(self):
        client = MagicMock()
        client.get_registry_data = AsyncMock(side_effect=RuntimeError("portal down"))
        previous = {"consumption_vt": 1.0}
        coordinator = _make_coordinator(
            client, {}, data={POD_ID: {"registry": previous}}
        )

        data, _ = await _run_registry_update(coordinator)

        assert data[POD_ID]["registry"] is previous
        assert coordinator._last_registry_fetch_date is None

    async def test_update_config_resets_registry_gate(self):
        coordinator = _make_coordinator(MagicMock(), {})
        coordinator.update_interval = None
        coordinator._last_registry_fetch_date = date(2026, 11, 8)

        await coordinator.update_config({CONF_PRICE_VT: 0.3})

        assert coordinator._last_registry_fetch_date is None
