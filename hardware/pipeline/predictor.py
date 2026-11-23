"""KCO2-HW-02 — Live features and CO₂ prediction. Owned by teammate."""

IMPLEMENTED = False


class Predictor:
    def __init__(self, model_path):
        """Load the supplied trusted model/preprocessing once, at startup."""
        raise NotImplementedError("KCO2-HW-02 — Live features and CO₂ prediction")

    def predict(self, history, *, session_start):
        """Return {'predicted_co2': float, 'horizon_minutes': positive float}.

        history is the merged reader's DataFrame: time (UTC), co2, temp_c, rh,
        is_stale. Use a copy and match all 23 features expected by the supplied
        model, including session_elapsed_minutes. Confirm the training session
        origin, feature names/order, preprocessing and sampling cadence with HW-02.
        Never reset elapsed time at each sliding query window.
        Do not include is_stale as a feature unless it was used during training.
        Return absolute CO2 ppm (convert delta predictions if necessary).
        Tell the launcher owner the required history span, count and maximum gap.
        No model training, InfluxDB queries or fan commands belong here.
        """
        raise NotImplementedError
