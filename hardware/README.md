# Hardware launcher

`main.py` launches the Streamlit dashboard and manages automatic and manual ESP32 fan commands. `dashboard.py` refreshes a CO₂ history chart and displays the current reading, forecast, and acknowledged fan state. The `pipeline/` folder contains `influxdb_reader.py`, `fan_controller.py`, `predictor.py`, and `recommender.py`.

On Windows, run `launch.bat`. It installs dependencies, copies `config.example.yaml` to `config.yaml` when needed, and opens the dashboard at http://localhost:8501. Python 3.10+ is required. On macOS or Linux, install `requirements.txt`, copy the example config, then run `python main.py` from this directory.

Set the ESP32 address and token and the InfluxDB connection details in `config.yaml`. The launcher resolves this file relative to `main.py`, so it can start from any working directory. Keep credentials out of Git. The dashboard refreshes the last 30 minutes of CO₂ readings every five seconds; change `influxdb.history_minutes` to choose another window. The model path in `pipeline.model_path` is relative to `hardware/`.

## Fan control

Set the Wi-Fi credentials and `FAN_API_KEY` in your local `ESP32/secrets.h`; the fan key must match `esp32.token` in `config.yaml`. Compile with ArduinoJson 7.x plus the existing sensor and LCD libraries.

For local credentials, put `ssid`, `password`, and `FAN_API_KEY` declarations in `ESP32/secrets.h`. The sketch includes that file when present and otherwise uses placeholders. `secrets.h` and `config.yaml` are ignored by Git; do not put real credentials directly into `ESP32.ino` or commit the header with `git add -f`.

### Wiring (power off before changing wires)

**GPIO 25 was used by LCD D7. Move that LCD wire to GPIO 27 first.** The active firmware now uses LCD pins 4, 5, 18, 19, 23, 27. SCD41 remains on default I2C GPIO 21/22. GPIO 26 and 27 have no other assignments in this firmware.

| Fan pin | ESP32 pin |
| --- | --- |
| GND | GND |
| VCC | 3.3V (the tested fan with built-in driver) |
| INA | GPIO 25 |
| INB | GPIO 26 |

ON sets INA HIGH and INB LOW; OFF sets both LOW. Both outputs initialize LOW before Wi-Fi, LCD or sensor setup. This wiring is for the tested driver-equipped fan. The separate `ESP32_Offline_Logger.ino` still assigns LCD D7 to GPIO 25: do not flash that sketch with the fan attached to GPIO 25.

The HTTP client uses `POST /fan` with JSON state `on` or `off` and the `X-API-Key` header. `GET /fan` reads status. Acknowledgement confirms the commanded state, not physical rotation. Manual ON renews every five seconds. The firmware also has a 30-second command lease.

Auto starts a new live session at the first sensor reading after Auto is selected. It reads history, predicts five-minute CO₂, and requests ON at 1,000 ppm or higher. An acknowledged automatic ON runs for at least 10 minutes during normal operation. Missing or invalid data requests OFF. The manual fan toggle overrides Auto; Stop and Manual OFF request OFF immediately. Check ESP32 reads the device status. All browser tabs share one controller. Press Stop before leaving the dashboard; closing a tab does not stop the system.


## Architecture and failure behavior

The ESP32 reads SCD41, updates its LCD every two seconds, and serves `/json`. Your existing external collector must continue writing these readings to InfluxDB 3 (`co2db`, measurement `scd41`, fields `co2`, `temp_c`, `rh`, and a UTC timestamp). This repository contains the reader, not the collector configuration. Fan control does not change the JSON sensor response or data collection path.

`influxdb_reader.py` validates and orders history; `predictor.py` applies the existing 23 features and trained model to predict CO2 five minutes ahead. `recommender.py` uses current and predicted CO2. The background controller in `main.py` passes its `fan_on` decision to `fan_controller.py`, which uses Python's standard-library HTTP client to call the ESP32's existing web server. No broker or additional service is needed.

Auto requires at least ten minutes of valid readings collected after Auto starts. While history is insufficient, the controller requests OFF. Under the current decision logic, the higher of current and predicted CO2 triggers ON at 1,000 ppm; below that it requests OFF after the existing ten-minute minimum run. Thresholds, model and feature engineering are unchanged by the physical fan integration.

Requests have a two-second socket timeout by default (configurable up to five seconds) and run in the existing background worker. Every successful POST renews the firmware's 30-second lease; GET, malformed commands and unauthorized requests do not renew it. Missing/stale sensor data or backend errors request OFF, overriding the minimum run. A failed acknowledgement makes the backend state Unknown and causes an OFF attempt. If the backend stops, stalls or cannot reach the device, the firmware turns OFF when the lease expires; Wi-Fi loss turns it OFF on the next loop. Reconnecting alone does not turn it ON. An Error mode requires selecting Auto or Manual ON again.

