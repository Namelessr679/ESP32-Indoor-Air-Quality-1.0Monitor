"""LSTM entry points backed by the shared recurrent adapter."""

from __future__ import annotations

from pathlib import Path

from .gru_pipeline import run_direct, run_recursive


def run(run_dir: Path, output_dir: Path | None = None):
    return run_direct("LSTM", run_dir, output_dir)


def run_recursive_forecast(run_dir: Path, output_dir: Path | None = None):
    return run_recursive("LSTM", run_dir, output_dir)