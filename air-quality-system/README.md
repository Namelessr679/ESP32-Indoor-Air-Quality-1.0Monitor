# Shared air-quality launcher

Streamlit browser dashboard, launcher and ESP32 fan integration. The three HW tickets are intentionally
**not implemented**. No fitted model or invented prediction/recommendation is
included. Existing root firmware and research notebooks are unchanged.

## Ticket handoff

| Ticket | File | Interface to implement |
| --- | --- | --- |
| KCO2-HW-01 — InfluxDB online sensor reader | `pipeline/sensor_reader.py` | `SensorReader(config)`, `get_recent_readings()`, `close()` |
| KCO2-HW-02 — Live features and CO₂ prediction | `pipeline/predictor.py` | `Predictor(model_path)`, `predict(readings)` |
| KCO2-HW-03 — Ventilation recommendation logic | `pipeline/recommender.py` | `decide(readings, prediction, previous_fan_state)` |

Each module has `IMPLEMENTED = False`. The owner replaces its placeholders, tests
it, and sets the flag to True. Start lists all unfinished tickets before attempting
to construct them. The stubs document required fields/units. The reader returns
unique, ascending timezone-aware timestamps. The reader raises `pipeline.sensor_reader.WaitingForData` when
there is insufficient history. The runner requests OFF and retries next cycle.
Other errors stop automatic mode and request OFF. Configure finite database timeouts;
slow or stuck HW calls cannot be forcibly interrupted by Python threads.

Supply your trusted trained model locally in `models/co2_model.joblib` (or change
its configured path). HW-02 must confirm the actual artifact schema, preprocessing,
sampling cadence, history length, horizon and exact dependency versions. Add those
dependencies to requirements.txt. There is no model retraining in this launcher.

## Why these files exist

`main.py` contains both the pipeline runner and the shared dashboard controller.
The controller lazily creates one runner, serializes creation across browser tabs,
provides snapshots, and requests shutdown on normal process exit. It is an internal
Python object, not an HTTP API. Keeping it in an imported module preserves it across
Streamlit dashboard reruns without creating one runner per tab.

`pipeline/` uses Python's namespace-package support and needs no `__init__.py`.
The InfluxDB reader owns history-readiness checks. Its placeholder module defines
`WaitingForData` so the launcher can handle that signal without a separate file.
The reader implementation remains the HW-01 owner's responsibility.

The tracked [`models/`](models/README.md) folder is ready for your local
`co2_model.joblib`. The default config already points to that exact location.

## Initial computer setup

1. Install Python 3.10+ with the Windows Python launcher (`py`).
2. Double-click `launch.bat`. First run creates a virtual environment, installs
   requirements, copies the example config, and starts Streamlit. Subsequent launches
   also check dependencies so existing installations receive the dashboard upgrade.
   Open http://localhost:8501 if the browser does not open automatically.
3. Edit `config.yaml`: ESP32 URL and command token, InfluxDB settings, model location.
   Use a command token at least 16 characters long matching `secrets.h`.
4. Close/reopen the app after changing configuration. It loads configuration on
   the first control action, and reloads it on a new app session.

For macOS/Linux, create a venv, install requirements, copy config.example.yaml to
config.yaml, and run `python main.py` inside this directory. The launcher binds
Streamlit to 127.0.0.1:8501 and disables file watching to prevent hot-reload workers.
For direct use: `python -m streamlit run dashboard.py --server.address=127.0.0.1
--server.port=8501 --server.fileWatcherType=none` (on one line).

The launcher does not install/start InfluxDB or the existing sensor-to-database
collector. Keep those services running using your existing setup. HW-01 reads the
database; it does not establish the upstream ingestion service. The computer and
ESP32 must be reachable on the same network (some campus Wi-Fi isolates devices).

## ESP32 setup (once)

