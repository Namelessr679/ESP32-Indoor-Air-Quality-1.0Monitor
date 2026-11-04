"""Standalone LSTM adapter for the approved five-minute comparison protocol.

This module deliberately has no registration side effects. Run it from the
project root with ``python models/lstm_pipeline.py`` or import ``run`` from an
external comparison runner.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import pandas as pd
import tensorflow as tf
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.preprocessing import MinMaxScaler

from gru_lstm_5min_direct import (
    BATCH_SIZE,
    EPOCHS,
    HORIZON_MINUTES,
    HORIZON_STEPS,
    NN_FEATURES,
    RANDOM_STATE,
    SEQUENCE_LENGTH,
    build_model,
    build_sequences,
    split_segments,
)
from linear_regression_5min_local import (
    TEST_SESSIONS,
    TRAIN_SESSIONS,
    VALIDATION_SESSIONS,
    load_local_data,
    prepare_recordings,
)

SCHEMA_COLUMNS = [
    "model",
    "split",
    "dataset_id",
    "segment",
    "time",
    "target_time",
    "actual",
    "predicted",
    "error",
    "absolute_error",
]


def _partition(data: pd.DataFrame) -> dict[str, list[pd.DataFrame]]:
    partitions = {
        "train": split_segments(data[data["dataset_id"].isin(TRAIN_SESSIONS)]),
        "validation": split_segments(data[data["dataset_id"].isin(VALIDATION_SESSIONS)]),
        "test": split_segments(data[data["dataset_id"].isin(TEST_SESSIONS)]),
    }
    if not all(partitions.values()):
        raise ValueError("Every configured session split must contain at least one segment")
    return partitions


def _check_sequences(x_values: np.ndarray, y_values: np.ndarray) -> None:
    expected_shape = (SEQUENCE_LENGTH, len(NN_FEATURES))
    if x_values.ndim != 3 or x_values.shape[1:] != expected_shape:
        raise ValueError(
            f"Expected sequences with shape (n, {expected_shape[0]}, {expected_shape[1]}), "
            f"got {x_values.shape}"
        )
    if y_values.ndim != 1 or len(x_values) != len(y_values):
        raise ValueError("Sequence and target counts do not match")
    if not len(x_values):
        raise ValueError("No training sequences were generated")


def _inverse_co2(scaler: MinMaxScaler, values: np.ndarray) -> np.ndarray:
    return values * (scaler.data_max_[0] - scaler.data_min_[0]) + scaler.data_min_[0]


def _evaluate(
    model: tf.keras.Model,
    scaler: MinMaxScaler,
    frames: list[pd.DataFrame],
    split_name: str,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for frame in frames:
        values = frame[NN_FEATURES].astype(float).to_numpy()
        scaled = scaler.transform(values)
        for origin in range(SEQUENCE_LENGTH - 1, len(frame) - HORIZON_STEPS, HORIZON_STEPS):
            sequence = scaled[origin - SEQUENCE_LENGTH + 1 : origin + 1]
            prediction_scaled = model(sequence[None, :, :], training=False).numpy()[0, 0]
            predicted = float(_inverse_co2(scaler, np.asarray(prediction_scaled)))
            actual_row = frame.iloc[origin + HORIZON_STEPS]
            actual = float(actual_row["co2"])
            rows.append({
                "model": "LSTM",
                "split": split_name,
                "dataset_id": frame.iloc[origin]["dataset_id"],
                "segment": frame.iloc[origin]["segment"],
                "time": frame.iloc[origin]["time"],
                "target_time": actual_row["time"],
                "actual": actual,
                "predicted": predicted,
                "error": predicted - actual,
                "absolute_error": abs(predicted - actual),
            })
    return pd.DataFrame(rows, columns=SCHEMA_COLUMNS)


def _metrics(records: pd.DataFrame) -> dict[str, float]:
    if records.empty:
        return {"MAE": np.nan, "RMSE": np.nan, "R2": np.nan, "origin_count": 0}
    actual = records["actual"].to_numpy(dtype=float)
    predicted = records["predicted"].to_numpy(dtype=float)
    return {
        "MAE": float(mean_absolute_error(actual, predicted)),
        "RMSE": float(np.sqrt(mean_squared_error(actual, predicted))),
        "R2": float(r2_score(actual, predicted)) if len(records) > 1 else np.nan,
        "origin_count": int(len(records)),
    }


def _set_reproducible_seed() -> None:
    tf.keras.utils.set_random_seed(RANDOM_STATE)
    tf.config.experimental.enable_op_determinism()


def run(
    data: pd.DataFrame | None = None,
    artifact: Path | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Train or load the LSTM and return common-schema test records and metadata."""
    _set_reproducible_seed()
    prepared = prepare_recordings(load_local_data() if data is None else data)
    partitions = _partition(prepared)

    development = partitions["train"] + partitions["validation"]
    scaler = MinMaxScaler()
    scaler.fit(pd.concat(development)[NN_FEATURES].astype(float))

    if artifact is None:
        train_scaler = MinMaxScaler()
        train_scaler.fit(pd.concat(partitions["train"])[NN_FEATURES].astype(float))
        x_train, y_train = build_sequences(partitions["train"], train_scaler)
        _check_sequences(x_train, y_train)
        model = build_model("LSTM")
        model.fit(x_train, y_train, epochs=EPOCHS, batch_size=BATCH_SIZE, verbose=0)
        validation_scaler = train_scaler
    else:
        model = tf.keras.models.load_model(artifact)
        validation_scaler = scaler

    input_shape = tuple(model.input_shape[1:])
    expected_shape = (SEQUENCE_LENGTH, len(NN_FEATURES))
    if input_shape != expected_shape:
        raise ValueError(f"Artifact/model input shape {input_shape} does not match {expected_shape}")

    validation_records = _evaluate(
        model, validation_scaler, partitions["validation"], "validation"
    )

    if artifact is None:
        x_development, y_development = build_sequences(development, scaler)
        _check_sequences(x_development, y_development)
        model = build_model("LSTM")
        model.fit(x_development, y_development, epochs=EPOCHS, batch_size=BATCH_SIZE, verbose=0)

    test_records = _evaluate(model, scaler, partitions["test"], "test")
    records = pd.concat([validation_records, test_records], ignore_index=True)
    evaluated_test_sessions = sorted(test_records["dataset_id"].dropna().unique().tolist())
    omitted_test_sessions = sorted(set(TEST_SESSIONS) - set(evaluated_test_sessions))
    metadata = {
        "model": "LSTM",
        "protocol": "session-based 6/2/2 direct forecast",
        "train_sessions": TRAIN_SESSIONS,
        "validation_sessions": VALIDATION_SESSIONS,
        "test_sessions": TEST_SESSIONS,
        "evaluated_test_sessions": evaluated_test_sessions,
        "omitted_test_sessions": omitted_test_sessions,
        "test_coverage_complete": not omitted_test_sessions,
        "horizon_minutes": HORIZON_MINUTES,
        "horizon_steps": HORIZON_STEPS,
        "sample_seconds": 10,
        "sequence_length": SEQUENCE_LENGTH,
        "features": NN_FEATURES,
        "epochs": EPOCHS,
        "batch_size": BATCH_SIZE,
        "random_state": RANDOM_STATE,
        "artifact": str(artifact) if artifact else None,
        "validation_metrics": _metrics(validation_records),
        "test_metrics": _metrics(test_records),
    }
    return records, metadata


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate the LSTM in the common CO2 comparison schema.")
    parser.add_argument("--predictions", type=Path, help="CSV path for validation and test prediction records")
    parser.add_argument("--summary", type=Path, help="JSON path for metrics, settings, and metadata")
    parser.add_argument("--artifact", type=Path, help="Optional compatible Keras LSTM artifact")
    args = parser.parse_args()

    records, metadata = run(artifact=args.artifact)
    if args.predictions:
        args.predictions.parent.mkdir(parents=True, exist_ok=True)
        records.to_csv(args.predictions, index=False)
    if args.summary:
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        args.summary.write_text(json.dumps(metadata, indent=2, allow_nan=True), encoding="utf-8")
    print(json.dumps(metadata, indent=2, allow_nan=True))


if __name__ == "__main__":
    main()