"""Choose an ON/OFF fan recommendation from current and predicted CO₂."""

import math

import pandas as pd


def _current_co2(history):
    if history.empty or not {"time", "co2", "is_stale"}.issubset(history.columns):
        raise ValueError("No sensor reading available")
    reading = history.iloc[-1]
    timestamp = pd.to_datetime(reading["time"], utc=True)
    age = (pd.Timestamp.now(tz="UTC") - timestamp).total_seconds()
    co2 = float(reading["co2"])
    if reading["is_stale"] or not 0 <= age <= 60 or not math.isfinite(co2) or co2 <= 0:
        raise ValueError("Latest sensor reading is invalid or stale")
    return timestamp, co2


def _predicted_co2(prediction, reading_time):
    if (prediction["validation_status"] != "valid" or prediction["is_stale"]
            or prediction["horizon_minutes"] != 5):
        raise ValueError("Forecast is invalid")
    forecast_time = pd.to_datetime(prediction["forecast_timestamp"], utc=True)
    if forecast_time != reading_time + pd.Timedelta(minutes=5):
        raise ValueError("Forecast does not match the latest reading")
    co2 = float(prediction["predicted_co2"])
    if not math.isfinite(co2) or co2 <= 0:
        raise ValueError("Forecast CO₂ is invalid")
    return co2


def decide(history, prediction):
    try:
        reading_time, current_co2 = _current_co2(history)
    except (KeyError, TypeError, ValueError) as exc:
        return {"recommendation": None, "reason": str(exc), "fan_on": None,
                "minimum_run_seconds": 0}

    try:
        predicted_co2 = _predicted_co2(prediction, reading_time)
        explanation = f"Predicted CO₂: {predicted_co2:.0f} ppm"
    except (KeyError, TypeError, ValueError):
        predicted_co2 = None
        explanation = "Forecast unavailable; using current CO₂"

    level = max(current_co2, predicted_co2) if predicted_co2 is not None else current_co2
    if level >= 1400:
        state = "TURN_FAN_ON"
    elif level >= 1000:
        state = "INCREASE_VENTILATION"
    elif level >= 800:
        state = "MONITOR"
    else:
        state = "NORMAL"
    fan_on = level >= 1000
    return {"recommendation": state, "reason": explanation,
            "fan_on": fan_on, "minimum_run_seconds": 600 if fan_on else 0}
