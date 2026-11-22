"""KCO2-HW-02 — Live features and CO₂ prediction. Owned by teammate."""

IMPLEMENTED = False


class Predictor:
    def __init__(self, model_path):
        """Load the supplied trusted model/preprocessing once, at startup."""
        raise NotImplementedError("KCO2-HW-02 — Live features and CO₂ prediction")

    def predict(self, readings):
        """Return {'predicted_co2': float, 'horizon_minutes': positive float}.

        Reproduce training features/order, preprocessing and sampling cadence.
        Raise pipeline.WaitingForData until required history exists.
        """
        raise NotImplementedError
