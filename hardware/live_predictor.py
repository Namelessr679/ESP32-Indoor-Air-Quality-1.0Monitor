"""KCO2-HW-02 - Live CO2 feature engineering and prediction."""

from pathlib import Path

import joblib
import numpy as np
import pandas as pd


# Exact feature names and order from kc_common.py.
MODEL_FEATURES = [
    "CO2_now", "Temp_now", "Humidity_now",
    "CO2_prev_1min", "CO2_prev_5min", "CO2_prev_10min",
    "CO2_change_1min", "CO2_change_5min", "CO2_change_10min",
    "CO2_mean_5min", "CO2_mean_10min",
    "CO2_std_5min", "CO2_std_10min",
    "CO2_slope_1min", "CO2_slope_5min", "CO2_slope_10min",
    "Temp_mean_5min", "Humidity_mean_5min",
    "Temp_slope_5min", "Humidity_slope_5min",
    "initial_CO2", "CO2_change_from_start", "session_elapsed_minutes",
]

# Training configuration.
FORECAST_HORIZON_MINUTES = 5
LAG_TOLERANCE = pd.Timedelta(seconds=30)
MAX_SEQUENCE_GAP_SECONDS = 30
MAX_READING_AGE_SECONDS = 60
# Minimum historical span required by the 10-minute lag feature.
MIN_HISTORY_MINUTES = 10

def validate_history(history, session_start):
    """Validate and prepare live sensor readings."""

    required_columns = [
        "time", "co2", "temp_c", "rh", "is_stale"
    ]

    if not isinstance(history, pd.DataFrame):
        raise TypeError("History must be a Pandas DataFrame.")

    missing = [
        column for column in required_columns
        if column not in history.columns
    ]

    if missing:
        raise ValueError(
            f"Missing required history columns: {missing}"
        )

    if history.empty:
        raise ValueError("No sensor readings available.")

    cleaned = history.copy()

    cleaned["time"] = pd.to_datetime(
        cleaned["time"], utc=True, errors="coerce"
    )

    start = pd.to_datetime(session_start, utc=True)

    if pd.isna(start):
        raise ValueError("Invalid session_start timestamp.")

    # Convert sensor measurements to numeric values.
    for column in ["co2", "temp_c", "rh"]:
        cleaned[column] = pd.to_numeric(
            cleaned[column], errors="coerce"
        )

    # Remove invalid or physically implausible measurements.
    valid_measurements = (
        cleaned["co2"].between(1, 40000)
        & cleaned["temp_c"].between(-40, 85)
        & cleaned["rh"].between(0, 100)
    )

    cleaned = cleaned.loc[valid_measurements].copy()

    cleaned = cleaned.dropna(subset=["time"])

    cleaned = cleaned.loc[
        cleaned["time"] >= start
    ]

    cleaned = cleaned.sort_values("time")
    cleaned = cleaned.drop_duplicates(
        subset=["time"], keep="first"
    )

    if cleaned.empty:
        raise ValueError(
            "No valid readings after session start."
        )

        # Only the newest reading must be fresh.
    latest_reading = cleaned.iloc[-1]

    if pd.isna(latest_reading["is_stale"]):
        raise ValueError(
            "Cannot predict: latest sensor freshness is unknown."
        )

    if isinstance(latest_reading["is_stale"], (bool, np.bool_)):
        latest_is_stale = bool(latest_reading["is_stale"])
    else:
        raise ValueError(
            "Cannot predict: latest is_stale flag must be boolean."
        )

    if latest_is_stale:
        raise ValueError(
            "Cannot predict: latest sensor reading is stale."
        )
        # Independently verify the latest reading timestamp.
    current_time = pd.Timestamp.now(tz="UTC")

    reading_age = (
        current_time - latest_reading["time"]
    ).total_seconds()

    if reading_age > MAX_READING_AGE_SECONDS:
        raise ValueError(
            "Cannot predict: latest sensor reading is too old."
        )

    if reading_age < -MAX_READING_AGE_SECONDS:
        raise ValueError(
            "Cannot predict: latest sensor timestamp is in the future."
        )

    # Check gaps between consecutive sensor readings.
    time_gaps = cleaned["time"].diff().dt.total_seconds()

    if (time_gaps > MAX_SEQUENCE_GAP_SECONDS).any():
        raise ValueError(
            "Sensor history contains gaps exceeding 30 seconds."
        )

    # Require enough history for the 10-minute lag features.
    history_span = (
        cleaned["time"].iloc[-1] - cleaned["time"].iloc[0]
    ).total_seconds()

    if history_span < MIN_HISTORY_MINUTES * 60:
        raise ValueError(
            "Insufficient history: at least 10 minutes required."
        )
    return cleaned.reset_index(drop=True)

