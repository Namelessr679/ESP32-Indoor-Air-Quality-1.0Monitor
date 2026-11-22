"""Streamlit rendering and shared-controller tests; no real device traffic."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
from dashboard_runtime import DashboardRuntime, runtime


class DashboardTests(unittest.TestCase):
    def app(self):
        return AppTest.from_file(str(Path(__file__).resolve().parents[1] / "dashboard.py"))

    def test_initial_dashboard_and_rerun(self):
        app = self.app().run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.button), 5)
        self.assertIn("KCO2-HW-01", " ".join(x.value for x in app.markdown))
        self.assertEqual(app.metric[0].value, "Stopped")
        app.run()
        self.assertFalse(app.exception)
        self.assertIsNone(runtime._runner)

    def test_controls_forward_once(self):
        with patch.object(runtime, "command") as command:
            app = self.app().run()
            for key in ("start", "stop", "on", "off", "check"):
                app.button(key=key).click().run()
                command.assert_called_with(key)
                self.assertFalse(app.exception)
            self.assertEqual(command.call_count, 5)

    def test_setup_error_is_displayed(self):
        with patch.object(runtime, "command", side_effect=ValueError("Configure ESP32 token")):
            app = self.app().run()
            app.button(key="check").click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.error[0].value, "Configure ESP32 token")

    def test_successful_reading_and_prediction_render(self):
        state = {"mode": "Auto", "fan": "Commanded ON", "message": "Test result",
                 "reading": {"timestamp": "2026-11-22T22:00:00Z", "co2": 900,
                             "temperature": 23, "humidity": 45},
                 "prediction": {"predicted_co2": 1200, "horizon_minutes": 5},
                 "recommendation": "Increase ventilation"}
        with patch.object(runtime, "snapshot", return_value=state):
            app = self.app().run()
            self.assertFalse(app.exception)
            self.assertIn("1200 ppm", [m.value for m in app.metric])

    def test_concurrent_tabs_create_only_one_runner(self):
        shared = DashboardRuntime()
        with patch("dashboard_runtime.load_config", return_value={}), patch("dashboard_runtime.Runner") as factory:
            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(shared.command, ["check"] * 8))
            factory.assert_called_once()
            self.assertEqual(factory.return_value.command.call_count, 8)
            shared.shutdown()
            factory.return_value.command.assert_called_with("close")
            factory.return_value.worker.join.assert_called_once_with(timeout=6)


if __name__ == "__main__":
    unittest.main()
