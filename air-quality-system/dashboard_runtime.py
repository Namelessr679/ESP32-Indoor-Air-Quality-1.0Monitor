"""One shared runner for every browser tab in this Streamlit process."""
import atexit
from threading import Lock

from main import Runner, load_config


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
