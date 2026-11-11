"""GRU/LSTM neural adapters for the shared CO2 experiment handoff."""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import optuna
import pandas as pd
import torch
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.preprocessing import StandardScaler
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

ROOT = Path(__file__).resolve().parents[2]
HELPER_DIR = ROOT / "KC_CO2_Modular_Notebooks"
sys.path.insert(0, str(HELPER_DIR)) if str(HELPER_DIR) not in sys.path else None

from kc_common import MODEL_FEATURES, RANDOM_STATE, SETUPS, check_prepared, engineer_features, load_prepared

SEQUENCE_LENGTH = 11
SENSOR_FEATURES = ["co2", "temp", "humidity"]
MAX_SEQUENCE_GAP_SECONDS = 30
N_TRIALS = 30
MAX_EPOCHS = 16
PATIENCE = 3
RESULT_KEYS = ["Horizon_min", "Approach", "Model", "Split"]
PREPARATION_IDENTITY_KEYS = [
    "schema_version", "run_id", "horizons", "approaches", "data_folder_id",
    "features", "train_ids", "validation_ids", "test_ids", "seed", "trials",
    "helper_sha256",
]


class RecurrentRegressor(nn.Module):
    def __init__(self, kind: str, static_size: int, hidden: int, layers: int, dropout: float):
        super().__init__()
        recurrent = nn.GRU if kind == "GRU" else nn.LSTM
        self.recurrent = recurrent(len(SENSOR_FEATURES), hidden, layers, batch_first=True,
                                   dropout=dropout if layers > 1 else 0.0)
        self.head = nn.Sequential(nn.Linear(hidden + static_size, 32), nn.ReLU(), nn.Linear(32, 1))

    def forward(self, sequence: torch.Tensor, static: torch.Tensor) -> torch.Tensor:
        output, _ = self.recurrent(sequence)
        return self.head(torch.cat((output[:, -1], static), dim=1)).squeeze(1)


def _seed() -> None:
    random.seed(RANDOM_STATE)
    np.random.seed(RANDOM_STATE)
    torch.manual_seed(RANDOM_STATE)


def _sampling(histories: dict[Any, pd.DataFrame]) -> dict[str, float]:
    intervals = []
    for frame in histories.values():
        values = pd.to_datetime(frame["time"]).sort_values().diff().dt.total_seconds().dropna()
        intervals.extend(values[values > 0].tolist())
    if not intervals:
        raise ValueError("No positive sampling intervals found")
    median = float(np.median(intervals))
    return {"median_seconds": median, "five_minute_steps": 300 / median, "ten_minute_steps": 600 / median}


def _sequence(history: pd.DataFrame, origin: pd.Timestamp) -> np.ndarray | None:
    wanted = pd.DataFrame({"wanted": [origin - pd.Timedelta(minutes=i) for i in range(10, -1, -1)]})
    source = history[["time", *SENSOR_FEATURES]].sort_values("time")
    matched = pd.merge_asof(wanted, source, left_on="wanted", right_on="time", direction="nearest",
                            tolerance=pd.Timedelta(seconds=MAX_SEQUENCE_GAP_SECONDS))
    if matched[SENSOR_FEATURES].isna().any().any():
        return None
    return matched[SENSOR_FEATURES].to_numpy(dtype=np.float32)


def _validate_origin_keys(prepared_frame: pd.DataFrame, evaluated_frame: pd.DataFrame) -> None:
    expected = list(prepared_frame[["session_id", "time"]].itertuples(index=False, name=None))
    actual = list(evaluated_frame[["session_id", "time"]].itertuples(index=False, name=None))
    if actual != expected:
        raise ValueError("Neural predictions do not preserve the prepared evaluation origins")


