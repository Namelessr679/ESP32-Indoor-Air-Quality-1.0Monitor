# CO₂ prediction model

`co2_model.joblib` is the supplied prediction artifact.

The artifact was supplied as `rf_direct_5min (1).joblib`. It records scikit-learn 1.6.1 and expects 23 features, including `session_elapsed_minutes`. Only load model files from a trusted source. The launcher does not retrain the model.

The predictor loads the artifact with matching runtime dependencies and recreates the training feature names, order, units, and preprocessing.