The new `firmware/esp32_controller/esp32_controller.ino` extends the repository's
online sensor sketch, retaining the LCD, SCD41 and `/json` interface. Flash this
combined sketch to the existing ESP32; do not run a separate fan-only sketch.

1. Copy `secrets.example.h` to `secrets.h` beside the sketch.
2. Set Wi-Fi credentials and the matching command token (16+ characters).
3. Set `FAN_PIN` to a confirmed free output GPIO for your exact board, and set
   `FAN_ACTIVE_HIGH` to the driver's actual polarity. No fan pin is guessed; the
   sketch deliberately fails compilation until you supply one. Existing LCD pins:
   4, 5, 18, 19, 23, 25. SCD41 I2C pins: 21 and 22.
4. Connect the GPIO to a compatible 3.3V-control fan driver. Power the fan with its
   rated supply through that driver, and share ground where the driver requires it.
   Do not power a motor from GPIO. Exact wiring depends on your fan/driver and must
   be confirmed before connecting; provide a hardware pull resistor for OFF during
   reset as appropriate to the driver polarity.
5. Install the existing Sensirion SCD4x and LiquidCrystal libraries plus
   **ArduinoJson 7.x**, select the correct ESP32 board, then compile/upload.
6. Use Check ESP32 and Manual ON/OFF to bench-test command control and sensor output.

The new sketch drives OFF at boot and on Wi-Fi loss. ON commands expire after
30 seconds without renewal. Manual ON renews every 5 seconds; Auto renews on each
successful cycle. Reconnection is nonblocking so it does not deliberately stall
the watchdog. Acknowledgement describes the GPIO command, not measured rotation.
Firmware must still be compiled with your board/libraries and tested on hardware;
this environment cannot verify physical wiring, timing or fan motion.

## Command protocol

Local-network HTTP; no TLS. Keep the device on a trusted network, not exposed to
the internet. Both endpoints require `X-API-Key` matching FAN_API_KEY.

- `GET /fan` -> `{"state":"off","lease_ms":30000}`
- `POST /fan`, JSON `{"state":"on"}` or `{"state":"off"}`
- Success -> `{"command_applied":true,"state":"on"}` (or `off`).
- Invalid body/state -> HTTP 400; wrong/missing token -> HTTP 401.

Repeated state commands are idempotent and renew the lease. The Python client uses
bounded requests, refuses redirects, bypasses HTTP proxies for local traffic and
checks the acknowledgement. Status polling does not renew ON. Sensor `/json` is
unchanged and remains unauthenticated as in the original sketch.

## Daily operation

Power the prewired ESP32/fan, ensure storage/collector are running, double-click
launch.bat, then press Start / Auto. Until the three tickets are connected, Auto
reports the missing modules; manual controls remain usable. Start is idempotent
and one worker serializes all IO. Manual ON overrides Auto; Start returns to Auto.
Stop/Manual OFF request OFF. If OFF cannot be acknowledged, the UI reports
unknown output and the firmware lease handles loss of commands. Closing a browser tab does **not** stop the background pipeline. Press Stop before
leaving. All browser tabs share one thread-safe controller and worker. Normal
process exit requests OFF and waits up to six seconds; forced termination relies
on the ESP32 lease. Stop the Streamlit server with Ctrl+C in its terminal. A failed/stale pipeline cannot
keep renewing ON. Tune the 1–10 second interval within the fixed 30-second lease;
long-running model calls may cause the fan to time out and must be optimized.

`config.yaml`, secrets.h, venvs and fitted models are ignored by git. The three
modules are intentionally placeholders, so successful automated tests do not mean
live prediction is complete.

## Validation

Install requirements, then run `python -m unittest discover -s tests -v`. Tests use fake HW modules and a local
HTTP server; no commands are sent to a real device. Before use, bench-test boot OFF,
manual commands, sensor endpoint continuity, Wi-Fi loss, lease expiry, automatic
integration, stale readings, repeated Start, Stop and restart with the real hardware.
