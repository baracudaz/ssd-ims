# Changelog

## Version 2.0.6

- **Bug fix**: Scan interval set via the options flow now survives a restart; `async_setup_entry` reads `entry.options` first and falls back to `entry.data`
- **Bug fix**: `async_unload_entry` once again clears `entry.runtime_data` after successful platform unload, preventing stale coordinator references on reload
- **Bug fix**: Migration to version 2 no longer silently bumps the config version when POD discovery returns `None`; it now logs an error and returns `False` so the migration is retried on the next startup

## Version 2.0.5

- **Bug fix**: Authentication failures now correctly trigger Home Assistant's re-authentication flow instead of silently failing at startup
- **Bug fix**: Config entry migration no longer re-runs on every restart (version is now properly bumped to 2 after migration)
- **Bug fix**: Platform setup now correctly waits for the first data fetch before registering entities, preventing empty sensor states on initial load
- **Bug fix**: `calculate_yesterday_range` now returns both start and end as UTC-aware datetimes (was returning a naive local datetime for start)
- **Bug fix**: Session expiry detection now catches HTTP 200 responses with an HTML body (portal login-page redirect), not just non-200 responses
- **Internal**: Options flow now stores mutable settings (update interval) in `entry.options` instead of `entry.data`
- **Internal**: Sensor entities now use the standard `CoordinatorEntity` base class and typed `DeviceInfo` object
- **Internal**: Config flow uses the shared Home Assistant aiohttp session instead of creating its own `ClientSession`
- **Internal**: Replaced deprecated `FlowResult` with `ConfigFlowResult`; bumped config flow `VERSION` to 2
- **Internal**: Replaced `raise Exception(...)` with `raise RuntimeError(...)` for specificity
- **Internal**: Modernized all type hints to Python 3.10+ union syntax (`X | None`, `list[X]`, `dict[K, V]`)
- **Internal**: Replaced f-string logging with lazy `%s` format throughout
- **Internal**: Removed unused models (`PodNameMapping`, `QualityType`, `AggregatedData`), constants (`CONF_HISTORY_IMPORT_DONE`), and dead method `_get_pod_id_by_text`
- **Internal**: Added `SensorStateClass.TOTAL_INCREASING` to energy sensors for correct HA statistics integration

## Version 2.0.4

- Refactor release: moved shared utility logic to `helpers.py` and kept `const.py` constants-only
- Runtime/performance improvements: `ConfigEntry.runtime_data`, shared HA aiohttp session, POD cache (TTL)
- Internal cleanup: reduced duplicated logic in API client, coordinator, config flow, and sensors

## Version 2.0.3

- Stability and maintenance updates
- Small fixes and quality improvements

## Version 2.0.2

- Bug fixes for data handling and integration reliability
- Minor internal improvements

## Version 2.0.1

- Runtime cleanup: migrated to `ConfigEntry.runtime_data` and shared HA aiohttp session
- Performance: added POD cache (TTL) and fixed stable→session POD lookup
- Refactor: moved utility methods to `helpers.py` and kept `const.py` constants-only
- Docs: moved changelog out of `README.md` into `CHANGELOG.md`

## Version 2.0.0

- Major update: simplified to 3 sensors per POD and switched to long-term statistics import
- Added Energy dashboard-ready statistics and historical import in setup flow
- Removed legacy multi-period/idle-reactive sensors and improved translations

## Version 1.x

- Initial releases with multiple sensor types and time periods
- Forked from <https://github.com/samsk/HA-SSD-IMS>
