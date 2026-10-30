"""Shared local-session preparation, forecasting and evaluation functions."""
import io
import math
import random
import uuid
import hashlib
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

SCHEMA_VERSION = 2
HORIZONS = (5, 10)
APPROACHES = ("direct", "recursive")
SETUPS = tuple((horizon, approach) for horizon in HORIZONS for approach in APPROACHES)
EXPERIMENT_NAME = "local_sessions_5_10_all_approaches_v1"
RANDOM_STATE = 42
LAG_TOLERANCE = pd.Timedelta(seconds=30)
FUTURE_TOLERANCE = pd.Timedelta(seconds=30)
MAX_SEQUENCE_GAP_SECONDS = 30
TRAIN_RATIO = 0.60
VALIDATION_RATIO = 0.20
N_OPTUNA_TRIALS = 30
NUMERIC_FEATURES = [
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
CATEGORICAL_FEATURES = []
MODEL_FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES
CORE_FEATURES = NUMERIC_FEATURES.copy()

def seed_everything(seed=RANDOM_STATE):
    """Make Python and NumPy randomness repeatable."""
    random.seed(seed)
    np.random.seed(seed)

def list_session_csvs(service, folder_id):
    """Read local session CSVs directly in one folder; ignore all subfolders."""
    metadata = service.files().get(fileId=folder_id, fields="id,mimeType", supportsAllDrives=True).execute()
    if metadata["mimeType"] != "application/vnd.google-apps.folder":
        raise ValueError(f"{folder_id} is not a Drive folder.")
    page, csv_files = None, {}
    while True:
        result = service.files().list(
            q=f"'{folder_id}' in parents and trashed = false",
            fields="nextPageToken,files(id,name,mimeType)",
            pageSize=1000, pageToken=page, supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()
        for item in result.get("files", []):
            if item["mimeType"] == "application/vnd.google-apps.folder":
                continue
            if item["name"].lower().endswith(".csv") or item["mimeType"] in {"text/csv", "application/csv"}:
                csv_files[item["id"]] = item
        page = result.get("nextPageToken")
        if not page:
            break
    # File IDs preserve ordering when source files are renamed.
    return [csv_files[key] for key in sorted(csv_files)]

def read_session_csv(service, item):
    """Download into memory only; never modify or delete the source file."""
    from googleapiclient.http import MediaIoBaseDownload
    content = io.BytesIO()
    request = service.files().get_media(fileId=item["id"], supportsAllDrives=True)
    download = MediaIoBaseDownload(content, request)
    done = False
    while not done:
        _, done = download.next_chunk()
    content.seek(0)
    return pd.read_csv(content)

def clean_session(session, session_id, source_name):
    """Validate and clean one CSV, preserving timestamp order and first duplicates."""
    required = ["elapsed_minutes", "co2", "temp", "humidity"]
    missing = [column for column in required if column not in session.columns]
    if missing:
        raise KeyError(f"Missing columns {missing} in Drive CSV {source_name!r} (ID {session_id}). Filenames are unrestricted; required columns are elapsed_minutes, co2, temp, humidity.")

    session = session[required].copy()
    # A fixed internal origin keeps timestamp-based windows unchanged.
    # This is an elapsed-time index, not the recording's calendar date.
    elapsed_minutes = pd.to_numeric(session["elapsed_minutes"], errors="raise")
    session["time"] = pd.Timestamp("1970-01-01") + pd.to_timedelta(elapsed_minutes, unit="m")
    for column in ["co2", "temp", "humidity"]:
        session[column] = pd.to_numeric(session[column], errors="coerce")

    # Deduplicate before dropping missing readings to preserve the CSV cleaning policy.
    session = session.sort_values("time")
    session = session.drop_duplicates(subset=["time"], keep="first")
    session = session.dropna(subset=["time", "co2", "temp", "humidity"]).reset_index(drop=True)
    session["session_id"] = session_id
    return session


def _value_at_offset(session, source_col, minutes, tolerance):
    """Match a signed minute offset using the nearest reading within tolerance."""
    wanted = pd.DataFrame({"wanted_time": session["time"] + pd.Timedelta(minutes=minutes)})
    available = session[["time", source_col]].rename(columns={"time": "matched_time"})
    return pd.merge_asof(
        wanted, available, left_on="wanted_time", right_on="matched_time",
        direction="nearest", tolerance=tolerance,
    )[source_col].to_numpy()


def closest_value_at_offset(session, source_col, minutes):
    """Find the sensor value closest to `minutes` ago."""
    return _value_at_offset(session, source_col, -minutes, LAG_TOLERANCE)


def rolling_time_stat(session, source_col, minutes, stat):
    """Calculate a recent mean or standard deviation."""
    # 1. Create a rolling window based on real-time intervals using the 'time' column
    rolling = session.rolling(f"{minutes}min", on="time", min_periods=2)[source_col]

    # 2. Return the rolling mean if specified
    if stat == "mean":
        return rolling.mean().to_numpy()
    # 3. Return the rolling standard deviation if specified
    if stat == "std":
        return rolling.std().to_numpy()

    # 4. Raise an error if an invalid statistic name was passed
    raise ValueError(f"Unknown rolling statistic: {stat}")

def regression_slope(session, source_col, minutes):
    """Estimate change per minute using a straight-line fit."""
    # 1. Cast the target column values into a float NumPy array
    values = session[source_col].to_numpy(dtype=float)
    # 2. Get the reference timestamp series
    timestamps = session["time"]
    # 3. Define the sliding window width as a Timedelta
    window = pd.Timedelta(minutes=minutes)
    # 4. Pre-allocate an array of NaNs matching the session length
    output = np.full(len(session), np.nan)
    # 5. Initialize the left boundary pointer for the sliding window
    left = 0

    # 6. Loop through each row in the session as the right boundary
    for right in range(len(session)):
        # Determine the oldest allowed time for the current window
        cutoff = timestamps.iloc[right] - window

        # Slide the left pointer forward until it falls within the window
        while left < right and timestamps.iloc[left] < cutoff:
            left += 1

        # Extract timestamps and values within the active window
        times = timestamps.iloc[left:right + 1]
        y = values[left:right + 1]

        # A slope requires at least 2 points to be calculated
        if len(y) < 2:
            continue

        # Convert timestamps into elapsed minutes from the start of this window
        x = (times - times.iloc[0]).dt.total_seconds().to_numpy() / 60.0
        # Fit a 1st-degree polynomial (y = mx + c) and extract the slope (m)
        output[right] = np.polyfit(x, y, 1)[0]

    # 7. Return the computed slope values for all positions
    return output

def future_target(session, minutes):
    """Find the real CO₂ reading at the requested horizon."""
    return pd.DataFrame({"future_co2": _value_at_offset(session, "co2", minutes, FUTURE_TOLERANCE)})


def engineer_features(session):
    """Create model features for one recording session only."""
    # Align row numbers with future targets. Time is already sorted.
    session = session.reset_index(drop=True)

    # Current sensor readings.
    session["CO2_now"] = session["co2"]
    session["Temp_now"] = session["temp"]
    session["Humidity_now"] = session["humidity"]

    # CO₂ history, change, and slope.
    for minutes in [1, 5, 10]:
        session[f"CO2_prev_{minutes}min"] = closest_value_at_offset(session, "co2", minutes)
        session[f"CO2_change_{minutes}min"] = session["CO2_now"] - session[f"CO2_prev_{minutes}min"]
        session[f"CO2_slope_{minutes}min"] = regression_slope(session, "co2", minutes)

    # Recent CO₂ level and variation.
    for minutes in [5, 10]:
        session[f"CO2_mean_{minutes}min"] = rolling_time_stat(session, "co2", minutes, "mean")
        session[f"CO2_std_{minutes}min"] = rolling_time_stat(session, "co2", minutes, "std")

    # Temperature and humidity history.
    session["Temp_mean_5min"] = rolling_time_stat(session, "temp", 5, "mean")
    session["Humidity_mean_5min"] = rolling_time_stat(session, "humidity", 5, "mean")
    session["Temp_slope_5min"] = regression_slope(session, "temp", 5)
    session["Humidity_slope_5min"] = regression_slope(session, "humidity", 5)

    # Session context available at prediction time.
    session["initial_CO2"] = session["co2"].iloc[0]
    session["CO2_change_from_start"] = session["CO2_now"] - session["initial_CO2"]
    session["session_elapsed_minutes"] = (session["time"] - session["time"].iloc[0]).dt.total_seconds() / 60.0

    return session


def engineer_session(session):
    """Create input features and observed training targets for one session."""
    session = engineer_features(session)
    for minutes in (1, 5, 10):
        session[f"CO2_future_{minutes}min"] = future_target(session, minutes)["future_co2"]
        session[f"target_change_{minutes}min"] = session[f"CO2_future_{minutes}min"] - session["CO2_now"]
    return session


def make_session_split(session_ids, seed=RANDOM_STATE):
    """Shuffle whole sessions and split them about 60/20/20."""
    # Make sure we have enough recordings to actually divide them up
    if len(session_ids) < 5:
        raise ValueError("At least 5 usable sessions are needed.")

    # Sort the session IDs first so we always start from the exact same order
    session_ids = sorted(session_ids)

    # Use our repeatable random number generator to shuffle the list of sessions
    rng = np.random.default_rng(seed)
    shuffled = rng.permutation(session_ids).tolist()

    # Calculate how many sessions go into train (60%) and validation (20%)
    total = len(shuffled)
    n_train = round(TRAIN_RATIO * total)
    n_validation = round(VALIDATION_RATIO * total)

    # Group the shuffled sessions into three distinct lists
    train_ids = shuffled[:n_train]
    validation_ids = shuffled[n_train:n_train + n_validation]
    test_ids = shuffled[n_train + n_validation:]

    return train_ids, validation_ids, test_ids

def rows_for_sessions(frame, session_ids):
    """Pull all data rows belonging to a specific list of session IDs."""
    return (
        frame[frame["session_id"].isin(session_ids)]
        .reset_index(drop=True)
    )

def make_preprocessor(scale_numeric=False):
    """Prepare numeric features with imputation and optional scaling."""
    # Create a list of processing steps for the numeric features starting with a median imputer
    # 'keep_empty_features=True' prevents errors if any numeric columns are entirely empty/NaN
    numeric_steps = [("imputer", SimpleImputer(strategy="median", keep_empty_features=True))]

    # If standard scaling is requested, append a StandardScaler step to the numeric processing pipeline
    if scale_numeric:
        numeric_steps.append(("scaler", StandardScaler()))

    return ColumnTransformer([
        ("numeric", Pipeline(numeric_steps), NUMERIC_FEATURES),
    ], verbose_feature_names_out=False)

def metrics_from_future_co2(actual, predicted):
    """Calculate prediction errors and R²."""
    # Measure how close predictions are to actual values using standard metrics (MAE, RMSE, R2)
    return {
        "MAE": mean_absolute_error(actual, predicted),
        "RMSE": math.sqrt(mean_squared_error(actual, predicted)),
        "R2": r2_score(actual, predicted),
    }

def model_output_to_future_co2(frame, predicted_change):
    """Add predicted change to current CO₂."""
    # Take the current CO2 value and add the predicted change to get the final predicted future ppm
    return frame["CO2_now"].to_numpy() + np.asarray(predicted_change)

def result_row(model_name, frame, predicted_future):
    return {"Model": model_name, **metrics_from_future_co2(frame["Actual"], predicted_future)}


def forecast_future_co2(model, preprocessor, frame, horizon, approach, history_by_session):
    """Forecast without reading any sensor observations after each origin."""
    if approach == "direct":
        change = model.predict(preprocessor.transform(frame[MODEL_FEATURES]))
        return model_output_to_future_co2(frame, change)
    if approach != "recursive" or horizon not in HORIZONS:
        raise ValueError("Unsupported forecast setup.")
    predictions = []
    # Feature calculations use session timestamps. Future temperature,
    # humidity are held at their latest observed values.
    # Each synthetic step updates CO2 lags, slopes, rolling statistics and context.
    for row in frame.itertuples(index=False):
        session = history_by_session[row.session_id]
        observed = session.loc[session.time <= row.time]
        initial_co2 = observed.co2.iloc[0]
        start_time = observed.time.iloc[0]
        history = observed.loc[observed.time >= row.time - pd.Timedelta(minutes=10, seconds=30)].copy()
        current = pd.DataFrame([row._asdict()])[MODEL_FEATURES].copy()
        current_co2 = row.CO2_now
        for step in range(horizon):
            delta = model.predict(preprocessor.transform(current))[0]
            current_co2 = current_co2 + delta
            if step == horizon - 1:
                break
            next_row = history.iloc[-1].copy()
            next_row["time"] = row.time + pd.Timedelta(minutes=step + 1)
            next_row["co2"] = current_co2
            history = pd.concat([history, next_row.to_frame().T], ignore_index=True)
            history["time"] = pd.to_datetime(history["time"])
            for column in ["co2", "temp", "humidity"]:
                history[column] = pd.to_numeric(history[column], errors="coerce")
            features = engineer_features(history).iloc[[-1]].copy()
            features["initial_CO2"] = initial_co2
            features["CO2_change_from_start"] = current_co2 - initial_co2
            features["session_elapsed_minutes"] = (features.time - start_time).dt.total_seconds() / 60.0
            current = features[MODEL_FEATURES]
        predictions.append(current_co2)
    return np.asarray(predictions)

def setup_key(horizon, approach):
    if (horizon, approach) not in SETUPS:
        raise ValueError("Unsupported forecast setup.")
    return f"{horizon}min_{approach}"

def helper_fingerprint():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

def prepare_experiment(raw_sessions, data_folder_id):
    """Prepare identical origin rows and whole-session splits for every setup."""
    frames = [engineer_session(session.copy()) for session in raw_sessions if not session.empty]
    if not frames:
        raise ValueError("No usable session data.")
    engineered = pd.concat(frames, ignore_index=True)
    required = CORE_FEATURES + [f"CO2_future_{minutes}min" for minutes in (1, 5, 10)]
    data = engineered.dropna(subset=required).reset_index(drop=True)
    train_ids, validation_ids, test_ids = make_session_split(data.session_id.unique())
    histories = {frame.session_id.iloc[0]: frame.copy() for frame in raw_sessions if not frame.empty}
    base_train = rows_for_sessions(data, train_ids)
    base_validation = rows_for_sessions(data, validation_ids)
    base_test = rows_for_sessions(data, test_ids)
    if any(frame.empty for frame in (base_train, base_validation, base_test)):
        raise ValueError("Each session split must contain usable forecast origins.")
    prep = make_preprocessor(scale_numeric=False)
    x_train = prep.fit_transform(base_train[MODEL_FEATURES])
    x_validation = prep.transform(base_validation[MODEL_FEATURES])
    configurations = {}
    for horizon, approach in SETUPS:
        target_minutes = horizon if approach == "direct" else 1
        train, validation, test = (frame.copy() for frame in (base_train, base_validation, base_test))
        for frame in (train, validation, test):
            frame["Actual"] = frame[f"CO2_future_{horizon}min"]
            frame["target_change"] = frame[f"target_change_{target_minutes}min"]
        configurations[setup_key(horizon, approach)] = {
            "horizon": horizon, "approach": approach,
            "train_df": train, "validation_df": validation, "test_df": test,
            "tree_preprocessor": prep, "X_train_tree": x_train,
            "X_validation_tree": x_validation,
            "y_train": train.target_change.to_numpy(),
        }
    metadata = {
        "schema_version": SCHEMA_VERSION, "run_id": uuid.uuid4().hex,
        "horizons": list(HORIZONS), "approaches": list(APPROACHES),
        "data_folder_id": data_folder_id, "features": MODEL_FEATURES.copy(),
        "train_ids": train_ids, "validation_ids": validation_ids, "test_ids": test_ids,
        "seed": RANDOM_STATE, "trials": N_OPTUNA_TRIALS,
        "helper_sha256": helper_fingerprint(),
    }
    return {"metadata": metadata, "configurations": configurations, "history_by_session": histories}

def check_prepared(prepared):
    metadata = prepared["metadata"]
    if metadata.get("schema_version") != SCHEMA_VERSION or metadata.get("helper_sha256") != helper_fingerprint():
        raise ValueError("Preparation does not match the helper. Rerun notebook 00.")
    if metadata["features"] != MODEL_FEATURES or set(prepared["configurations"]) != {setup_key(*s) for s in SETUPS}:
        raise ValueError("Preparation features or forecast setups do not match.")

def make_tree_model(kind, params):
    if kind == "Random Forest":
        from sklearn.ensemble import RandomForestRegressor
        return RandomForestRegressor(random_state=RANDOM_STATE, n_jobs=-1, **params)
    if kind == "XGBoost":
        from xgboost import XGBRegressor
        return XGBRegressor(objective="reg:squarederror", random_state=RANDOM_STATE, n_jobs=-1, verbosity=0, **params)
    raise ValueError("Unknown tree model.")

def tune_and_validate(kind, suggest_params, config, histories):
    """Tune on training rows and validation MAE; never score test rows here."""
    import optuna
    seed_everything()
    prep = config["tree_preprocessor"]
    validation = config["validation_df"]
    def predict_validation(model):
        if config["approach"] == "direct":
            return model_output_to_future_co2(validation, model.predict(config["X_validation_tree"]))
        return forecast_future_co2(model, prep, validation, config["horizon"], config["approach"], histories)

    def objective(trial):
        model = make_tree_model(kind, suggest_params(trial))
        model.fit(config["X_train_tree"], config["y_train"])
        prediction = predict_validation(model)
        return mean_absolute_error(validation.Actual, prediction)
    study = optuna.create_study(direction="minimize", sampler=optuna.samplers.TPESampler(seed=RANDOM_STATE))
    study.optimize(objective, n_trials=N_OPTUNA_TRIALS)
    model = make_tree_model(kind, study.best_params)
    model.fit(config["X_train_tree"], config["y_train"])
    prediction = predict_validation(model)
    return {"params": study.best_params, "validation_predictions": prediction,
            "validation_metrics": result_row(kind, validation, prediction),
            "trial_history": study.trials_dataframe()}

def validation_selections(rf_results, xgb_results):
    """Freeze the RF/XGBoost winner per setup using validation MAE only."""
    selections = {}
    for key in rf_results:
        candidates = [rf_results[key]["validation_metrics"], xgb_results[key]["validation_metrics"]]
        selections[key] = min(candidates, key=lambda row: row["MAE"])["Model"]
    return selections

def export_tree_results(prepared, rf_results, xgb_results, selections):
    """Final refits use train plus validation; exported test scores do not alter selection."""
    metric_rows, prediction_frames, importance_frames = [], [], []
    final_prep, final_features, final_x = None, None, None
    for key, config in prepared["configurations"].items():
        horizon, approach = config["horizon"], config["approach"]
        histories = prepared["history_by_session"]
        candidates = {"Random Forest": rf_results[key], "XGBoost": xgb_results[key]}
        ranking = sorted(candidates, key=lambda name: candidates[name]["validation_metrics"]["MAE"])
        if selections[key] != ranking[0]:
            raise ValueError("Selection does not match the frozen validation comparison.")
        final_frame = pd.concat([config["train_df"], config["validation_df"]], ignore_index=True)
        if not set(final_frame.session_id).isdisjoint(set(config["test_df"].session_id)):
            raise ValueError("Test sessions overlap final fitting data.")
        features = final_frame[MODEL_FEATURES]
        if final_prep is None:
            final_features = features.copy()
            final_prep = make_preprocessor(scale_numeric=False)
            final_x = final_prep.fit_transform(final_features)
        elif not features.equals(final_features):
            raise ValueError("Forecast setups must share identical final fitting inputs.")
        for name, validation_result in candidates.items():
            model = make_tree_model(name, validation_result["params"])
            model.fit(final_x, final_frame.target_change.to_numpy())
            if hasattr(model, "feature_importances_"):
                importance = pd.DataFrame({"Feature": final_prep.get_feature_names_out(),
                                           "Importance": model.feature_importances_})
                importance["Model"], importance["Horizon_min"], importance["Approach"] = name, horizon, approach
                importance_frames.append(importance)
            test_prediction = forecast_future_co2(model, final_prep, config["test_df"], horizon, approach, histories)
            for split, frame, prediction in (
                ("Validation", config["validation_df"], validation_result["validation_predictions"]),
                ("Test", config["test_df"], test_prediction),
            ):
                metric_rows.append({"Horizon_min": horizon, "Approach": approach,
                    "Split": split, **result_row(name, frame, prediction),
                    "Validation Rank": ranking.index(name) + 1,
                    "Selected on validation": selections[key] == name})
                exported = frame[["session_id", "time", "Actual"]].copy()
                exported["Predicted"] = np.asarray(prediction)
                exported["Model"], exported["Split"] = name, split
                exported["Horizon_min"], exported["Approach"] = horizon, approach
                prediction_frames.append(exported)
    return {"metadata": prepared["metadata"], "selected_models": selections,
        "metrics": pd.DataFrame(metric_rows), "predictions": pd.concat(prediction_frames, ignore_index=True),
        "feature_importance": pd.concat(importance_frames, ignore_index=True) if importance_frames else pd.DataFrame()}


def experiment_run_dir(project):
    """Create the shared output directory beneath the notebook's chosen project."""
    run_dir = Path(project) / "runs" / EXPERIMENT_NAME
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def load_prepared(run_dir):
    """Load preparation and reject incompatible helper versions or features."""
    import joblib
    prepared = joblib.load(Path(run_dir) / "tree_session_prepared.joblib")
    check_prepared(prepared)
    return prepared


def run_tree_configurations(kind, suggest_params, prepared, output_path):
    """Tune each setup independently and save the existing validation artifact."""
    import joblib
    results = {}
    for key, config in prepared["configurations"].items():
        print(f"{kind}:", key)
        results[key] = tune_and_validate(kind, suggest_params, config, prepared["history_by_session"])
        print(pd.DataFrame([results[key]["validation_metrics"]]).to_string(index=False))
    joblib.dump({"metadata": prepared["metadata"], "configurations": results}, output_path, compress=3)
    return results
