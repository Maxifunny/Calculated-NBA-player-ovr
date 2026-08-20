from __future__ import annotations

import numpy as np
import pandas as pd

from nba_ovr.settings import OVR_SCALE_MAX, OVR_SCALE_MIN, OVR_WEIGHTS

from .utils import (
    minutes_credibility_percentile,
    position_group,
    prepare_defensive_and_pie_features,
    robust_01,
    robust_01_grouped,
    scale_raw_to_ovr_band,
)


class TrueOvrModelV2:
    """
    v2 improvements:
      - PER normalization within coarse position roles (C/PF vs wings vs backcourt)
        so PER doesn't get "misplaced" in the global scale.
      - minutes credibility shrinks only the PER component (not the whole composite),
        reducing accidental under/over-rating of centers based on sample size.
      - global percentile mapping to [62..99] to keep cross-position comparability.
    """

    model_name = "v2"

    def predict(self, frame: pd.DataFrame) -> pd.DataFrame:
        required = list(OVR_WEIGHTS.keys()) + ["gp", "mpg", "ovr_2k", "position"]
        missing = [c for c in required if c not in frame.columns]
        if missing:
            raise ValueError(f"Missing required columns for {self.model_name}: {missing}")

        out = frame.copy()
        out = prepare_defensive_and_pie_features(out)

        pos_grp = position_group(out["position"])
        cred = minutes_credibility_percentile(out, position_group_series=pos_grp)

        composite = np.zeros(len(out), dtype=float)

        # PER is the feature where position mismatch hurts most.
        if "per" in out.columns:
            per_vals = pd.to_numeric(out["per"], errors="coerce")
            per_unit = robust_01_grouped(per_vals, pos_grp)
            # Shrink PER only, around the mid-point (0.5) of the unit scale.
            per_unit_adj = 0.5 + (per_unit - 0.5) * cred
            out["unit_per"] = per_unit
            out["unit_per_adj"] = per_unit_adj
        else:
            per_unit_adj = np.full(len(out), 0.5, dtype=float)

        for col, w in OVR_WEIGHTS.items():
            if col == "per":
                composite += per_unit_adj * float(w)
                continue

            out[col] = pd.to_numeric(out[col], errors="coerce")
            unit = robust_01(out[col])
            composite += unit * float(w)
            out[f"unit_{col}"] = unit

        out["minutes_credibility"] = cred
        out["true_ovr_raw"] = composite
        out["true_ovr"] = scale_raw_to_ovr_band(
            composite, ovr_min=OVR_SCALE_MIN, ovr_max=OVR_SCALE_MAX
        )
        out["ovr_gap"] = out["ovr_2k"].to_numpy(dtype=float) - out["true_ovr"].to_numpy(dtype=float)
        out["overrated_flag"] = out["ovr_gap"] >= 5
        out["underrated_flag"] = out["ovr_gap"] <= -5
        return out


MODEL_V2 = TrueOvrModelV2()