def calculate_co2_lag(history, minutes):
    """Find the CO2 reading closest to the requested past offset."""

    target_time = history["time"].iloc[-1] - pd.Timedelta(
        minutes=minutes
    )

    time_differences = (
        history["time"] - target_time
    ).abs()

    closest_index = time_differences.idxmin()

    if time_differences.loc[closest_index] > LAG_TOLERANCE:
        return np.nan

    return float(history.loc[closest_index, "co2"])

def calculate_rolling_stat(history, column, minutes, stat):
    """Calculate a time-based rolling mean or standard deviation."""

    rolling = history.rolling(
        f"{minutes}min",
        on="time",
        min_periods=2
    )[column]

    if stat == "mean":
        return float(rolling.mean().iloc[-1])

    if stat == "std":
        return float(rolling.std().iloc[-1])

    raise ValueError(f"Unknown rolling statistic: {stat}")

def calculate_slope(history, column, minutes):
    """Calculate the slope of sensor readings per minute."""

    latest_time = history["time"].iloc[-1]

    window_start = latest_time - pd.Timedelta(
        minutes=minutes
    )

# Include readings at both ends of the time window.
    window = history.loc[
        history["time"] >= window_start
    ].copy()

    if len(window) < 2:
        return np.nan

# Convert timestamps into elapsed minutes.
    elapsed_minutes = (
        window["time"] - window["time"].iloc[0]
    ).dt.total_seconds() / 60.0

    values = window[column].to_numpy(dtype=float)

# Calculate the linear regression slope.
    slope = np.polyfit(
        elapsed_minutes.to_numpy(),
        values,
        1
    )[0]

    return float(slope)

def build_live_features(history, *, session_start=None, initial_co2=None):
    """Build the 23 model features from validated sensor history."""

    latest = history.iloc[-1]
    current_co2 = float(latest["co2"])

    features = {
        "CO2_now": current_co2,
        "Temp_now": float(latest["temp_c"]),
        "Humidity_now": float(latest["rh"]),
    }

    # Historical CO2 readings and changes.
    for minutes in [1, 5, 10]:
        previous_co2 = calculate_co2_lag(history, minutes)

        features[f"CO2_prev_{minutes}min"] = previous_co2
        features[f"CO2_change_{minutes}min"] = (
            current_co2 - previous_co2
        )

    # Rolling CO2 statistics.
    for minutes in [5, 10]:
        features[f"CO2_mean_{minutes}min"] = (
            calculate_rolling_stat(history, "co2", minutes, "mean")
        )
        features[f"CO2_std_{minutes}min"] = (
            calculate_rolling_stat(history, "co2", minutes, "std")
        )

    # CO2 slopes.
    for minutes in [1, 5, 10]:
        features[f"CO2_slope_{minutes}min"] = (
            calculate_slope(history, "co2", minutes)
        )

    # Temperature and humidity statistics.
    features["Temp_mean_5min"] = (
        calculate_rolling_stat(history, "temp_c", 5, "mean")
    )
    features["Humidity_mean_5min"] = (
        calculate_rolling_stat(history, "rh", 5, "mean")
    )

    features["Temp_slope_5min"] = (
        calculate_slope(history, "temp_c", 5)
    )
    features["Humidity_slope_5min"] = (
        calculate_slope(history, "rh", 5)
    )

    # Session-based features.
    first_time = history["time"].iloc[0]

    if session_start is not None:
        first_time = pd.to_datetime(session_start, utc=True)

    if initial_co2 is None:
        if session_start is not None and first_time < history["time"].iloc[0]:
            raise ValueError(
                "Original session CO2 is required for sliding history."
            )
        initial_co2 = float(history["co2"].iloc[0])

    initial_co2 = float(initial_co2)

    if not np.isfinite(initial_co2) or initial_co2 <= 0:
        raise ValueError("Invalid initial session CO2.")

    features["initial_CO2"] = initial_co2
    features["CO2_change_from_start"] = current_co2 - initial_co2

    features["session_elapsed_minutes"] = (
        history["time"].iloc[-1] - first_time
    ).total_seconds() / 60.0

    # Preserve the exact feature order used during training.
    return pd.DataFrame([features], columns=MODEL_FEATURES)