def _arrays(frame: pd.DataFrame, histories: dict[Any, pd.DataFrame], partition_name: str):
    sequences, static, targets, rows = [], [], [], []
    for row in frame.itertuples(index=False):
        sequence = _sequence(histories[row.session_id], row.time)
        if sequence is None:
            raise ValueError(
                f"Missing 11-point sequence for {partition_name} origin "
                f"({row.session_id}, {row.time}); rerun preparation with compatible histories"
            )
        values = row._asdict()
        sequences.append(sequence)
        static.append([values[name] for name in MODEL_FEATURES])
        targets.append(float(values["target_change"]))
        rows.append(values)
    if not sequences:
        raise ValueError("No usable neural sequence origins")
    evaluated = pd.DataFrame(rows)
    _validate_origin_keys(frame, evaluated)
    return np.asarray(sequences, np.float32), np.asarray(static, np.float32), np.asarray(targets, np.float32), evaluated


def _scalers(sequences: np.ndarray, static: np.ndarray):
    return (StandardScaler().fit(sequences.reshape(-1, 3)), StandardScaler().fit(static))


def _transform(sequences, static, sequence_scaler, static_scaler):
    shape = sequences.shape
    sequence = sequence_scaler.transform(sequences.reshape(-1, 3)).reshape(shape)
    return sequence.astype(np.float32), static_scaler.transform(static).astype(np.float32)


def _predict(model, sequences, static):
    model.eval()
    with torch.no_grad():
        return model(torch.from_numpy(sequences), torch.from_numpy(static)).numpy()


def _train(kind, train_x, train_static, target, validation_x, validation_static, validation_target, params, select):
    _seed()
    model = RecurrentRegressor(kind, train_static.shape[1], int(params["hidden"]), int(params["layers"]), float(params["dropout"]))
    optimizer = torch.optim.Adam(model.parameters(), lr=float(params["learning_rate"]), weight_decay=float(params["weight_decay"]))
    loader = DataLoader(TensorDataset(torch.from_numpy(train_x), torch.from_numpy(train_static), torch.from_numpy(target)),
                        batch_size=int(params["batch_size"]), shuffle=True)
    if not select:
        for _ in range(int(params["epochs"])):
            model.train()
            for sequence, static, values in loader:
                optimizer.zero_grad()
                loss = nn.functional.l1_loss(model(sequence, static), values)
                loss.backward()
                optimizer.step()
        return model, int(params["epochs"]), np.nan
    best_state, best_score, best_epoch, stale = None, float("inf"), 0, 0
    for epoch in range(int(params["epochs"])):
        model.train()
        for sequence, static, values in loader:
            optimizer.zero_grad()
            loss = nn.functional.l1_loss(model(sequence, static), values)
            loss.backward()
            optimizer.step()
        score = mean_absolute_error(validation_target, _predict(model, validation_x, validation_static))
        if score < best_score:
            best_state, best_score, best_epoch, stale = {k: v.detach().clone() for k, v in model.state_dict().items()}, float(score), epoch + 1, 0
        else:
            stale += 1
        if stale >= PATIENCE:
            break
    model.load_state_dict(best_state)
    return model, best_epoch, best_score


def _params(trial):
    return {"hidden": trial.suggest_categorical("hidden", [16, 32, 64]), "layers": trial.suggest_int("layers", 1, 2),
            "dropout": trial.suggest_float("dropout", 0.0, 0.3), "learning_rate": trial.suggest_float("learning_rate", 0.0003, 0.003, log=True),
            "weight_decay": trial.suggest_float("weight_decay", 1e-6, 0.001, log=True), "batch_size": trial.suggest_categorical("batch_size", [256, 512, 1024]), "epochs": MAX_EPOCHS}


def _metrics(actual, predicted):
    return {"MAE": float(mean_absolute_error(actual, predicted)), "RMSE": float(np.sqrt(mean_squared_error(actual, predicted))),
            "R2": float(r2_score(actual, predicted)) if len(actual) > 1 else np.nan}


def _validate_rows(metrics: pd.DataFrame, kind: str, approaches: set[str]) -> None:
    if metrics.duplicated(RESULT_KEYS).any():
        raise ValueError("Duplicate neural result keys")
    expected = {(h, a, kind, s) for h in (5, 10) for a in approaches for s in ("Validation", "Test")}
    actual = set(metrics[RESULT_KEYS].itertuples(index=False, name=None))
    if actual != expected:
        raise ValueError(f"Incomplete neural result keys: {actual}")


def _check_output(path: Path) -> None:
    try:
        path.resolve().relative_to(ROOT)
    except ValueError:
        return
    raise ValueError("Generated artifacts must be stored outside the Git checkout")


