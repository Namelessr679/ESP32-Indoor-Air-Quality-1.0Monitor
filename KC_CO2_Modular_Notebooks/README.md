# CO₂ forecasting notebooks

This project predicts classroom CO₂ five and ten minutes ahead using only locally recorded sensor sessions from one shared Google Drive folder. Each CSV is one recording session. All models use the same prepared sessions, features and split assignments. Keep the notebook layout, shared helper, experiment settings and saved-file interfaces consistent across contributions.

## Project structure

| File | Responsibility |
| --- | --- |
| `00_Data_Preparation.ipynb` | Read session CSVs, clean data, calculate features, split whole sessions, fit training preprocessing and save preparation. |
| `01_Random_Forest.ipynb` | Tune Random Forest and export its selected parameters and validation results. |
| `02_XGBoost.ipynb` | Tune XGBoost, compare tree models on validation, freeze selection, perform final refits and export results. |
| `03_GRU.ipynb` | GRU entry point using the common preparation handoff. |
| `04_LSTM.ipynb` | LSTM entry point using the common preparation handoff. |
| `05_Combined_Results.ipynb` | Load model results, display comparisons and plots, and export the comparison table. |
| `kc_common.py` | Shared settings, features, splits, preprocessing, forecast rollout and metric functions. |

GRU and LSTM contain setup, preparation loading and empty model cells. Their score entries stay blank until results exist; missing results must never be represented as zero scores.

## Contribution rules

- Preserve these filenames, numbering, directory layout and responsibilities. Extend the designated model file rather than creating a parallel workflow or nested notebook folder.
- Keep shared logic in `kc_common.py`. Import it from notebooks; do not duplicate its functions or generate separate helper copies.
- Limit edits to the requested scope. Do not rewrite unrelated notebooks, change formatting across the project, or reorganize files as part of a model addition.
- Do not change features, targets, preprocessing, split rules, seeds, trial budgets, hyperparameter ranges, metrics, forecast semantics or final-refit policy without the project owner's explicit approval.
- Preserve handoff filenames, dictionary keys, feature names, model names and result-column names. An interface change requires explicit approval and coordinated updates to every producer and consumer.
- Fit preprocessing on training only during tuning. Keep whole sessions disjoint. Choose parameters and models using validation only, freeze selection before test evaluation, and never use test scores to retune or switch the selected model.
- Reuse the preparation handoff for every model. Do not create model-specific session splits or change evaluation rows to improve a score. Neural sequence construction must respect session boundaries and prediction-time data availability.
- Do not add occupancy inputs or require information unavailable during live prediction. Never read future sensor values to build forecast inputs.
- Read only the local recording-session CSVs directly inside the configured folder. Do not create, edit, move or delete source files, traverse subfolders, or add other data sources without explicit approval.
- Keep datasets, fitted models, predictions and experiment outputs out of Git. Keep notebook outputs cleared. Do not fabricate results or insert illustrative scores into result tables.
- Document functions and intended behavior directly. Avoid change-history notes, personal task assignments and comments about temporary development steps.
- Do not commit or push without the project owner's explicit instruction.

## Run in Google Colab

