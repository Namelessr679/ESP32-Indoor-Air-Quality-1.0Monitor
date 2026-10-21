# Validation performed

- All six workflow notebooks passed notebook-schema validation and Python syntax parsing. Relative notebook/document links resolve inside the package.
- Ran the original feature preparation logic against the complete real-session archive for both horizons. Both produced training 237,944 rows, validation 80,392 rows, test 73,979 rows.
- Validation by source: Local 165, UPC 1,054, Slovenia 79,173. Test: Local 70, UPC 1,037, Slovenia 72,872. These match the earlier results supplied in the conversation.
- Checked five- and ten-minute origin rows are identical.
- Ran small end-to-end smoke tests on real rows for RF and XGBoost direct/recursive at both horizons, and GRU and LSTM direct at both horizons. Testing used one trial and at most two neural epochs, only to validate code paths; these are not research experiments or benchmark results.
- Tested prediction exports and their readback through the actual combined-results cells, including run identity and matching evaluation rows.
- Independently checked source-weighted MAE, RMSE and R² formulas against the exported smoke-test predictions.
- The delivered six notebooks contain no execution outputs and still use 30 trials per setup, with up to 16 neural epochs and original early stopping. The complete 360-trial experiment was not run.
- Colab Drive mounting and browser upload prompts require your Colab session. GPU reproducibility and full-duration Colab resource usage were not tested here. Pinning scikit-learn keeps the prepared preprocessor consistent across notebook sessions; recorded package versions aid later review.

Original reference notebooks are unchanged archival copies and are not part of the six-notebook run order.

## Shared-helper relocation update
All shared code is now embedded in an editable `%%writefile` cell in notebook 00. Executed that cell in a fresh temporary directory, imported the generated module, and checked its Python syntax tree matches the previous helper exactly. All six notebooks passed schema and code syntax checks after the update. This changes code location and setup instructions, not features, split assignments, weights or model settings. Full model tuning was not repeated for this relocation.
