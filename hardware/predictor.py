"""KCO2-HW-02 — Live features and CO₂ prediction. Owned by teammate."""

IMPLEMENTED = False


class Predictor:
    def __init__(self, model_path):
        """Load the supplied trusted model/preprocessing once, at startup."""
        raise NotImplementedError("KCO2-HW-02 — Live features and CO₂ prediction")

    def predict(self, history, *, session_start):
        """Return {'predicted_co2': float, 'horizon_minutes': positive float}.

        history is PR #4's DataFrame: time (UTC), co2, temp_c, rh, is_stale.
        Use a copy: rename temp_c to temp if that matches the saved model. Derive
        elapsed time from the fixed UTC session_start using the training units
        and exact feature name. Never reset it at each sliding query window.
        Reproduce all training features/order, preprocessing and sampling cadence.
        Do not include is_stale as a feature unless it was used during training.
        Return absolute CO2 ppm (convert delta predictions if necessary).
        Tell the launcher owner the required history span, count and maximum gap.
        No model training, InfluxDB queries or fan commands belong here.
        """
        raise NotImplementedError
