# KC CO₂ — separate, linked experiment notebooks

## Run in Google Colab
1. Extract this ZIP and upload the folder to GitHub, or open the notebooks directly in Colab. No folder or helper upload to Drive is required: notebook 00 creates its Drive project folder and shared helper automatically.
2. Open `00_Data_Preparation.ipynb` with Colab. Run from top to bottom. Upload `KC_CO2_All_Real_Sessions_2026-10-11.zip` when prompted. Data is not included in this code package.
3. Run `01_Random_Forest.ipynb` and `02_XGBoost.ipynb`. Each tunes direct and recursive forecasts at 10 and 5 minutes, 30 trials each (120 trials per notebook).
4. Run `03_GRU.ipynb` and `04_LSTM.ipynb`, preferably with a Colab GPU. Each tunes direct forecasts at 10 and 5 minutes, 30 trials each (60 trials per notebook). No neural recursive experiments are added.
5. Run `05_Combined_Results.ipynb`. It reads all saved predictions and prints source-specific, source-weighted, and ordinary pooled MAE/RMSE/R², plus persistence comparisons and a tree comparison chart.

You may run model notebooks in any order after preparation. They share the same `RUN_DIR` on Drive, not notebook memory. Keep all outputs for one experiment under that directory. For a new experiment, change RUN_DIR in all notebooks. If you rerun preparation, rerun all model notebooks: the results notebook prevents mixing different preparation runs.

### Files passed between notebooks
- Preparation → `runs/real_sessions_v1/prepared.joblib`, `preparation.json`, `split_manifest.csv`, `persistence_predictions.csv.gz`.
- Each model → model folder with `metrics.csv`, `predictions.csv.gz`, 30-trial histories, selected settings, fitted models, package versions and study/refit times.
- Combined results → `per_source_results.csv`, `pooled_results.csv`, `source_weighted_results.csv`, `persistence_comparison.csv`, `tree_methods_by_horizon.png`.
- Section 2 of `00_Data_Preparation.ipynb` contains the editable source for every shared function and setting. Its `%%writefile` cell generates `kc_common.py` on Drive, and the next cell imports it. Model notebooks import that generated helper. The ZIP does not need a separately maintained Python helper.

## Which original is being reproduced?
`reference/KC_CO2_Four_Model_Comparison_Colab.ipynb` is the earlier all-source four-model comparison. Its cleaning, minute sampling, feature definitions, manifest splits, source weights, trial caps, tree settings, neural architecture and early stopping are retained.
`reference/Attached_Final_Session_Split.ipynb` is the uploaded style reference. It is a different experiment: only direct 10-minute trees, a shuffled session split, different features/search ranges, and train-plus-validation final refitting. Those methodological differences are NOT silently imported into the earlier all-source comparison. The original reference notebook also contains a file-deletion cell; it is archival, not part of the run instructions.

### Deliberate additions
- GRU and LSTM at 5 minutes (the earlier notebook ran them at 10 minutes only).
- Per-row prediction exports, source-weighted RMSE and R², and saved handoffs between notebooks.
- Overall permutation importance for both tree models, using the earlier validation-weighted method (previously plotted for XGBoost only).
- Test display label shortened to Test, with its previously examined status explained.

### Important reproduction details
- 50% Local, 25% UPC and 25% Slovenia weights affect BOTH training losses and trial validation MAE in the original comparison. Ordinary ALL metrics are unweighted by source.
- Optuna tunes on capped source-stratified samples; final models fit all training rows with selected settings. Full validation and test rows are scored afterward. No train+validation refit occurs here.
- Validation decides the neural best epoch during tuning. Final neural refits use that epoch count without further early stopping.
- 5- and 10-minute runs use identical origin rows, restricted to origins with the full 10-minute future available.
- The split is preserved from the dataset manifest, not freshly randomized. Counts depend on the actual archive and cleaning. Read the printed counts; do not assume historical counts or paste historical results into new output.
- GPU/library differences can change scores even with the same seed. These notebooks are reruns, not a guarantee of identical printed decimals.
- All-source training with source-specific evaluation does not mean three independently trained models.
- Only real recorded data belong in the real experiment. Generated data are not independent validation/test sessions.
- Study times are Colab tuning/refit times, not ESP32 inference benchmarks.

No completed training results are fabricated or bundled. See `VALIDATION.md` for checks performed on this code package.

## Updating an existing GitHub/Drive setup
Replace the six numbered notebooks and this README with the updated copies. The old standalone `kc_common.py` in GitHub can be deleted: notebook 00 is now the source of truth. The old Drive copy is overwritten when section 2 runs. Start with notebook 00, then rerun the four model notebooks and notebook 05. Use a new RUN_DIR in all notebooks to preserve previous experiment outputs.
