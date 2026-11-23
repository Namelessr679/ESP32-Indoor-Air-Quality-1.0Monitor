"""Single-worker pipeline and Streamlit launcher. Uses the merged InfluxDB reader."""
import atexit
import copy
import math
import importlib
import os
from pathlib import Path
from queue import Empty, Queue
from threading import Event, Lock, Thread
from datetime import datetime, timezone
import time

from pipeline import predictor, recommender
from control.fan_controller import FanController

ROOT = Path(__file__).resolve().parent


class WaitingForData(Exception):
    """The reader has not returned enough fresh history for prediction yet."""


def load_reader(config):
    """Set the reader's environment before its first import."""
    for key, env in (("host", "INFLUXDB_HOST"), ("token", "INFLUXDB_TOKEN"),
                     ("database", "INFLUXDB_DATABASE"), ("measurement", "INFLUXDB_MEASUREMENT")):
        value = config.get(key)
        if not isinstance(value, str) or not value or value.startswith("YOUR_"):
            raise ValueError(f"Set influxdb.{key} in config.yaml")
        os.environ[env] = value
    return importlib.import_module("influxdb_reader")


def history_settings(config):
    """HW-02 owner specifies history requirements; don't guess model requirements."""
    lookback = config["history_minutes"]
    span = config.get("required_history_minutes")
    count = config.get("required_readings")
    gap = config.get("max_gap_seconds")
    if type(lookback) is not int or lookback <= 0:
        raise ValueError("history_minutes must be a positive integer")
    if not finite_number(span) or not 0 <= span < lookback:
        raise ValueError("Set required_history_minutes from HW-02 (less than history_minutes)")
    if type(count) is not int or count < 1:
        raise ValueError("Set required_readings from HW-02 (positive integer)")
    if not finite_number(gap) or gap <= 0:
        raise ValueError("Set max_gap_seconds from HW-02 (positive number)")
    return lookback, span, count, gap


def prepare_readings(history, config):
    """Adapt the reader's DataFrame for dashboard/validation; keep raw table for HW-02/03."""
    if history.empty:
        raise WaitingForData("No readings available")
    rows = [{"timestamp": row.time.isoformat(), "co2": float(row.co2),
             "temperature": float(row.temp_c), "humidity": float(row.rh)}
            for row in history.itertuples(index=False)]
    validate_readings(rows, config["max_reading_age_seconds"])
    _, span, count, gap = history_settings(config)
    times = [datetime.fromisoformat(row["timestamp"]) for row in rows]
    if len(rows) < count or (times[-1] - times[0]).total_seconds() < span * 60:
        raise WaitingForData("Collecting the history required by HW-02")
    if any((b - a).total_seconds() > gap for a, b in zip(times, times[1:])):
        raise WaitingForData("Waiting for history without large gaps")
    # Old rows are required for lag/rolling features; do not filter all is_stale rows.
    return rows


def load_config(path=ROOT / "config.yaml"):
    import yaml
    if not path.exists():
        raise ValueError("Copy config.example.yaml to config.yaml and fill in your settings")
    config = yaml.safe_load(path.read_text())
    if not isinstance(config, dict):
        raise ValueError("Configuration must be a YAML mapping")
    for section in ("esp32", "pipeline", "influxdb"):
        if not isinstance(config.get(section), dict):
            raise ValueError(f"Missing configuration section: {section}")
    p = config["pipeline"]
    interval = float(p["interval_seconds"])
    age = float(p["max_reading_age_seconds"])
    if not math.isfinite(interval) or not 1 <= interval <= 10:
        raise ValueError("Pipeline interval must be 1–10 seconds (fan lease is 30 seconds)")
    if not math.isfinite(age) or age <= 0:
        raise ValueError("Maximum reading age must be positive")
    p["interval_seconds"], p["max_reading_age_seconds"] = interval, age
    p["model_path"] = str((path.parent / p["model_path"]).resolve())
    return config


def pending_tickets():
    pending = []
    for module, name in ((predictor, "KCO2-HW-02 — Live features and CO₂ prediction"),
                         (recommender, "KCO2-HW-03 — Ventilation recommendation logic")):
        if not module.IMPLEMENTED:
            pending.append(name)
    return pending


def finite_number(value):
    return type(value) in (int, float) and math.isfinite(value)


