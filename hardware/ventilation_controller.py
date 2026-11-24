"""Ventilation recommendation logic for live CO2 monitoring.

Uses current and predicted CO2 levels to recommend ventilation
actions without automatically controlling physical hardware.
"""

from dataclasses import dataclass
from enum import Enum

import math
import pandas as pd


class VentilationState(str, Enum):
    NORMAL = "NORMAL"
    MONITOR = "MONITOR"
    INCREASE_VENTILATION = "INCREASE_VENTILATION"
    TURN_FAN_ON = "TURN_FAN_ON"

@dataclass(frozen=True)
class VentilationConfig:
    """Project-approved ventilation thresholds in ppm."""

    monitor_ppm: float
    increase_ventilation_ppm: float
    fan_on_ppm: float

    def __post_init__(self):
        thresholds = (
            self.monitor_ppm,
            self.increase_ventilation_ppm,
            self.fan_on_ppm
        )

        if not all(math.isfinite(v) and v > 0 for v in thresholds):
            raise ValueError(
                "CO2 thresholds must be finite and positive."
            )

        if not (
            self.monitor_ppm
            < self.increase_ventilation_ppm
            < self.fan_on_ppm
        ):
            raise ValueError(
                "CO2 thresholds must be in increasing order."
            )

def validate_current_reading(history, max_age_seconds=60):
    """Retrieve and validate the latest sensor reading."""

    if not isinstance(history, pd.DataFrame) or history.empty:
        raise ValueError("Sensor history is missing or empty.")

    required_columns = {"time", "co2", "is_stale"}

    if not required_columns.issubset(history.columns):
        raise ValueError("Required sensor columns are missing.")

    readings = history.copy()
    readings["time"] = pd.to_datetime(
        readings["time"], utc=True, errors="coerce"
    )

    if readings["time"].isna().any():
        raise ValueError("Invalid sensor timestamp.")

    latest = readings.sort_values("time").iloc[-1]

    co2 = float(latest["co2"])

    if not math.isfinite(co2) or not 0 < co2 <= 50000:
        raise ValueError("Invalid current CO2 measurement.")

    if pd.isna(latest["is_stale"]) or latest["is_stale"]:
        raise ValueError("Current sensor reading is stale or invalid.")

    now = pd.Timestamp.now(tz="UTC")
    age = (now - latest["time"]).total_seconds()

    if age < 0:
        raise ValueError("Sensor timestamp is in the future.")

    if age > max_age_seconds:
        raise ValueError("Current sensor reading has expired.")

    return {
        "time": latest["time"],
        "co2": co2,
        "is_stale": False
    }

def validate_forecast(prediction, current_reading):
    """Validate the forecast produced by the live predictor."""

    if not isinstance(prediction, dict) or not prediction:
        raise ValueError("Forecast is missing.")

    required_fields = {
        "predicted_co2",
        "forecast_timestamp",
        "horizon_minutes",
        "validation_status",
        "is_stale"
    }

    if not required_fields.issubset(prediction):
        raise ValueError("Required forecast fields are missing.")

    if prediction["validation_status"] != "valid":
        raise ValueError("Forecast validation failed.")

    if prediction["is_stale"] is not False:
        raise ValueError("Forecast is stale or invalid.")

    try:
        predicted_co2 = float(prediction["predicted_co2"])
    except (TypeError, ValueError):
        raise ValueError("Invalid predicted CO2 measurement.")

    if not math.isfinite(predicted_co2) or not 0 < predicted_co2 <= 50000:
        raise ValueError("Invalid predicted CO2 measurement.")

    if prediction["horizon_minutes"] != 5:
        raise ValueError("Unexpected forecast horizon.")

    forecast_time = pd.to_datetime(
        prediction["forecast_timestamp"],
        utc=True,
        errors="coerce"
    )

    if pd.isna(forecast_time):
        raise ValueError("Invalid forecast timestamp.")

    now = pd.Timestamp.now(tz="UTC")

    if forecast_time <= now:
        raise ValueError("Forecast has expired.")

    expected_time = (
        current_reading["time"] + pd.Timedelta(minutes=5)
    )

    if forecast_time != expected_time:
        raise ValueError("Forecast does not match current reading.")

    return {
        "predicted_co2": predicted_co2,
        "forecast_timestamp": forecast_time,
        "horizon_minutes": 5,
        "validation_status": "valid",
        "is_stale": False
    }

def classify_co2(co2, config):
    """Classify CO2 using configured ventilation thresholds."""

    if co2 >= config.fan_on_ppm:
        return VentilationState.TURN_FAN_ON

    if co2 >= config.increase_ventilation_ppm:
        return VentilationState.INCREASE_VENTILATION

    if co2 >= config.monitor_ppm:
        return VentilationState.MONITOR

    return VentilationState.NORMAL

