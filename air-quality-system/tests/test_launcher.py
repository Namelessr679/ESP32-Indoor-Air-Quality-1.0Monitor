import json
import threading
import time
import unittest
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from main import Runner, validate_readings, pending_tickets
from pipeline.sensor_reader import WaitingForData
from pipeline.fan_controller import FanController, FanError


def reading(age=0):
    return {"timestamp": (datetime.now(timezone.utc) - timedelta(seconds=age)).isoformat(),
            "co2": 900., "temperature": 23., "humidity": 45.}


class FakeFan:
    def __init__(self): self.calls = []
    def set_state(self, on):
        self.calls.append(on)
        return {"command_applied": True, "state": "on" if on else "off"}
    def status(self): return {"state": "off"}


class FakeReader:
    def __init__(self, age=0): self.age = age
    def get_recent_readings(self): return [reading(self.age)]
    def close(self): pass


class FakeModel:
    def predict(self, readings):
        return {"predicted_co2": 1200., "horizon_minutes": 5}


def decision(*args):
    return {"recommendation": "Test only", "reason": "Injected test result", "fan_on": True}


CONFIG = {"pipeline": {"interval_seconds": 0.05, "max_reading_age_seconds": 30}}


class RunnerTests(unittest.TestCase):
    def wait_for(self, condition):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if condition(): return
            time.sleep(.01)
        self.fail("Worker did not reach expected state")

    def make_runner(self, factory=None):
        fan = FakeFan()
        runner = Runner(CONFIG, fan=fan, components=factory)
        def cleanup():
            runner.command("close")
            runner.worker.join(2)
            self.assertFalse(runner.worker.is_alive())
        self.addCleanup(cleanup)
        return runner, fan

    def test_missing_tickets_block_auto(self):
        self.assertEqual(len(pending_tickets()), 3)
        runner, fan = self.make_runner()
        runner.command("start")
        self.wait_for(lambda: runner.snapshot()["mode"] == "Error")
        self.assertIn("KCO2-HW-01", runner.snapshot()["message"])
        self.assertNotIn(True, fan.calls)

    def test_auto_stop_and_repeated_start(self):
        creations = []
        def factory():
            creations.append(1)
            return FakeReader(), FakeModel(), decision
        runner, fan = self.make_runner(factory)
        runner.command("start")
        runner.command("start")
        self.wait_for(lambda: True in fan.calls)
        self.assertEqual(len(creations), 1)
        runner.command("stop")
        self.wait_for(lambda: runner.snapshot()["mode"] == "Stopped")
        self.assertFalse(fan.calls[-1])

    def test_manual_works_without_hw_tickets(self):
        runner, fan = self.make_runner()
        runner.command("on")
        self.wait_for(lambda: True in fan.calls)
        runner.command("off")
        self.wait_for(lambda: runner.snapshot()["mode"] == "Stopped")
        self.assertFalse(fan.calls[-1])

    def test_stale_data_never_turns_on(self):
        runner, fan = self.make_runner(lambda: (FakeReader(90), FakeModel(), decision))
        runner.command("start")
        self.wait_for(lambda: "stale" in runner.snapshot()["message"])
        self.assertNotIn(True, fan.calls)

    def test_stop_during_prediction_suppresses_on(self):
        entered, release = threading.Event(), threading.Event()
        class SlowModel:
            def predict(self, readings):
                entered.set()
                release.wait(2)
                return FakeModel().predict(readings)
        runner, fan = self.make_runner(lambda: (FakeReader(), SlowModel(), decision))
        runner.command("start")
        self.assertTrue(entered.wait(1))
        runner.command("stop")
        release.set()
        self.wait_for(lambda: runner.snapshot()["mode"] == "Stopped")
        self.assertNotIn(True, fan.calls)

    def test_invalid_decision_stops_auto(self):
        def bad(*args): return {"fan_on": "yes", "reason": "bad", "recommendation": "bad"}
        runner, fan = self.make_runner(lambda: (FakeReader(), FakeModel(), bad))
        runner.command("start")
        self.wait_for(lambda: runner.snapshot()["mode"] == "Error")
        self.assertNotIn(True, fan.calls)

    def test_reading_validation(self):
        validate_readings([reading()], 30)
        with self.assertRaises(WaitingForData): validate_readings([reading(60)], 30)
        with self.assertRaises(ValueError): validate_readings([reading(-60)], 30)
        row = reading()
        row["co2"] = float("nan")
        with self.assertRaises(ValueError): validate_readings([row], 30)


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self): self.reply({"state": "off"})
            def do_POST(self):
                data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if self.headers.get("X-API-Key") != "test-token-123456":
                    self.send_error(401)
                    return
                self.reply({"command_applied": True, "state": data["state"]})
            def reply(self, data):
                body = json.dumps(data).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def test_actual_http_command_and_status(self):
        client = FanController(self.url, "test-token-123456")
        self.assertEqual(client.status()["state"], "off")
        self.assertEqual(client.set_state(True)["state"], "on")
        self.assertEqual(client.set_state(False)["state"], "off")

    def test_auth_failure(self):
        with self.assertRaises(FanError):
            FanController(self.url, "incorrect-token-123").set_state(True)

    def test_mismatched_acknowledgement(self):
        client = FanController(self.url, "test-token-123456")
        with patch.object(client, "_request", return_value={"command_applied": True, "state": "off"}):
            with self.assertRaises(FanError): client.set_state(True)

    def test_invalid_state_rejected(self):
        with self.assertRaises(ValueError):
            FanController(self.url, "test-token-123456").set_state("on")


if __name__ == "__main__": unittest.main()
