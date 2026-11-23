"""KCO2-HW-03 — Ventilation recommendation logic. Owned by teammate."""

IMPLEMENTED = False


def decide(history, prediction, previous_fan_state):
    """Return recommendation: str, fan_on: bool, reason: str, and optional
    minimum_run_seconds: nonnegative number in a dict.

    history is PR #4's chronological DataFrame (time, co2, temp_c, rh, is_stale).
    prediction has predicted_co2 (absolute ppm) and horizon_minutes.
    Return ALL three fields on every decision, e.g.:
    {"recommendation": "Turn fan on", "fan_on": True, "reason": "Threshold exceeded", "minimum_run_seconds": 300}.
    Only decide: main.py enforces the minimum after acknowledged ON and sends
    commands via control/fan_controller.py. Stop/Manual OFF bypass the minimum.
    previous_fan_state is the last acknowledged output (bool). The ticket owner
    supplies thresholds/hysteresis. The launcher deliberately supplies no policy.
    """
    raise NotImplementedError("KCO2-HW-03 — Ventilation recommendation logic")
