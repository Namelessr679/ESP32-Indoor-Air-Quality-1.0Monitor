# CO₂ prediction model

The supplied prediction artifact is checked in with this filename:

`co2_model.joblib`

Its location from the repository root is:

`hardware/models/co2_model.joblib`

The launcher already references it in `config.example.yaml`:

```yaml
pipeline:
  model_path: models/co2_model.joblib
```

Keep the same setting in your local `config.yaml`. Relative paths are resolved
against the configuration file's directory, not the terminal's working directory.
The lowercase filename matters on case-sensitive systems.

This is the provided `rf_direct_5min (1).joblib`, renamed to match the launcher
configuration. It is a binary model artifact; do not open it as a text file.
Only load model files from a trusted source. No retraining is done by the launcher.

The HW-02 owner must implement loading this artifact and its required feature
preprocessing, and supply its exact dependency versions. The artifact records
scikit-learn 1.6.1; its saved pipeline expects 23 features, including
`session_elapsed_minutes`. Verify the full feature list and training setup with
the model owner before enabling prediction. Adding the file does not complete
HW-02 or enable automatic prediction while HW-02 and HW-03 are placeholders.
