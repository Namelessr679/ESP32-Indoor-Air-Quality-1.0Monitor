"""KCO2-HW-03 — Ventilation recommendation logic. Owned by teammate."""

IMPLEMENTED = False


def decide(readings, prediction, previous_fan_state):
    """Return recommendation: str, fan_on: bool, reason: str in a dict.

    previous_fan_state is the last acknowledged output (bool). The ticket owner
    supplies thresholds/hysteresis. The launcher deliberately supplies no policy.
    """
    raise NotImplementedError("KCO2-HW-03 — Ventilation recommendation logic")
