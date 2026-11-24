"""Live CO₂ prediction."""

AVAILABLE = False


class Predictor:
    def __init__(self, model_path):
        raise NotImplementedError

    def predict(self, history, *, session_start):
        raise NotImplementedError