class Predictor:
    """Generate live CO2 forecasts using a trained model."""

    def __init__(self, model_path):
        self.model_path = Path(model_path)
        self.model = None
        self.preprocessor = None

        # Preserve the original CO2 reading for each recording session.
        self.session_start = None
        self.initial_co2 = None

    def load_model(self):
        """Load the approved trained model and preprocessing pipeline."""

        if not self.model_path.is_file():
            raise FileNotFoundError(
                f"Trained model artifact not found: {self.model_path}"
            )

        artifact = joblib.load(self.model_path)

        # Support a saved scikit-learn pipeline.
        if hasattr(artifact, "named_steps"):
            components = artifact.named_steps

        # Support a dictionary containing model components.
        elif isinstance(artifact, dict):
            components = artifact

        else:
            raise ValueError(
                "Unsupported trained model artifact format."
            )

        if "model" not in components or "preprocessor" not in components:
            raise ValueError(
                "Model artifact must contain 'model' and 'preprocessor'."
            )

        self.model = components["model"]
        self.preprocessor = components["preprocessor"]

    def predict(self, history, *, session_start):
        """Predict future CO2 using historical sensor readings.

        Args:
            history: DataFrame containing time, co2, temp_c, rh,
                     and is_stale.
            session_start: Fixed UTC start of the recording session.

        Returns:
            Dictionary containing predicted_co2 and horizon_minutes.
        """
                # Load the approved model when first needed.
        if self.model is None or self.preprocessor is None:
            self.load_model()

                # Validate incoming sensor history.
        cleaned = validate_history(history, session_start)

        # Normalize the session start timestamp.
        current_session_start = pd.to_datetime(
            session_start, utc=True
        )

        # Reset saved information when a new session begins.
        if self.session_start != current_session_start:
            self.session_start = current_session_start
            self.initial_co2 = None

        # Capture the original reading when it is available.
        first_reading_time = cleaned["time"].iloc[0]

        if self.initial_co2 is None:
            if first_reading_time > current_session_start + pd.Timedelta(
                seconds=MAX_SEQUENCE_GAP_SECONDS
            ):
                raise ValueError(
                    "Original session CO2 is unavailable. "
                    "Cannot initialize from sliding history."
                )

            self.initial_co2 = float(cleaned["co2"].iloc[0])

        # Generate features using the original session information.
        features = build_live_features(
            cleaned,
            session_start=first_reading_time
            if self.initial_co2 is not None
            and first_reading_time == current_session_start
            else current_session_start,
            initial_co2=self.initial_co2,
        )

        if features.isna().any().any():
            raise ValueError(
                "Cannot predict: required model features are missing."
            )

        # Apply the fitted training preprocessor.
        model_input = self.preprocessor.transform(features)

        # The model predicts the five-minute change in CO2.
        predicted_change = float(
            self.model.predict(model_input)[0]
        )

        current_co2 = float(features["CO2_now"].iloc[0])
        predicted_co2 = current_co2 + predicted_change

        if not np.isfinite(predicted_co2):
            raise ValueError(
                "Model returned an invalid CO2 prediction."
            )

                # Calculate when the forecast applies.
        latest_time = cleaned["time"].iloc[-1]

        forecast_time = latest_time + pd.Timedelta(
            minutes=FORECAST_HORIZON_MINUTES
        )

        return {
            "predicted_co2": predicted_co2,
            "horizon_minutes": FORECAST_HORIZON_MINUTES,
            "forecast_timestamp": forecast_time.isoformat(),
            "model_identifier": self.model_path.name,
            "validation_status": "valid",
            "is_stale": False,
        }