def _validate_preparation_identity(saved_metadata: dict[str, Any], current_metadata: dict[str, Any]) -> None:
    mismatches = [
        key for key in PREPARATION_IDENTITY_KEYS
        if saved_metadata.get(key) != current_metadata.get(key)
    ]
    if mismatches:
        raise ValueError(
            "Existing direct results use a different preparation "
            f"({', '.join(mismatches)}). Rerun direct forecasting before recursive forecasting."
        )


def _recursive_prediction(model, sequence_scaler, static_scaler, history, origin, horizon):
    synthetic = history.loc[history.time <= origin.time].copy()
    current = float(origin.CO2_now)
    static = origin[MODEL_FEATURES].to_numpy(dtype=float)
    for step in range(horizon):
        sequence = _sequence(synthetic, origin.time + pd.Timedelta(minutes=step))
        if sequence is None:
            raise ValueError("Incomplete recursive sequence history")
        sequence_x, static_x = _transform(sequence[None], static[None], sequence_scaler, static_scaler)
        current += float(_predict(model, sequence_x, static_x)[0])
        if step == horizon - 1:
            break
        next_row = synthetic.iloc[-1].copy()
        next_row.time = origin.time + pd.Timedelta(minutes=step + 1)
        next_row.co2 = current
        synthetic = pd.concat([synthetic, next_row.to_frame().T], ignore_index=True)
        synthetic.time = pd.to_datetime(synthetic.time)
        features = engineer_features(synthetic).iloc[[-1]].copy()
        features["initial_CO2"] = synthetic.co2.iloc[0]
        features["CO2_change_from_start"] = current - synthetic.co2.iloc[0]
        features["session_elapsed_minutes"] = (features.time - synthetic.time.iloc[0]).dt.total_seconds() / 60
        static = features[MODEL_FEATURES].iloc[0].to_numpy(dtype=float)
    return current


def _recursive_predictions(model, sequence_scaler, static_scaler, rows, histories, horizon):
    return np.asarray([_recursive_prediction(model, sequence_scaler, static_scaler, histories[row.session_id], row, horizon)
                       for _, row in rows.iterrows()], dtype=float)