def validate_readings(readings, max_age):
    if not readings:
        raise WaitingForData("No readings available")
    previous = None
    now = datetime.now(timezone.utc)
    for row in readings:
        stamp = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise ValueError("Reading timestamps must include a timezone")
        if previous is not None and stamp <= previous:
            raise ValueError("Readings must have unique, increasing timestamps")
        previous = stamp
        for key in ("co2", "temperature", "humidity"):
            if not finite_number(row[key]):
                raise ValueError(f"Invalid reading field: {key}")
        if row["co2"] <= 0 or not 0 <= row["humidity"] <= 100:
            raise ValueError("Invalid CO₂ or humidity")
    age = (now - previous).total_seconds()
    if age < -5:
        raise ValueError("Latest reading timestamp is in the future")
    if age > max_age:
        raise WaitingForData("Latest reading is stale; waiting for fresh data")


class Runner:
    """One serialized worker owns pipeline and fan IO; UI never performs IO."""
    def __init__(self, config, fan=None, components=None):
        self.config = config
        self.fan = fan or FanController(**config["esp32"])
        self.components = components  # Dependency injection for integration tests.
        self.reader = self.model = self.decide = None
        self.session_start = None
        self.fan_on_since = None  # monotonic clock, set only after ON is acknowledged
        self.minimum_fan_until = None
        self.commands = Queue()
        self.cancel = Event()
        self.lock = Lock()
        self.state = {"mode": "Stopped", "message": "Ready", "fan": "Unknown",
                      "reading": None, "prediction": None, "recommendation": None}
        self.worker = Thread(target=self._run, daemon=True)
        self.worker.start()

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(self.state)

    def _update(self, **values):
        with self.lock:
            self.state.update(values)

    def command(self, name):
        if name not in ("start", "stop", "on", "off", "check", "close"):
            raise ValueError("Unknown command")
        if name in ("stop", "off", "close"):
            self.cancel.set()  # Suppress an in-flight automatic ON result.
        self.commands.put(name)

    def _set_fan(self, on):
        try:
            self.fan.set_state(on)
        except Exception:
            self._update(fan="Unknown")
            raise
        now = time.monotonic()
        if on:
            if self.fan_on_since is None:
                self.fan_on_since = now
        else:
            self.fan_on_since = None
            self.minimum_fan_until = None
        self._update(fan="Commanded ON" if on else "Commanded OFF")

    def _off(self):
        try:
            self._set_fan(False)
            return "OFF acknowledged"
        except Exception:
            return "OFF not acknowledged; ESP32 will request OFF when its 30-second lease is checked"

    def _cleanup(self):
        # The reader closes its client inside each function; there is no reader.close().
        self.reader = self.model = self.decide = None

    def _start(self):
        if self.snapshot()["mode"] == "Auto":
            return
        missing = pending_tickets() if self.components is None else []
        if missing:
            raise RuntimeError("Waiting for: " + "; ".join(missing))
        self._cleanup()
        self._set_fan(False)
        if self.components:
            self.reader, self.model, self.decide = self.components()
        else:
            model_path = self.config["pipeline"]["model_path"]
            if not Path(model_path).is_file():
                raise ValueError("Model file missing; supply the HW-02 artifact")
            history_settings(self.config["pipeline"])
            self.reader = load_reader(self.config["influxdb"])
            self.model = predictor.Predictor(model_path)
            self.decide = recommender.decide
        if self.session_start is None:
            self.session_start = datetime.now(timezone.utc)
        self._update(mode="Auto", message="Automatic pipeline started")

    def _tick(self):
        history = self.reader.get_historical_readings(
            minutes=self.config["pipeline"]["history_minutes"])
        # One live session starts at the first Auto start and survives Stop/Start.
        # Exclude older records so elapsed time relative to that start isn't negative.
        history = history.loc[history["time"] >= self.session_start].copy()
        readings = prepare_readings(history, self.config["pipeline"])
        prediction = self.model.predict(history, session_start=self.session_start)
        if (not finite_number(prediction["predicted_co2"]) or prediction["predicted_co2"] <= 0
                or not finite_number(prediction["horizon_minutes"])
                or prediction["horizon_minutes"] <= 0):
            raise ValueError("Invalid prediction output")
        decision = self.decide(history, prediction, self.snapshot()["fan"] == "Commanded ON")
        if type(decision["fan_on"]) is not bool or not all(
                isinstance(decision[k], str) for k in ("recommendation", "reason")):
            raise ValueError("Invalid recommendation output")
        minimum = decision.get("minimum_run_seconds", 0)
        if not finite_number(minimum) or minimum < 0:
            raise ValueError("minimum_run_seconds must be a finite nonnegative number")
        # Reject data that became stale during slow feature/model processing.
        validate_readings(readings, self.config["pipeline"]["max_reading_age_seconds"])
        if self.cancel.is_set():
            return
        now = time.monotonic()
        # Once ON is acknowledged, a later recommendation cannot shorten its run.
        # Renew ON each cycle so the ESP32's command lease does not expire.
        keep_running = (self.fan_on_since is not None and
                        self.minimum_fan_until is not None and
                        now < self.minimum_fan_until)
        desired_on = decision["fan_on"] or keep_running
        self._set_fan(desired_on)
        if decision["fan_on"] and minimum > 0:
            self.minimum_fan_until = max(
                self.minimum_fan_until or 0, self.fan_on_since + minimum)
        message = decision["reason"]
        if keep_running and not decision["fan_on"]:
            message += " (finishing minimum fan run)"
        self._update(reading=readings[-1], prediction=prediction,
                     recommendation=decision["recommendation"], message=message)

    def _run(self):
        next_tick = time.monotonic()
        while True:
            try:
                command = self.commands.get(timeout=0.1)
            except Empty:
                command = None
            try:
                if command == "close":
                    self._update(mode="Stopped", message=self._off())
                    self._cleanup()
                    return
                if command in ("stop", "off"):
                    self._update(mode="Stopped", message=self._off())
                    self._cleanup()
                elif command == "on":
                    self._update(mode="Manual", message="Manual ON; refreshed every 5 seconds")
                    self._cleanup()
                    self._set_fan(True)
                    next_tick = time.monotonic() + 5
                elif command == "start":
                    self._start()
                    next_tick = time.monotonic()
                elif command == "check":
                    result = self.fan.status()
                    self._update(message="ESP32 connected", fan="Commanded " + result["state"].upper())
                # Only clear cancellation after all queued requests are processed.
                if self.commands.empty():
                    self.cancel.clear()
                if time.monotonic() >= next_tick and not self.cancel.is_set():
                    mode = self.snapshot()["mode"]
                    next_tick = time.monotonic() + self.config["pipeline"]["interval_seconds"]
                    if mode == "Auto":
                        self._tick()
                    elif mode == "Manual":
                        self._set_fan(True)
                        next_tick = time.monotonic() + 5
            except WaitingForData as exc:
                self._update(message=f"{exc}. {self._off()}", prediction=None, recommendation=None)
            except Exception as exc:
                self._update(mode="Error", message=f"{exc}. {self._off()}")
                try:
                    self._cleanup()
                except Exception:
                    pass


class DashboardRuntime:
    def __init__(self):
        self._lock = Lock()
        self._runner = None

    def command(self, name):
        with self._lock:
            if self._runner is None:
                self._runner = Runner(load_config())
            self._runner.command(name)

    def snapshot(self):
        with self._lock:
            if self._runner is None:
                return {"mode": "Stopped", "message": "Configure config.yaml, then check ESP32.",
                        "fan": "Unknown", "reading": None, "prediction": None,
                        "recommendation": None}
            return self._runner.snapshot()

    def shutdown(self):
        with self._lock:
            runner = self._runner
            if runner is not None:
                runner.command("close")
        if runner is not None:
            runner.worker.join(timeout=6)


# Module lifetime survives Streamlit script reruns and new browser sessions.
# Do not put this in session_state: all tabs control the same physical fan.
runtime = DashboardRuntime()
atexit.register(runtime.shutdown)


def main():
    import os
    import sys
    os.execv(sys.executable, [sys.executable, "-m", "streamlit", "run",
                             str(ROOT / "dashboard.py"),
                             "--server.address=127.0.0.1", "--server.port=8501",
                             "--server.fileWatcherType=none",
                             "--browser.gatherUsageStats=false"])


if __name__ == "__main__":
    main()
