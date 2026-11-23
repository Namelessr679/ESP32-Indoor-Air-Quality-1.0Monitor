# Hardware launcher

Everything for the live pipeline is under `hardware/`. Start with `launch.bat`
on Windows; it installs dependencies, creates `config.yaml` from the example,
and opens the Streamlit app at http://localhost:8501. Python 3.10+ is required.
On macOS/Linux: install requirements, copy the config example, then `python main.py`
from this folder. InfluxDB and the sensor-to-database collector must already run.

## One-time setup

1. Fill in `config.yaml`: ESP32 address/token and InfluxDB **3 Core** host, token,
   database and measurement. The defaults match PR #4 (`8181`, `co2db`, `scd41`).
2. Merge PR #4 or put its unchanged `influxdb_reader.py` directly in this folder.
   This PR does not copy or rewrite the teammate's reader. Until it is present,
   the dashboard lists HW-01 as missing. There is no `sensor_reader.py` substitute.
3. Put the trusted model in `models/co2_model.joblib`. Add the model's exact runtime
   dependencies from HW-02 to requirements.txt.
4. HW-02 fills in `predictor.py` and supplies the history requirements. Enter
   `required_history_minutes`, `required_readings`, and `max_gap_seconds` in config.
   Required span may be zero for a single-reading model; count must be at least 1.
   Query `history_minutes` must exceed required span so the sliding query can hold
   enough history. Set these based on the model, not by guessing.
5. HW-03 fills in `recommender.py`. HW-02/HW-03 set their IMPLEMENTED flags True
   only after testing. PR #4's reader needs no such flag, class or new methods.
6. Open `ESP32/ESP32.ino` in Arduino IDE. Set Wi-Fi credentials as before, set a
   verified free FAN_PIN and driver polarity, and set FAN_API_KEY to match config
   (16+ characters). Add ArduinoJson 7.x alongside the original sensor/LCD libraries.
   Compile and flash. GPIO controls a compatible driver; it does not power a motor.
   FAN_PIN=-1 keeps control disabled until configured. Keep credentials out of Git.
7. Restart the launcher after config changes. Test Check ESP32 and Manual ON/OFF.
   Manual control works before the reader, model and history settings are ready.

## How main.py uses PR #4

The launcher sets INFLUXDB_HOST, INFLUXDB_TOKEN, INFLUXDB_DATABASE and
INFLUXDB_MEASUREMENT from YAML **before importing** influxdb_reader. These values
are read at module import in PR #4. Restart the server after changing configuration;
there is no second credentials file. Use the reader's default co2/temp_c/rh fields
unless its configurable-field alias review issue has been fixed.

Each cycle calls `influxdb_reader.get_historical_readings(minutes=...)` directly.
That function returns a DataFrame and closes its own client. The launcher never
requires SensorReader, get_recent_readings, close or IMPLEMENTED from that module.
It doesn't call get_latest_reading, avoiding a redundant database query.

The reader owns database cleaning. PR #4 currently does not check complete history
coverage, so the launcher checks configured span/count/gaps as well as freshness
before calling HW-02. Empty, stale or incomplete data shows Waiting for data and
requests fan OFF. Historical rows marked is_stale are kept for lag/rolling features;
only the newest timestamp determines current freshness (default 60 seconds).

Only readings from the current live session are passed onward. The session begins
at the first successful Auto startup, stays fixed through Stop/Start and manual
mode, and resets when the server is restarted. This makes elapsed time stable
across moving query windows. Confirm this session definition matches training with
HW-02; an external collection-session origin would require an explicit adjustment.

## HW-02 handoff

Implement `Predictor(model_path)` to load the model/preprocessing once, and:

```python
predict(history, *, session_start)
# returns {"predicted_co2": 1200.0, "horizon_minutes": 5}
```

`history` is the chronological reader DataFrame with `time`, `co2`, `temp_c`, `rh`,
and `is_stale`. Work on a copy. Match the actual saved model: for the discussed
co2/temp/rh/elapsed inputs, rename temp_c to temp and calculate elapsed time from
session_start in the original training units. Use the exact training feature names
and order, plus any lags, rolling averages, scaling or recursive forecasting used.
Don't assume the .joblib contains only a bare estimator. Don't pass is_stale as a
model feature unless trained with it. Convert delta targets to absolute CO2 ppm.
No prediction implementation or invented model output is included in this PR.

## HW-03 handoff

Implement `decide(history, prediction, previous_fan_state)`. Return the three
required fields and an optional minimum run duration in seconds:

```python
{"recommendation": "Turn fan on", "fan_on": True,
 "reason": "Predicted CO₂ exceeds the agreed threshold",
 "minimum_run_seconds": 300}
```

history uses the same reader fields. prediction includes absolute CO2 and its
horizon. previous_fan_state is the last acknowledged command. HW-03 supplies agreed
thresholds/hysteresis and minimum run duration. The example 300 seconds is not
an agreed project threshold. The duration must be a finite nonnegative number;
when omitted, it defaults to zero. The clock starts only after the first ON
acknowledgement. Later ON decisions can extend, but never shorten, the minimum.
An automatic OFF decision waits until it expires; Stop and Manual OFF bypass it.
If data becomes stale, a command fails, or the process disconnects, the system
requests OFF and the ESP32 lease can also shut it down. The minimum is therefore
a normal-operation guarantee, not an override of failure handling. It makes decisions only; main.py sends fan_on through
fan_controller.py and shows recommendation/reason on the dashboard.

## Controls and fan protocol

Start/Auto starts one background loop; repeated Start doesn't create another.
Manual ON overrides Auto; Start resumes Auto. Stop and Manual OFF request OFF.
All browser tabs share one controller. Closing a tab does not stop the system:
press Stop before leaving. Ctrl+C stops the Streamlit server. Normal process exit
attempts OFF; loss of the process relies on the firmware's command lease.

The HTTP client sends JSON POST `/fan` with state `on` or `off`, using X-API-Key.
GET `/fan` checks status. The firmware acknowledges the commanded state, not actual
rotation. Manual ON renews every five seconds; Auto renews per successful cycle.
The existing ESP32 code is moved into its Arduino sketch folder without further
firmware changes in this revision. Compared with the original sensor sketch it
has only the previously added fan handler/setup/lease code (58 added lines).
The original Wi-Fi reconnect logic remains, with OFF before reconnect attempts.
The 30-second lease is checked in loop(); blocking operations can delay checks.

## Limits and verification

PR #4's separate review fixes remain its owner's work (connection-check cleanup,
field aliasing, newest-valid-row selection). The launcher cannot repair them.
Its database calls also need bounded timeouts before unattended use; a stuck query
can delay Stop processing, although it cannot keep renewing the ESP32 ON lease.

Local tests cover the unmodified PR #4 reader with a fake database, its integration
with the runner, Streamlit controls, fan HTTP acknowledgements and Stop behavior.
Test files are deliberately omitted from this PR. Firmware compilation, physical
fan tests and Windows launch.bat execution require your board/computer. No fitted
model, real credentials, Docker setup or HW-02/HW-03 implementation is included.
