from __future__ import annotations

import numpy as np
import pandas as pd

from nba_ovr.settings import OVR_SCALE_MAX, OVR_SCALE_MIN, OVR_WEIGHTS

from .utils import minutes_credibility_percentile, prepare_defensive_and_pie_features, robust_01, scale_raw_to_ovr_band


class TrueOvrModelV1:
    """
    Baseline heuristic (existing Stage 4 logic):
      - robust_01 compression per feature (global)
      - weighted sum using OVR_WEIGHTS
      - minutes credibility shrinks the *whole* composite toward 0.5
      - global percentile→OVR band scaling to [62..99]
    """

    model_name = "v1"

    def _minutes_credibility_composite(self, frame: pd.DataFrame) -> np.ndarray:
        gp = pd.to_numeric(frame.get("gp"), errors="coerce").fillna(0.0).to_numpy(dtype=float)
        mpg = pd.to_numeric(frame.get("mpg"), errors="coerce").fillna(0.0).to_numpy(dtype=float)
        minutes = gp * mpg
        prior = 500.0
        cred = minutes / (minutes + prior)
        return np.clip(cred, 0.40, 1.0)

    def predict(self, frame: pd.DataFrame) -> pd.DataFrame:
        required = list(OVR_WEIGHTS.keys()) + ["gp", "mpg", "ovr_2k", "position"]
        # position is not strictly required for v1; keep it for interface consistency.
        missing = [c for c in required if c not in frame.columns and c not in ("position", "gp", "mpg")]
        if missing:
            raise ValueError(f"Missing required columns for {self.model_name}: {missing}")

        out = frame.copy()
        out = prepare_defensive_and_pie_features(out)

        # Prepare features as numeric columns.
        for col in OVR_WEIGHTS.keys():
            if col not in out.columns:
                out[col] = np.nan
            out[col] = pd.to_numeric(out[col], errors="coerce")

        composite = np.zeros(len(out), dtype=float)
        for col, w in OVR_WEIGHTS.items():
            unit = robust_01(out[col])
            composite += unit * float(w)
            out[f"unit_{col}"] = unit  # useful for debugging/analysis

        minutes_cred = self._minutes_credibility_composite(out)
        out["minutes_credibility"] = minutes_cred
        composite_adj = 0.5 + (composite - 0.5) * minutes_cred
        out["true_ovr_raw"] = composite_adj

        out["true_ovr"] = scale_raw_to_ovr_band(
            out["true_ovr_raw"].to_numpy(),
            ovr_min=OVR_SCALE_MIN,
            ovr_max=OVR_SCALE_MAX,
        )
        out["ovr_gap"] = out["ovr_2k"].to_numpy(dtype=float) - out["true_ovr"].to_numpy(dtype=float)
        out["overrated_flag"] = out["ovr_gap"] >= 5
        out["underrated_flag"] = out["ovr_gap"] <= -5
        return out


MODEL_V1 = TrueOvrModelV1()

