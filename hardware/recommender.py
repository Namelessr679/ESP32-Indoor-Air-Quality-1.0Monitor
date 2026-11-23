"""KCO2-HW-03 — Ventilation recommendation logic. Owned by teammate."""

IMPLEMENTED = False


def decide(history, prediction, previous_fan_state):
    """Return recommendation: str, fan_on: bool, reason: str in a dict.

    history is PR #4's chronological DataFrame (time, co2, temp_c, rh, is_stale).
    prediction has predicted_co2 (absolute ppm) and horizon_minutes.
    Return ALL three fields on every decision, e.g.:
    {"recommendation": "Turn fan on", "fan_on": True, "reason": "Threshold exceeded"}.
    Only decide: main.py displays the result and sends it via fan_controller.py.
    previous_fan_state is the last acknowledged output (bool). The ticket owner
    supplies thresholds/hysteresis. The launcher deliberately supplies no policy.
    """
    raise NotImplementedError("KCO2-HW-03 — Ventilation recommendation logic")