1. Use the notebooks and `kc_common.py` from the same repository revision. The setup imports a local helper when available; otherwise it downloads the helper from GitHub at `HELPER_REF`. Set a commit SHA for reproducible code versions. A distributed folder or ZIP must include the helper. In Colab, a local helper belongs in the Files pane beside the notebook runtime's working files.
2. Sign into a Google account with Viewer access to the [session data folder](https://drive.google.com/drive/folders/11FwkaIH_LhHWwaJsVcrCbBWwM1H32y-G).
3. Use the same `PROJECT` and experiment output location throughout the notebooks. The notebooks automatically process all four horizon/approach combinations; no forecast selector is required.
4. Run `00 → 01 → 02 → 05`. Model notebooks load preparation; reporting loads saved model results. Notebooks 03 and 04 use the same preparation interface.
5. Rerun the sequence after changing data, shared settings or code. Preparation identities must match across saved model results.

The authentication and Drive-mounting cells require Colab. A repository checkout provides the helper for VS Code, but local execution requires configuring Google authentication and storage paths.

## Dataset contract

The experiment uses a single collection of locally recorded sessions. Only CSV files directly inside the configured Drive folder are read. No separate source manifests or source-balancing weights are required. Folder and CSV names are unrestricted. Each CSV represents one recording session and must contain:

| Column | Meaning |
| --- | --- |
| `elapsed_seconds` | Elapsed seconds from the start of the recording (for example, 0, 30, 60) |
| `co2` | CO₂ concentration in ppm |
| `temp` | Temperature reading |
| `humidity` | Relative humidity reading |

Subfolders, Google Sheets and Drive shortcuts are not followed. Session identities use Drive file IDs, so filenames can be changed without changing the ordering used for splitting. Adding, deleting or replacing session files can change the split.

## Experiment contract

- Seed: **42**. Split: approximately **60% training / 20% validation / 20% test**, shuffled by whole session, with at least five usable sessions.
- Inputs: **23 numeric features**, defined in `kc_common.py`. Occupancy is not an input. Timestamp matching uses the configured 30-second tolerances.
- Forecast setups: **5-minute direct, 5-minute recursive, 10-minute direct and 10-minute recursive**, run automatically. Direct forecasts learn the change at the requested horizon; recursive forecasts learn one-minute changes and roll forward five or ten steps.
- Every setup uses identical eligible forecast origins and the same session assignments. Origins require observed targets at one, five and ten minutes, along with valid feature history. This makes horizon and approach comparisons use matching rows.
- Recursive forecasts update predicted CO₂ history, lags, slopes and rolling statistics. Temperature and humidity remain fixed at their latest observed values.
- Tuning: **30 Optuna trials per model per setup**: 120 for RF and 120 for XGBoost, **240 total**. Parameter ranges are defined in the model notebooks; the objective is unweighted validation MAE.
- Evaluation: MAE and RMSE in ppm, plus R². Validation uses training-only fits. Final tree models refit on training plus validation before test evaluation.
- RF/XGBoost model selection is frozen separately for each of the four setups using validation MAE before any test scoring. Combined reporting preserves those selections.
- Final combined tables explicitly print **MAE, RMSE and R2** for validation and test, with horizon and approach labels. The exported CSV contains the same values; `R2` denotes R².

## Shared execution

Input features and observed training targets are built separately; recursive inference only rebuilds input features. All setups share one training-fitted tree preprocessor and cached input matrices. Final refits share a separate preprocessor fitted on training plus validation. Configuration data frames and target arrays remain specific to each horizon and approach. Treat the shared preprocessor and matrices as read-only; do not refit or mutate them in model cells.

RF and XGBoost use a shared configuration runner while keeping their search spaces in their own notebooks. Each notebook retains its standalone helper bootstrap and explicit Colab Drive mount. GRU and LSTM remain preparation-loading scaffolds.

Any helper edit changes its fingerprint, including refactoring or comment changes. Rerun 00 → 01 → 02 → 05 using the matching helper after edits; existing preparation is deliberately rejected.

## Saved-file interfaces

Each runner uses their own Drive. All four setups belong to one experiment folder, with horizon and approach recorded in configuration keys and result rows:

`KC_CO2_Modular_Notebooks/runs/local_sessions_5_10_all_approaches_v1`

| Artifact | Producer | Consumers |
| --- | --- | --- |
| `tree_session_prepared.joblib` | 00 | 01, 02, 03, 04 |
| `preparation_metadata.joblib` | 00 | 02, 05 |
| `rf_validation.joblib` | 01 | 02 |
| `xgb_validation.joblib` | 02 | Validation analysis |
| `tree_results.joblib` | 02 | 05 |
| `combined_results.csv` | 05 | Analysis and reporting |

Preparation contains `metadata`, `configurations` and `history_by_session`. Configuration keys are `5min_direct`, `5min_recursive`, `10min_direct` and `10min_recursive`. Each configuration contains its `horizon`, `approach`, `train_df`, `validation_df`, `test_df`, training-fitted `tree_preprocessor`, `X_train_tree`, `X_validation_tree` and `y_train`.

Metadata records `schema_version`, `run_id`, `horizons`, `approaches`, `data_folder_id`, `features`, `train_ids`, `validation_ids`, `test_ids`, `seed`, `trials` and `helper_sha256`. Consumers reject mismatched preparation or helper versions.

RF and XGBoost validation artifacts contain `metadata` and `configurations`. Each setup stores `params`, `validation_predictions`, `validation_metrics` and `trial_history`. Tree results contain `metadata`, `selected_models`, `metrics`, `predictions` and `feature_importance`.

Metric rows use `Horizon_min`, `Approach`, `Model`, `Split`, `MAE`, `RMSE`, `R2`, `Validation Rank` and `Selected on validation`. Reporting adds `Status`. Prediction rows use `session_id`, `time`, `Actual`, `Predicted`, `Model`, `Split`, `Horizon_min` and `Approach`. The selected-model dictionary has one entry per configuration key. Model-specific feature importance is recorded per horizon and approach.

Neural result rows must use matching preparation, forecast approach, horizon, split roles and metric meanings. Do not change the frozen tree selection when adding result rows. A unified cross-family selection policy requires an explicitly approved change before test evaluation.

## Checks before sharing

Check notebook structure, Python syntax, imports and producer/consumer compatibility. Verify direct and recursive logic without future-data leakage, reject mismatched preparation identities, and confirm source access is read-only. Record which checks were actually run; syntax checks alone do not establish that Colab authentication or a full training run succeeds. Training and experiment runs require an explicit request.

CSV `elapsed_seconds` values are numeric elapsed seconds. Only `elapsed_seconds`, `co2`, `temp` and `humidity` are read as raw inputs; other CSV columns are ignored. Room is not used or encoded. Internally they are represented relative to 1970-01-01 solely for time-window calculations; this is not the recording date. `hour_of_day` is excluded because no clock time is supplied. The existing `session_elapsed_minutes` feature remains measured in minutes from the first usable reading. Saved prediction times use the internal time index.
