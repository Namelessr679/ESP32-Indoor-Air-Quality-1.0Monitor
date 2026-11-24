# Hardware launcher

`main.py` launches the Streamlit dashboard and manages manual ESP32 fan commands. `dashboard.py` refreshes a CO₂ history chart and displays the current reading and acknowledged fan state. The `pipeline/` folder contains `influxdb_reader.py`, `fan_controller.py`, `predictor.py`, and `recommender.py`.

On Windows, run `launch.bat`. It installs dependencies, copies `config.example.yaml` to `config.yaml` when needed, and opens the dashboard at http://localhost:8501. Python 3.10+ is required. On macOS or Linux, install `requirements.txt`, copy the example config, then run `python main.py` from this directory.

Set the ESP32 address and token and the InfluxDB connection details in `config.yaml`. The launcher resolves this file relative to `main.py`, so it can start from any working directory. Keep credentials out of Git. The dashboard refreshes the last 30 minutes of CO₂ readings every five seconds; change `influxdb.history_minutes` to choose another window.

## Fan control

Set the ESP32 Wi-Fi credentials and a verified fan driver pin in `ESP32/ESP32.ino`. Set `FAN_API_KEY` to match `config.yaml` and compile with ArduinoJson 7.x plus the sensor and LCD libraries. `FAN_PIN=-1` disables fan control. The GPIO drives a compatible driver, not the motor directly.

The HTTP client uses `POST /fan` with JSON state `on` or `off` and the `X-API-Key` header. `GET /fan` reads status. Acknowledgement confirms the commanded state, not physical rotation. Manual ON renews every five seconds. The firmware also has a 30-second command lease.

The manual fan toggle starts renewal when switched ON and requests OFF when switched OFF. Stop also requests OFF. Check ESP32 reads the device status. All browser tabs share one controller. Press Stop before leaving the dashboard; closing a tab does not stop the system.
