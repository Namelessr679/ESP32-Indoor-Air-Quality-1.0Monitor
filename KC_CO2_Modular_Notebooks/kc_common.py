"""Shared features and scoring. See 00_Data_Preparation.ipynb and README.md."""

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

SEED = 42
N_TRIALS = 30
SOURCE_SHARE = {"Local": 0.50, "UPC": 0.25, "Slovenia": 0.25}
TRIAL_TRAIN_CAP = {"Local": 100000, "UPC": 100000, "Slovenia": 12000}
TRIAL_VAL_CAP = {"Local": 100000, "UPC": 4000, "Slovenia": 4000}
NUM = ["CO2_now", "Temp_now", "Humidity_now"]
for m in (1, 5, 10):
    NUM += [f"CO2_prev_{m}min", f"CO2_change_{m}min", f"CO2_slope_{m}min"]
for m in (5, 10):
    NUM += [f"CO2_mean_{m}min", f"CO2_std_{m}min"]
NUM += [
    "Temp_mean_5min",
    "Humidity_mean_5min",
    "Temp_slope_5min",
    "Humidity_slope_5min",
    "initial_CO2",
    "CO2_change_from_start",
    "session_elapsed_minutes",
    "people",
    "hour_of_day",
]
FEATURES = NUM + ["room"]


def make_features(c, t, h, initial, elapsed, people, times, room):
    d = {"CO2_now": c[:, -1], "Temp_now": t[:, -1], "Humidity_now": h[:, -1]}
    for m in (1, 5, 10):
        z = c[:, -m - 1 :]
        x = np.arange(m + 1) - m / 2
        d[f"CO2_prev_{m}min"] = c[:, -m - 1]
        d[f"CO2_change_{m}min"] = c[:, -1] - c[:, -m - 1]
        d[f"CO2_slope_{m}min"] = z @ x / (x @ x)
    for m in (5, 10):
        d[f"CO2_mean_{m}min"] = c[:, -m:].mean(axis=1)
        d[f"CO2_std_{m}min"] = c[:, -m:].std(axis=1, ddof=1)
    for label, z in [("Temp", t), ("Humidity", h)]:
        d[f"{label}_mean_5min"] = z[:, -5:].mean(axis=1)
        d[f"{label}_slope_5min"] = z[:, -6:] @ (np.arange(6) - 2.5) / 17.5
    ts = pd.DatetimeIndex(times)
    d.update(
        initial_CO2=initial,
        CO2_change_from_start=c[:, -1] - initial,
        session_elapsed_minutes=elapsed,
        people=people,
        hour_of_day=ts.hour + ts.minute / 60,
        room=room,
    )
    return pd.DataFrame(d)[FEATURES]


def role_group(s):
    return np.select(
        [
            s.eq("Training"),
            s.isin(["Validation", "Public Validation check"]),
            s.isin(["Test", "Public Test check"]),
        ],
        ["Training", "Validation", "Test"],
        default="Invalid",
    )


def balanced_weights(s):
    counts = s.value_counts()
    shares = {k: SOURCE_SHARE[k] for k in counts.index}
    assert len(shares) == 3 and set(shares) == set(SOURCE_SHARE)
    return s.map({k: shares[k] / counts[k] for k in shares}).to_numpy(dtype=np.float64)


def score_sources(actual, pred, source):
    return sum(
        (
            SOURCE_SHARE[k] * mean_absolute_error(actual[source == k], pred[source == k])
            for k in SOURCE_SHARE
        )
    )


def sample_per_source(df, cap, seed):
    rng = np.random.default_rng(seed)
    out = []
    for source, g in df.groupby("source", sort=True):
        ids = g.index.to_numpy()
        out.append(rng.choice(ids, min(len(ids), cap[source]), replace=False))
    return np.sort(np.concatenate(out))


def metrics(actual, predicted, weights=None):
    return {
        "MAE": mean_absolute_error(actual, predicted, sample_weight=weights),
        "RMSE": mean_squared_error(actual, predicted, sample_weight=weights) ** 0.5,
        "R2": r2_score(actual, predicted, sample_weight=weights),
    }
