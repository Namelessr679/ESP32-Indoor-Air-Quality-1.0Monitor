"""Streamlit launcher and shared manual fan controller."""

import atexit
import importlib
import os
import time
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
        self.commands = Queue()
        self.cancel = Event()
        self.lock = Lock()
        self.state = {"mode": "Stopped", "message": "Configure config.yaml, then check ESP32.",
                      "fan": "Unknown"}
        self.worker = None

    def snapshot(self):
        with self.lock:
            return self.state.copy()

    def _update(self, **values):
        with self.lock:
            self.state.update(values)

    def command(self, name):
        if name not in ("stop", "on", "off", "check", "close"):
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
        try:
            self._set_fan(False)
            return "OFF acknowledged"
        except Exception:
            return "OFF not acknowledged; ESP32 will request OFF when its 30-second lease is checked"

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
                    self._update(mode="Stopped", message=self._off())
                    if command == "close":
                        return
                elif command == "on":
                    self._set_fan(True)
                    self._update(mode="Manual", message="Manual ON; refreshed every 5 seconds")
                    next_refresh = time.monotonic() + 5
                elif command == "check":
                    result = self.fan.status()
                    self._update(message="ESP32 connected", fan="Commanded " + result["state"].upper())
                if self.commands.empty():
                    self.cancel.clear()
                if next_refresh is not None and time.monotonic() >= next_refresh and not self.cancel.is_set():
                    self._set_fan(True)
                    next_refresh = time.monotonic() + 5
            except Exception as exc:
                next_refresh = None
                self._update(mode="Error", message=f"{exc}. {self._off()}")


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
