"""Streamlit launcher and shared manual fan controller."""

import atexit
import importlib
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from queue import Empty, Queue
from threading import Event, Lock, Thread

from pipeline.fan_controller import FanController


ROOT = Path(__file__).resolve().parent


def load_config(path=ROOT / "config.yaml"):
    import yaml

    path = Path(path)
    if not path.exists():
        raise ValueError("Copy config.example.yaml to config.yaml and fill in your settings")
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or not isinstance(config.get("esp32"), dict):
        raise ValueError("Missing esp32 configuration")
    return config


def load_reader(config):
    for key, env in (("host", "INFLUXDB_HOST"), ("token", "INFLUXDB_TOKEN"),
                     ("database", "INFLUXDB_DATABASE"), ("measurement", "INFLUXDB_MEASUREMENT")):
        value = config.get(key)
        if not value or value.startswith("YOUR_"):
            raise ValueError(f"Set influxdb.{key} in config.yaml")
        os.environ[env] = value
    return importlib.import_module("pipeline.influxdb_reader")


def read_history():
    config = load_config()["influxdb"]
    reader = load_reader(config)
    return reader.get_historical_readings(minutes=config.get("history_minutes", 30))


class Controller:
    def __init__(self):
        self.fan = None
        self.reader = None
        self.predictor = None
        self.auto_start = None
        self.session_start = None
        self.minimum_until = None
        self.commands = Queue()
        self.cancel = Event()
        self.lock = Lock()
        self.state = {"mode": "Stopped", "message": "Configure config.yaml, then check ESP32.",
                      "fan": "Unknown", "prediction": None, "recommendation": None}
        self.worker = None

    def snapshot(self):
        with self.lock:
            return self.state.copy()

    def _update(self, **values):
        with self.lock:
            self.state.update(values)

    def command(self, name):
        if name not in ("auto", "stop", "on", "off", "check", "close"):
            raise ValueError("Unknown command")
        with self.lock:
            if self.worker is None:
                if name == "close":
                    return
                self.fan = FanController(**load_config()["esp32"])
                self.worker = Thread(target=self._run, daemon=True)
                self.worker.start()
            if name in ("stop", "off", "close"):
                self.cancel.set()
            self.commands.put(name)

    def shutdown(self):
        self.command("close")
        if self.worker is not None:
            self.worker.join(timeout=6)

    def _set_fan(self, on):
        try:
            self.fan.set_state(on)
        except Exception:
            self._update(fan="Unknown")
            raise
        self._update(fan="Commanded ON" if on else "Commanded OFF")

    def _off(self):
        self.minimum_until = None
        try:
            self._set_fan(False)
            return "OFF acknowledged"
        except Exception:
            return "OFF not acknowledged; ESP32 will request OFF when its 30-second lease is checked"

    def _start_auto(self):
        from pipeline.predictor import Predictor

        config = load_config()
        model_path = ROOT / config.get("pipeline", {}).get("model_path", "models/co2_model.joblib")
        if not model_path.is_file():
            raise FileNotFoundError(f"Model file not found: {model_path}")
        self.reader = load_reader(config["influxdb"])
        self.predictor = Predictor(model_path)
        self.auto_start = datetime.now(timezone.utc)
        self.session_start = None
        self._update(mode="Auto", message="Collecting sensor history", prediction=None,
                     recommendation=None)

    def _tick_auto(self):
        config = load_config()["influxdb"]
        try:
            history = self.reader.get_historical_readings(minutes=config.get("history_minutes", 30))
        except Exception as exc:
            self._update(message=f"Sensor read failed: {exc}", prediction=None,
                         recommendation=None)
            self._off()
            return
        if history.empty:
            self._update(message="Waiting for sensor readings", prediction=None,
                         recommendation=None)
            self._off()
            return
        if self.session_start is None:
            new_readings = history.loc[history["time"] >= self.auto_start]
            if new_readings.empty:
                self._update(message="Waiting for a new sensor reading")
                self._off()
                return
            self.session_start = new_readings["time"].iloc[0]
            self.predictor.start_session(new_readings.iloc[0])
        history = history.loc[history["time"] >= self.session_start]
        try:
            prediction = self.predictor.predict(history, session_start=self.session_start)
        except ValueError as exc:
            self._update(message=str(exc), prediction=None, recommendation=None)
            self._off()
            return
        from pipeline.recommender import decide

        decision = decide(history, prediction)
        if decision["fan_on"] is None:
            self._update(message=decision["reason"], prediction=prediction,
                         recommendation=None)
            self._off()
            return
        now = time.monotonic()
        keep_running = self.minimum_until is not None and now < self.minimum_until
        desired_on = decision["fan_on"] or keep_running
        if self.cancel.is_set():
            return
        was_on = self.snapshot()["fan"] == "Commanded ON"
        self._set_fan(desired_on)
        if desired_on and not was_on:
            self.minimum_until = time.monotonic() + decision["minimum_run_seconds"]
        if not desired_on:
            self.minimum_until = None
        message = decision["reason"]
        if keep_running and not decision["fan_on"]:
            message += " Finishing the 10-minute minimum run."
        self._update(message=message, prediction=prediction,
                     recommendation=decision["recommendation"])

    def _run(self):
        next_refresh = None
        while True:
            try:
                command = self.commands.get(timeout=0.1)
            except Empty:
                command = None
            try:
                if command in ("stop", "off", "close"):
                    next_refresh = None
                    self.reader = self.predictor = None
                    self._update(mode="Stopped", message=self._off(), prediction=None,
                                 recommendation=None)
                    if command == "close":
                        return
                elif command == "on":
                    self.reader = self.predictor = None
                    self.minimum_until = None
                    self._set_fan(True)
                    self._update(mode="Manual", message="Manual ON; refreshed every 5 seconds",
                                 prediction=None, recommendation=None)
                    next_refresh = time.monotonic() + 5
                elif command == "auto":
                    if self.snapshot()["mode"] != "Auto":
                        self._off()
                        self._start_auto()
                    next_refresh = time.monotonic()
                elif command == "check":
                    result = self.fan.status()
                    self._update(message="ESP32 connected", fan="Commanded " + result["state"].upper())
                if self.commands.empty():
                    self.cancel.clear()
                if next_refresh is not None and time.monotonic() >= next_refresh and not self.cancel.is_set():
                    if self.snapshot()["mode"] == "Auto":
                        self._tick_auto()
                    else:
                        self._set_fan(True)
                    next_refresh = time.monotonic() + 5
            except Exception as exc:
                next_refresh = None
                self._update(mode="Error", message=f"{exc}. {self._off()}",
                             prediction=None, recommendation=None)


runtime = Controller()
atexit.register(runtime.shutdown)


def main():
    import sys

    os.execv(sys.executable, [sys.executable, "-m", "streamlit", "run",
                             str(ROOT / "dashboard.py"),
                             "--server.address=127.0.0.1", "--server.port=8501",
                             "--server.fileWatcherType=none",
                             "--browser.gatherUsageStats=false"])


if __name__ == "__main__":
    main()
