# Changelog

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
