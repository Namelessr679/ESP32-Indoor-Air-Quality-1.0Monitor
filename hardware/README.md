# Hardware launcher

Files are grouped by purpose: `main.py` coordinates the system, `dashboard.py`
shows it, `pipeline/` holds the model and recommendation handoffs, `control/`
sends fan commands, `ESP32/` holds the Arduino sketch, and `models/` holds the
local model. The merged `influxdb_reader.py` lives directly in `hardware/`.

Everything for the live pipeline is under `hardware/`. Start with `launch.bat`
on Windows; it installs dependencies, creates `config.yaml` from the example,
and opens the Streamlit app at http://localhost:8501. Python 3.10+ is required.
On macOS/Linux: install requirements, copy the config example, then `python main.py`
from this folder. InfluxDB and the sensor-to-database collector must already run.

## One-time setup

1. Fill in `config.yaml`: ESP32 address/token and InfluxDB **3 Core** host, token,
   database and measurement. The defaults match the merged reader (`8181`, `co2db`, `scd41`).
2. `hardware/influxdb_reader.py` comes from merged PR #4 and is present here.
   There is no `sensor_reader.py` substitute.
3. The supplied `models/co2_model.joblib` is included. Add its exact runtime
   dependencies from HW-02 to requirements.txt.
4. HW-02 fills in `pipeline/predictor.py` and supplies the history requirements. Enter
   `required_history_minutes`, `required_readings`, and `max_gap_seconds` in config.
   Required span may be zero for a single-reading model; count must be at least 1.
   Query `history_minutes` must exceed required span so the sliding query can hold
   enough history. Set these based on the model, not by guessing.
5. HW-03 fills in `pipeline/recommender.py`. HW-02/HW-03 set their IMPLEMENTED flags True
   only after testing. The merged reader needs no such flag, class or new methods.
6. Open `ESP32/ESP32.ino` in Arduino IDE. Set Wi-Fi credentials as before, set a
   verified free FAN_PIN and driver polarity, and set FAN_API_KEY to match config
   (16+ characters). Add ArduinoJson 7.x alongside the original sensor/LCD libraries.
   Compile and flash. GPIO controls a compatible driver; it does not power a motor.
   FAN_PIN=-1 keeps control disabled until configured. Keep credentials out of Git.
7. Restart the launcher after config changes. Test Check ESP32 and Manual ON/OFF.
   Manual control works before the predictor and history settings are ready.

## How main.py uses the InfluxDB reader

The launcher sets INFLUXDB_HOST, INFLUXDB_TOKEN, INFLUXDB_DATABASE and
INFLUXDB_MEASUREMENT from YAML **before importing** influxdb_reader. These values
are read at module import in the reader. Restart the server after changing configuration;
there is no second credentials file. The reader aliases configured fields to
co2/temp_c/rh in both queries.

Each cycle calls `influxdb_reader.get_historical_readings(minutes=...)` directly.
That function returns a DataFrame and closes its own client. The launcher never
requires SensorReader, get_recent_readings, close or IMPLEMENTED from that module.
It doesn't call get_latest_reading, avoiding a redundant database query.

The reader owns database cleaning. It does not check complete history
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
and `is_stale`. Work on a copy. The supplied `rf_direct_5min (1).joblib` is saved
as `models/co2_model.joblib`. Its pipeline expects 23 features, including
`session_elapsed_minutes`, and records scikit-learn 1.6.1. HW-02 must confirm
the complete training feature names, order, elapsed-time origin and units,
plus any lags, rolling averages and preprocessing. Rename reader columns only
as required by the saved model.
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
control/fan_controller.py and shows recommendation/reason on the dashboard.

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

The merged reader closes the client on a failed connection check and aliases field
overrides. Its latest-reading query checks at most 20 candidates; this launcher
uses its historical query instead. Database calls still need bounded timeouts
before unattended use; a stuck query can delay Stop processing, although it
cannot keep renewing the ESP32 ON lease.

Earlier local tests covered the unmodified reader with a fake database, its integration
with the runner, Streamlit controls, fan HTTP acknowledgements and Stop behavior.
Test files are deliberately omitted from this PR. Firmware compilation, physical
fan tests and Windows launch.bat execution require your board/computer. No fitted
real credentials, Docker setup or HW-02/HW-03 implementation is included.
