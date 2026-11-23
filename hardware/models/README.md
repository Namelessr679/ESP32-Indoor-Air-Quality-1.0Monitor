# Put the CO₂ model here

Copy your final trained model into this folder with this exact filename:

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

This README keeps the folder present in Git. There is intentionally no empty
`.joblib` file: an empty file would not be a valid model. Fitted models are ignored
by Git; copy yours locally after checking out the branch. No retraining is done by
the launcher.

The HW-02 owner must implement loading this trusted artifact and any preprocessing,
and supply its exact dependency versions. Adding the file does not complete HW-02
or enable automatic prediction while the three HW modules remain placeholders.
