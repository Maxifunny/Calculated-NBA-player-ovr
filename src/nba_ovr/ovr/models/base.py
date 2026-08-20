from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import pandas as pd


class TrueOvrModel(Protocol):
    """
    Minimal shared interface across heuristic True OVR variants.

    Contract:
      - model_name: identifier used for reports/CSV.
      - predict(frame): returns frame with at least:
          true_ovr (int in [62, 99]) and ovr_gap (ovr_2k - true_ovr)
    """

    model_name: str

    def predict(self, frame: pd.DataFrame) -> pd.DataFrame:  # pragma: no cover (protocol)
        ...


@dataclass(frozen=True)
class ModelPredictionSpec:
    model_name: str
    ovr_min: int = 62
    ovr_max: int = 99

