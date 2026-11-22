"""Single-worker pipeline and Streamlit launcher. HW-01/02/03 remain unimplemented."""
import copy
import math
from pathlib import Path
from queue import Empty, Queue
from threading import Event, Lock, Thread
from datetime import datetime, timezone
import time

from pipeline import WaitingForData, sensor_reader, predictor, recommender
from pipeline.fan_controller import FanController

ROOT = Path(__file__).resolve().parent


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
    return [name for module, name in (
        (sensor_reader, "KCO2-HW-01 — InfluxDB online sensor reader"),
        (predictor, "KCO2-HW-02 — Live features and CO₂ prediction"),
        (recommender, "KCO2-HW-03 — Ventilation recommendation logic"),
    ) if not module.IMPLEMENTED]


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
        self._update(fan="Commanded ON" if on else "Commanded OFF")

    def _off(self):
        try:
            self._set_fan(False)
            return "OFF acknowledged"
        except Exception:
            return "OFF not acknowledged; ESP32 command lease expires within 30 seconds"

    def _cleanup(self):
        reader, self.reader = self.reader, None
        self.model = self.decide = None
        if reader is not None:
            reader.close()

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
            self.reader = sensor_reader.SensorReader(self.config["influxdb"])
            self.model = predictor.Predictor(model_path)
            self.decide = recommender.decide
        self._update(mode="Auto", message="Automatic pipeline started")

    def _tick(self):
        readings = self.reader.get_recent_readings()
        validate_readings(readings, self.config["pipeline"]["max_reading_age_seconds"])
        prediction = self.model.predict(readings)
        if (not finite_number(prediction["predicted_co2"]) or prediction["predicted_co2"] <= 0
                or not finite_number(prediction["horizon_minutes"])
                or prediction["horizon_minutes"] <= 0):
            raise ValueError("Invalid prediction output")
        decision = self.decide(readings, prediction, self.snapshot()["fan"] == "Commanded ON")
        if type(decision["fan_on"]) is not bool or not all(
                isinstance(decision[k], str) for k in ("recommendation", "reason")):
            raise ValueError("Invalid recommendation output")
        # Reject data that became stale during slow feature/model processing.
        validate_readings(readings, self.config["pipeline"]["max_reading_age_seconds"])
        if self.cancel.is_set():
            return
        self._set_fan(decision["fan_on"])
        self._update(reading=readings[-1], prediction=prediction,
                     recommendation=decision["recommendation"], message=decision["reason"])

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
