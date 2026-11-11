from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK_DIR = ROOT / "KC_CO2_Modular_Notebooks"
PIPELINE = NOTEBOOK_DIR / "models" / "gru_pipeline.py"


class PullRequestReviewContracts(unittest.TestCase):
    def test_neural_modules_live_with_notebooks(self):
        self.assertTrue(PIPELINE.is_file())
        self.assertTrue((NOTEBOOK_DIR / "models" / "lstm_pipeline.py").is_file())
        self.assertFalse((ROOT / "models" / "gru_pipeline.py").exists())
        self.assertFalse((ROOT / "models" / "lstm_pipeline.py").exists())

    def test_notebooks_bootstrap_matching_neural_modules(self):
        for name, module in (("03_GRU.ipynb", "gru_pipeline.py"), ("04_LSTM.ipynb", "lstm_pipeline.py")):
            source = (NOTEBOOK_DIR / name).read_text(encoding="utf-8")
            self.assertIn("REPO_REF =", source)
            self.assertIn(module, source)
            self.assertIn("KC_CO2_Modular_Notebooks/models/", source)
            self.assertNotIn("PROJECT_ROOT / \"models\"", source)

    def test_pipeline_rejects_filtered_origins_and_stale_results(self):
        source = PIPELINE.read_text(encoding="utf-8")
        self.assertIn("def _validate_origin_keys", source)
        self.assertIn("Missing 11-point sequence", source)
        self.assertIn("Neural predictions do not preserve the prepared evaluation origins", source)
        self.assertIn("def _validate_preparation_identity", source)
        self.assertIn("Rerun direct forecasting before recursive forecasting", source)
        self.assertIn("_validate_preparation_identity(old.get(\"metadata\", {}), metadata)", source)


if __name__ == "__main__":
    unittest.main()