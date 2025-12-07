# SSD IMS Home Assistant Integration

A custom Home Assistant integration for gathering energy consumption and supply data from the Stredoslovenská distribučná SSD IMS portal (ims.ssd.sk) with automatic import into Home Assistant's long-term statistics for use in the Energy dashboard.

## Features

- **Energy Statistics Import**: Automatically imports historical and daily energy data into Home Assistant's statistics database
- **Energy Dashboard Ready**: Data is formatted for direct use in Home Assistant's Energy dashboard
- **Multiple POD Support**: Monitor multiple Points of Delivery simultaneously
- **Custom POD Names**: Set friendly names for your Points of Delivery (e.g., home address, apartment name)
- **Historical Data Import**: Import past energy data during initial setup (configurable, up to 365 days)
- **Automatic Updates**: Configurable update interval (6, 12, or 24 hours recommended)
- **Robust Error Handling**: Comprehensive error handling with automatic re-authentication

## Data Characteristics

**Data Freshness**: The SSD IMS portal provides day-old data that is published after midnight:

- Data for the current day is not available
- The most recent data available is from yesterday
- Data is updated once daily after midnight

**Data Resolution**: All metering data has 15-minute resolution from the source, aggregated to hourly statistics for Home Assistant.

## Sensors Created

The integration creates **3 sensors per Point of Delivery**:

| Sensor | Description |
|--------|-------------|
| `sensor.<pod_name>_actual_consumption_yesterday` | Yesterday's total energy consumption (kWh) |
| `sensor.<pod_name>_actual_supply_yesterday` | Yesterday's total energy supply/production (kWh) |
| `sensor.<pod_name>_last_update` | Timestamp of last data update |

## Long-Term Statistics

The integration imports energy data into Home Assistant's statistics database with hourly granularity:

| Statistic ID | Description |
|--------------|-------------|
| `ssd_ims:<pod_name>_actual_consumption` | Cumulative energy consumption (kWh) |
| `ssd_ims:<pod_name>_actual_supply` | Cumulative energy supply/production (kWh) |

These statistics can be used directly in the Energy dashboard configuration.

## Installation

### Method 1: HACS (Recommended)

1. Open HACS in Home Assistant
2. Click on "Integrations"
3. Click the "+" button
4. Search for "SSD IMS"
5. Click "Install"
6. Restart Home Assistant

### Method 2: Manual Installation

1. Download this repository
2. Copy the `custom_components/ssd_ims` folder to your Home Assistant `config/custom_components/` directory
3. Restart Home Assistant
4. Add the integration via the UI

## Configuration

### Setup Flow

1. Go to **Settings** → **Devices & Services**
2. Click **Add Integration**
3. Search for "SSD IMS"
4. **Step 1 - Credentials**: Enter your SSD IMS portal credentials (<https://ims.ssd.sk>)
5. **Step 2 - POD Selection**: Select which Points of Delivery to monitor
6. **Step 3 - POD Names**: Set friendly names for your PODs (optional, e.g., your home address)
7. **Step 4 - Data Import & Refresh**: Configure update interval and historical data import

### Configuration Options

| Option | Default | Description |
|--------|---------|-------------|
| Update Interval | 6 hours | How often to check for new data (6h, 12h, or 24h recommended) |
| Enable History Import | Yes | Import historical energy data on first setup |
| Days to Import | 7 | Number of days of historical data to import (1-365) |

### Options Flow

After setup, you can change the update interval via **Settings** → **Devices & Services** → **SSD IMS** → **Configure**.

## Energy Dashboard Setup

To add SSD IMS data to your Energy dashboard:

1. Go to **Settings** → **Dashboards** → **Energy**
2. Click **Add Consumption** under "Electricity grid"
3. Select "Use an external statistic"
4. Search for `ssd_ims:<pod_name>_actual_consumption`
5. (Optional) Add supply data similarly for solar production tracking

## Development

### Prerequisites

- Python 3.11+
- Docker and Docker Compose
- Home Assistant 2024.1+

### Setup Development Environment

```bash
# Clone the repository
git clone <repository-url>
cd ha-ssd-ims

# Start Home Assistant container
make docker-up

# View logs
make docker-logs
```

### Running Tests

```bash
# Run all tests
make test

# Run with coverage
make test-coverage
```

### Project Structure

```shell
ha-ssd-ims/
├── custom_components/ssd_ims/
│   ├── __init__.py           # Main integration setup
│   ├── api_client.py         # SSD IMS API client
│   ├── config_flow.py        # Configuration UI flow
│   ├── coordinator.py        # Data update coordinator
│   ├── sensor.py             # Sensor entities
│   ├── models.py             # Data models
│   ├── const.py              # Constants and configuration
│   ├── manifest.json         # Integration manifest
│   └── translations/         # UI translations (EN, SK)
├── tests/                    # Test suite
├── config/                   # Home Assistant dev config
├── docker-compose.yml        # Development environment
└── Makefile                  # Development commands
```

## Troubleshooting

### Common Issues

1. **Authentication Failed**
   - Verify your username and password at <https://ims.ssd.sk>
   - Ensure your account is active

2. **No Data in Energy Dashboard**
   - Wait for the first data update (can take up to 6 hours depending on interval)
   - Check that historical import completed in the logs
   - Verify the statistic IDs are correctly configured in the Energy dashboard

3. **SSL Certificate Error**
   - The SSD IMS portal uses SSL; ensure your Home Assistant can verify certificates
   - Check your system's CA certificates are up to date

### Debug Logging

Enable debug logging for troubleshooting:

```yaml
# configuration.yaml
logger:
  default: info
  logs:
    custom_components.ssd_ims: debug
```

## API Integration

The integration uses the SSD IMS portal API:

| Endpoint | Purpose |
|----------|---------|
| `/api/account/login` | Authentication |
| `/api/consumption-production/profile-data/get-points-of-delivery` | POD discovery |
| `/api/consumption-production/profile-data/chart-data` | Energy data retrieval |

## License

This project is licensed under the AGPLv3 License - see the LICENSE file for details.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes with tests
4. Submit a pull request

## Changelog

### Version 2.0.0

- **Breaking**: Simplified sensor structure - now creates 3 sensors per POD instead of 28
- **New**: Direct import into Home Assistant's long-term statistics database
- **New**: Energy dashboard ready out of the box
- **New**: Historical data import during initial setup
- **New**: Improved 4-step configuration flow
- **Removed**: Multiple time period sensors (replaced by statistics)
- **Removed**: Idle/reactive power sensors
- **Removed**: Supply sensor toggle (always enabled)
- **Improved**: Slovak and English translations

### Version 1.x

- Initial releases with multiple sensor types and time periods