Fan control and Wi-Fi retries use `millis()` without delay loops. The existing 500 ms sensor initialization wait remains at startup, while the fan is OFF; no fan timing delays are added. Serial logs show startup OFF and each physical output change with its cause. Backend console logs show acknowledged state transitions and failed commands without printing credentials. Status reports commanded GPIO state, not measured motor rotation.

## Test with the physical device

1. Move LCD D7 to GPIO 27 and connect the fan as above. Configure and upload `ESP32/ESP32.ino`. Open Serial Monitor at 115200 baud. Confirm startup OFF, a working LCD, sensor readings, and the logged Wi-Fi IP. If mDNS fails, use that IP in `esp32.url`.
2. Start the existing InfluxDB collector. Verify `/json` remains readable and new InfluxDB rows arrive at the normal interval (no more than 30 seconds apart for the prediction windows). Set both ESP32 and InfluxDB settings in `hardware/config.yaml`, then run `hardware/launch.bat` or `python hardware/main.py` with dependencies installed.
3. Select Check ESP32, then Manual ON and Manual OFF. Confirm fan rotation/stopping, serial state-change logs, and matching dashboard acknowledgements while LCD updates and InfluxDB collection continue.
4. Select Auto and collect at least ten minutes of new valid history. Observe the displayed five-minute prediction and recommendation. When current or predicted CO2 reaches 1,000 ppm, confirm automatic ON. When both fall below 1,000 ppm and the ten-minute minimum run has elapsed, confirm OFF. Use normally occurring room conditions; do not alter model thresholds for this test. Stop/Manual OFF should stop the fan immediately, including during the minimum run.
5. With Manual ON active, terminate the backend process completely (closing a browser tab does not stop it). Confirm OFF about 30 seconds after the last successful POST and a `command lease expired` serial log. Restart the backend, turn ON, then disconnect Wi-Fi: confirm OFF while sensor/LCD updates continue. Restore Wi-Fi and verify `/json` recovers.
6. In Auto, stop the collector until the latest reading is older than 60 seconds, or make InfluxDB unavailable. Confirm an OFF request despite the minimum run; restore collection and verify recovery (reselect Auto if mode is Error).
7. With the backend stopped, use the PowerShell commands below to test the HTTP endpoint independently. ON expires after 30 seconds unless renewed. Wrong keys must return 401 and an invalid state must return 400 without changing output or extending the lease.

```powershell
$deviceUrl = 'http://esp32.local' # or the logged IP
$fanHeaders = @{ 'X-API-Key' = 'YOUR_MATCHING_16_PLUS_CHARACTER_TOKEN' }
Invoke-RestMethod "$deviceUrl/fan" -Method Post -Headers $fanHeaders -ContentType 'application/json' -Body '{"state":"on"}'
Invoke-RestMethod "$deviceUrl/fan" -Headers $fanHeaders
Invoke-RestMethod "$deviceUrl/fan" -Method Post -Headers $fanHeaders -ContentType 'application/json' -Body '{"state":"off"}'
```

Backend regression checks (no hardware needed): install `hardware/requirements.txt` in a Python 3.12 environment, then run `python -m unittest discover -s hardware/tests -v` from the repository root. The trained artifact requires the pinned scikit-learn 1.6.1; the existing Python 3.14 environment could not install that version during testing.

For the isolated test environment created in this checkout:

```powershell
hardware/.venv-test/Scripts/python.exe -m unittest discover -s hardware/tests -v
```

Tests exercise real recommendation thresholds, feature calculations, validation, model loading and a synthetic-data model smoke test; mocked database queries and connection cleanup; controller timing, mode changes, cancellation and shutdown; local HTTP success/failure responses; and Streamlit UI callbacks. The integration test uses the real reader, predictor, model, recommender and controller with mocked database and fan IO. Synthetic predictions test execution and output validity, not predictive accuracy. Tests never read deployment credentials or command the physical device.

Firmware compilation is a separate check. Python mocks do not execute the ESP32 firmware or verify its lease timing, GPIO signals, Wi-Fi reconnect behavior or sensor/LCD timing. Follow the physical tests above for these checks.

If Serial Monitor reports `wifi:sta is connecting, return error`, upload the latest `ESP32/ESP32.ino`; older copies used `WiFi.reconnect()` while an attempt was still running. The current sketch gives each attempt 20 seconds, then disconnects and restarts it after a one-second pause without blocking the sensor loop. If it remains disconnected, check the configured SSID/password and that the ESP32 can use the hotspot's 2.4 GHz network.

If InfluxDB rows repeat unchanged sensor values, compare `/json` twice about 10 seconds apart. Its `sensor_age_ms` should repeatedly return to near zero when the SCD41 supplies new measurements; `time_ms` alone only proves the ESP32 is running. The sketch now checks sensor readiness once per second, logs new measurements or errors in Serial Monitor, and returns HTTP 503 from `/json` if no fresh measurement has arrived for 15 seconds. The collector should skip 503 responses instead of writing stale values with new timestamps. If `sensor_age_ms` stays low but CO2 remains implausible, check sensor wiring and the collector's mapping of `co2`, `temp_c`, and `rh`.
