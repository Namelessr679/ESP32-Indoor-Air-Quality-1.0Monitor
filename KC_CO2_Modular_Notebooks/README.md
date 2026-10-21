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