def _run(kind: str, run_dir: Path, output_dir: Path | None, approach: str, trials: int):
    _seed()
    run_dir, output_dir = Path(run_dir), Path(output_dir or Path(run_dir) / kind)
    output_dir.mkdir(parents=True, exist_ok=True)
    _check_output(output_dir)
    prepared = load_prepared(run_dir)
    check_prepared(prepared)
    histories, sampling = prepared["history_by_session"], _sampling(prepared["history_by_session"])
    metadata = {**prepared["metadata"], "model": kind, "sequence_length": SEQUENCE_LENGTH, "sampling": sampling}
    rows, predictions, artifacts = [], [], {}
    for horizon in (5, 10):
        config = prepared["configurations"][f"{horizon}min_{approach}"]
        train = _arrays(config["train_df"], histories, "train")
        validation = _arrays(config["validation_df"], histories, "validation")
        test = _arrays(config["test_df"], histories, "test")
        seq_scaler, static_scaler = _scalers(train[0], train[1])
        train_x, train_s = _transform(train[0], train[1], seq_scaler, static_scaler)
        val_x, val_s = _transform(validation[0], validation[1], seq_scaler, static_scaler)
        study = optuna.create_study(direction="minimize", sampler=optuna.samplers.TPESampler(seed=RANDOM_STATE))
        def objective(trial):
            params = _params(trial)
            model, epoch, _ = _train(kind, train_x, train_s, train[2], val_x, val_s, validation[2], params, True)
            trial.set_user_attr("best_epoch", epoch)
            if approach == "direct":
                prediction = validation[3].CO2_now.to_numpy() + _predict(model, val_x, val_s)
            else:
                prediction = _recursive_predictions(model, seq_scaler, static_scaler, validation[3], histories, horizon)
            return mean_absolute_error(validation[3].Actual, prediction)
        study.optimize(objective, n_trials=trials, show_progress_bar=False)
        params = dict(study.best_params)
        params["epochs"] = int(study.best_trial.user_attrs["best_epoch"])
        validation_model, _, _ = _train(kind, train_x, train_s, train[2], val_x, val_s, validation[2], params, False)
        final_frame = pd.concat([config["train_df"], config["validation_df"]], ignore_index=True)
        final = _arrays(final_frame, histories, "final training")
        final_seq_scaler, final_static_scaler = _scalers(final[0], final[1])
        final_x, final_s = _transform(final[0], final[1], final_seq_scaler, final_static_scaler)
        final_model, _, _ = _train(kind, final_x, final_s, final[2], None, None, None, params, False)
        if approach == "direct":
            val_prediction = validation[3].CO2_now.to_numpy() + _predict(validation_model, val_x, val_s)
            test_x, test_s = _transform(test[0], test[1], final_seq_scaler, final_static_scaler)
            test_prediction = test[3].CO2_now.to_numpy() + _predict(final_model, test_x, test_s)
        else:
            val_prediction = _recursive_predictions(validation_model, seq_scaler, static_scaler, validation[3], histories, horizon)
            test_prediction = _recursive_predictions(final_model, final_seq_scaler, final_static_scaler, test[3], histories, horizon)
        for split, frame, prediction in (("Validation", validation[3], val_prediction), ("Test", test[3], test_prediction)):
            actual = frame.Actual.to_numpy(dtype=float)
            rows.append({"Horizon_min": horizon, "Approach": approach, "Model": kind, "Split": split, **_metrics(actual, prediction), "Validation Rank": 1, "Selected on validation": True})
            export = frame[["session_id", "time"]].copy(); export["Actual"], export["Predicted"] = actual, prediction
            export["Model"], export["Split"], export["Horizon_min"], export["Approach"] = kind, split, horizon, approach
            export["run_id"] = metadata["run_id"]; predictions.append(export)
        artifact = output_dir / f"{horizon}min_{approach}.pt"
        torch.save({"metadata": metadata, "params": params, "state_dict": final_model.state_dict(), "sequence_scaler": final_seq_scaler, "static_scaler": final_static_scaler, "sequence_length": SEQUENCE_LENGTH, "feature_order": MODEL_FEATURES.copy(), "model": kind}, artifact)
        artifacts[f"{horizon}min_{approach}"] = str(artifact)
    result = {"metadata": metadata, "metrics": pd.DataFrame(rows), "predictions": pd.concat(predictions, ignore_index=True), "feature_importance": pd.DataFrame(), "artifacts": artifacts}
    _validate_rows(result["metrics"], kind, {approach})
    path = output_dir / f"{kind.lower()}_results.joblib"
    if approach == "recursive" and path.is_file():
        old = joblib.load(path)
        _validate_preparation_identity(old.get("metadata", {}), metadata)
        old_metrics = old["metrics"].loc[old["metrics"].Approach.eq("direct")]
        old_predictions = old["predictions"].loc[old["predictions"].Approach.eq("direct")]
        result["metrics"] = pd.concat([old_metrics, result["metrics"]], ignore_index=True)
        result["predictions"] = pd.concat([old_predictions, result["predictions"]], ignore_index=True)
        result["artifacts"] = {**old.get("artifacts", {}), **result["artifacts"]}
        _validate_rows(result["metrics"], kind, {"direct", "recursive"})
    joblib.dump(result, path, compress=3)
    result["metrics"].to_csv(output_dir / f"{kind.lower()}_results.csv", index=False)
    result["predictions"].to_csv(output_dir / f"{kind.lower()}_predictions.csv.gz", index=False)
    return result


def run_direct(kind: str, run_dir: Path, output_dir: Path | None = None, trials: int = N_TRIALS):
    return _run(kind, run_dir, output_dir, "direct", trials)


def run_recursive(kind: str, run_dir: Path, output_dir: Path | None = None, trials: int = N_TRIALS):
    return _run(kind, run_dir, output_dir, "recursive", trials)


def run(run_dir: Path, output_dir: Path | None = None):
    return run_direct("GRU", run_dir, output_dir)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    print(run_direct("GRU", args.run_dir, args.output_dir)["metrics"].to_string(index=False))