def determine_state(current_co2, predicted_co2, config):
    """Determine a proposed state using current and forecast CO2."""

    current_state = classify_co2(current_co2, config)

    if predicted_co2 is None:
        return (
            current_state,
            "Forecast unavailable. Using current CO2 only."
        )

    predicted_state = classify_co2(predicted_co2, config)

    severity = {
        VentilationState.NORMAL: 0,
        VentilationState.MONITOR: 1,
        VentilationState.INCREASE_VENTILATION: 2,
        VentilationState.TURN_FAN_ON: 3
    }

    if severity[predicted_state] > severity[current_state]:
        return (
            predicted_state,
            f"Forecasted CO2 increase from {current_co2:.1f} "
            f"to {predicted_co2:.1f} ppm warrants escalation."
        )

    return (
        current_state,
        f"Recommendation based on current CO2 "
        f"of {current_co2:.1f} ppm."
    )

def apply_hysteresis(
    proposed_state,
    previous_state,
    current_co2,
    predicted_co2,
    config,
    hysteresis_ppm
):
    """Prevent frequent switching between ventilation states."""

    if not math.isfinite(hysteresis_ppm) or hysteresis_ppm < 0:
        raise ValueError("Invalid hysteresis margin.")

    if previous_state is None or hysteresis_ppm == 0:
        return proposed_state

    previous_state = VentilationState(previous_state)

    severity = {
        VentilationState.NORMAL: 0,
        VentilationState.MONITOR: 1,
        VentilationState.INCREASE_VENTILATION: 2,
        VentilationState.TURN_FAN_ON: 3
    }

    # Allow immediate escalation.
    if severity[proposed_state] >= severity[previous_state]:
        return proposed_state

    thresholds = {
        VentilationState.MONITOR: config.monitor_ppm,
        VentilationState.INCREASE_VENTILATION:
            config.increase_ventilation_ppm,
        VentilationState.TURN_FAN_ON: config.fan_on_ppm
    }

    effective_co2 = current_co2

    if predicted_co2 is not None:
        effective_co2 = max(current_co2, predicted_co2)

    release_threshold = (
        thresholds[previous_state] - hysteresis_ppm
    )

    if effective_co2 >= release_threshold:
        return previous_state

    return proposed_state

def decide(
    history,
    prediction,
    previous_fan_state=None,
    *,
    config,
    hysteresis_ppm
):
    """Return a ventilation recommendation without actuating hardware.

    previous_fan_state must be a previous recommendation state
    or None, not a physical fan on/off boolean.
    """

    result = {
        "state": None,
        "explanation": None,
        "decision_timestamp": pd.Timestamp.now(tz="UTC").isoformat(),
        "reading_timestamp": None,
        "forecast_timestamp": None,
        "current_co2": None,
        "predicted_co2": None,
        "validation_status": "valid",
        "fallback": False,
        "error": None,
        "fan_requested": None
    }

    # Validate current sensor data.
    try:
        current = validate_current_reading(history)
    except (ValueError, TypeError) as e:
        result["validation_status"] = "invalid"
        result["fallback"] = True
        result["error"] = str(e)
        result["explanation"] = (
            "Current sensor data unavailable. "
            "No new ventilation recommendation issued."
        )
        return result

    result["current_co2"] = current["co2"]
    result["reading_timestamp"] = current["time"].isoformat()

    # Validate forecast or fall back to current CO2.
    predicted_co2 = None

    try:
        forecast = validate_forecast(prediction, current)

        predicted_co2 = forecast["predicted_co2"]

        result["predicted_co2"] = predicted_co2
        result["forecast_timestamp"] = (
            forecast["forecast_timestamp"].isoformat()
        )

    except (ValueError, TypeError) as e:
        result["fallback"] = True
        result["validation_status"] = "degraded"
        result["error"] = str(e)

    # Determine the proposed ventilation state.
    proposed_state, explanation = determine_state(
        current["co2"],
        predicted_co2,
        config
    )

    # Apply transition stability.
    final_state = apply_hysteresis(
        proposed_state,
        previous_fan_state,
        current["co2"],
        predicted_co2,
        config,
        hysteresis_ppm
    )

    if final_state != proposed_state:
        explanation += (
            " Previous recommendation retained by hysteresis."
        )

    result["state"] = final_state.value
    result["explanation"] = explanation

    # Recommendation only. No hardware commands.
    result["fan_requested"] = (
        final_state == VentilationState.TURN_FAN_ON
    )

    return result