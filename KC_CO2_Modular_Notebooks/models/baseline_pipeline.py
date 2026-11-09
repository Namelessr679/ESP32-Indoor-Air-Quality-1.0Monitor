"""Standalone persistence and Linear Regression baseline adapter.

Run with a prepared experiment handoff::

    python KC_CO2_Modular_Notebooks/models/baseline_pipeline.py \
        --run-dir KC_CO2_Modular_Notebooks/runs/local_sessions_5_10_all_approaches_v1

The adapter consumes the existing preparation contract and writes new baseline
artifacts beneath the selected run directory. It does not modify notebooks,
the shared helper, existing model artifacts, or saved results.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression


ROOT = Path(__file__).resolve().parents[2]
HELPER_DIR = ROOT / "KC_CO2_Modular_Notebooks"
if str(HELPER_DIR) not in sys.path:
    sys.path.insert(0, str(HELPER_DIR))

from kc_common import (  # noqa: E402
    MODEL_FEATURES,
    SETUPS,
    forecast_future_co2,
    load_prepared,
    make_preprocessor,
    metrics_from_future_co2,
    model_output_to_future_co2,
    setup_key,
)


AVAILABLE_METHODS = ("Persistence", "Linear Regression")
MISSING_METHODS = ("Linear Trend",)
RUN_NAME = "baseline_pipeline"


def _fit_linear_regression(config: dict) -> tuple[LinearRegression, object]:
    preprocessor = make_preprocessor(scale_numeric=False)
    train = config["train_df"]
    features = preprocessor.fit_transform(train[MODEL_FEATURES])
    model = LinearRegression()
    model.fit(features, train["target_change"].to_numpy())
    return model, preprocessor


def _fit_final_linear_regression(config: dict) -> tuple[LinearRegression, object]:
    preprocessor = make_preprocessor(scale_numeric=False)
    training = pd.concat(
        [config["train_df"], config["validation_df"]],
        ignore_index=True,
    )
    features = preprocessor.fit_transform(training[MODEL_FEATURES])
    model = LinearRegression()
    model.fit(features, training["target_change"].to_numpy())
    return model, preprocessor


def _predict(
    method: str,
    model: LinearRegression | None,
    preprocessor: object | None,
    frame: pd.DataFrame,
    config: dict,
    histories: dict,
) -> np.ndarray:
    if method == "Persistence":
        return frame["CO2_now"].to_numpy(dtype=float)
    if method != "Linear Regression" or model is None or preprocessor is None:
        raise ValueError(f"Unsupported baseline method: {method}")
    if config["approach"] == "direct":
        changes = model.predict(preprocessor.transform(frame[MODEL_FEATURES]))
        return model_output_to_future_co2(frame, changes)
    return forecast_future_co2(
        model,
        preprocessor,
        frame,
        config["horizon"],
        config["approach"],
        histories,
    )


def _prediction_rows(
    method: str,
    split: str,
    config: dict,
    frame: pd.DataFrame,
    predicted: np.ndarray,
) -> pd.DataFrame:
    rows = frame[["session_id", "time", "Actual"]].copy()
    rows["Predicted"] = np.asarray(predicted, dtype=float)
    rows["Model"] = method
    rows["Split"] = split
    rows["Horizon_min"] = config["horizon"]
    rows["Approach"] = config["approach"]
    rows["Run"] = RUN_NAME
    return rows


def run(run_dir: Path, output_dir: Path | None = None) -> dict[str, object]:
    """Evaluate available baselines using the existing prepared handoff."""
    prepared = load_prepared(run_dir)
    output_dir = output_dir or run_dir / "baseline_results"
    output_dir.mkdir(parents=True, exist_ok=True)
    histories = prepared["history_by_session"]
    metric_rows: list[dict[str, object]] = []
    prediction_frames: list[pd.DataFrame] = []

    for key in (setup_key(*setup) for setup in SETUPS):
        config = prepared["configurations"][key]
        validation = config["validation_df"]
        test = config["test_df"]
        for method in AVAILABLE_METHODS:
            if method == "Linear Regression":
                validation_model, validation_preprocessor = _fit_linear_regression(config)
                final_model, final_preprocessor = _fit_final_linear_regression(config)
            else:
                validation_model = final_model = None
                validation_preprocessor = final_preprocessor = None

            validation_prediction = _predict(
                method, validation_model, validation_preprocessor,
                validation, config, histories,
            )
            test_prediction = _predict(
                method, final_model, final_preprocessor,
                test, config, histories,
            )
            for split, frame, prediction in (
                ("Validation", validation, validation_prediction),
                ("Test", test, test_prediction),
            ):
                metrics = metrics_from_future_co2(frame["Actual"], prediction)
                metric_rows.append({
                    "Horizon_min": config["horizon"],
                    "Approach": config["approach"],
                    "Model": method,
                    "Split": split,
                    "Run": RUN_NAME,
                    **metrics,
                })
                prediction_frames.append(
                    _prediction_rows(method, split, config, frame, prediction)
                )

    metrics_frame = pd.DataFrame(metric_rows)
    predictions_frame = pd.concat(prediction_frames, ignore_index=True)
    metrics_frame.to_csv(output_dir / "baseline_metrics.csv", index=False)
    predictions_frame.to_csv(output_dir / "baseline_predictions.csv", index=False)
    pd.DataFrame([
        {"method": method, "status": "available"}
        for method in AVAILABLE_METHODS
    ] + [
        {"method": method, "status": "unavailable"}
        for method in MISSING_METHODS
    ]).to_csv(output_dir / "baseline_method_metadata.csv", index=False)
    (output_dir / "baseline_metadata.json").write_text(
        json.dumps({
            "run": RUN_NAME,
            "methods": list(AVAILABLE_METHODS),
            "missing_methods": list(MISSING_METHODS),
            "setups": [setup_key(*setup) for setup in SETUPS],
            "source_run": str(run_dir),
        }, indent=2),
        encoding="utf-8",
    )
    return {
        "metadata": prepared["metadata"],
        "metrics": metrics_frame,
        "predictions": predictions_frame,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    result = run(args.run_dir, args.output_dir)
    print(result["metrics"].to_string(index=False))
    print("Unavailable baseline implementation: " + ", ".join(MISSING_METHODS))


if __name__ == "__main__":
    main()