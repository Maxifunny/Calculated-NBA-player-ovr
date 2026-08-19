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


class TrueOvrModelV3:
    """
    v3 improvements:
      - offense_index / defense_index (separate)
      - position-dependent blend: centers lean toward defense
      - PER (and offense usage) position-normalized + minutes credibility applied
        only inside the offense side (where sample-size variance is highest).
    """

    model_name = "v3"

    offense_features = ("per", "ts_pct", "usage_efficiency", "ast_pct", "bpm", "vorp", "pie")
    defense_features = ("dbpm", "stocks_per_100", "dws", "def_events_per_100")

    def _offense_share_by_group(self, pos_grp: pd.Series) -> np.ndarray:
        # Offense share α; defense share is (1-α).
        grp = pos_grp.astype("string").fillna("other")
        out = np.full(len(grp), 0.50, dtype=float)
        out[grp == "center_pf"] = 0.45
        out[grp == "wings"] = 0.55
        out[grp == "backcourt"] = 0.60
        return out

    def predict(self, frame: pd.DataFrame) -> pd.DataFrame:
        required = list(OVR_WEIGHTS.keys()) + ["gp", "mpg", "ovr_2k", "position"]
        missing = [c for c in required if c not in frame.columns]
        if missing:
            raise ValueError(f"Missing required columns for {self.model_name}: {missing}")

        out = frame.copy()
        out = prepare_defensive_and_pie_features(out)

        pos_grp = position_group(out["position"])
        cred = minutes_credibility_percentile(out, position_group_series=pos_grp)

        # Compute normalized units for every feature.
        units: dict[str, np.ndarray] = {}
        for col in OVR_WEIGHTS.keys():
            out[col] = pd.to_numeric(out[col], errors="coerce")
            if col == "per":
                units[col] = robust_01_grouped(out[col], pos_grp)
            else:
                units[col] = robust_01(out[col])

        # Apply minutes credibility inside offense only.
        # Shrink "offense volatility" features toward 0.5 on the unit scale.
        per_unit_adj = 0.5 + (units["per"] - 0.5) * cred
        usage_unit_adj = 0.5 + (units.get("usage_efficiency", np.full(len(out), 0.5))) * cred

        composite_off = np.zeros(len(out), dtype=float)
        composite_def = np.zeros(len(out), dtype=float)

        off_weight_sum = sum(float(OVR_WEIGHTS[f]) for f in self.offense_features)
        def_weight_sum = sum(float(OVR_WEIGHTS[f]) for f in self.defense_features)

        for f in self.offense_features:
            w = float(OVR_WEIGHTS[f])
            if f == "per":
                composite_off += per_unit_adj * w
            elif f == "usage_efficiency":
                composite_off += usage_unit_adj * w
            else:
                composite_off += units[f] * w

        for f in self.defense_features:
            w = float(OVR_WEIGHTS[f])
            composite_def += units[f] * w

        offense_index = composite_off / float(off_weight_sum)  # ∈ [~0..1]
        defense_index = composite_def / float(def_weight_sum)  # ∈ [~0..1]

        alpha = self._offense_share_by_group(pos_grp)  # offense share
        true_ovr_raw = alpha * offense_index + (1.0 - alpha) * defense_index

        out["minutes_credibility"] = cred
        out["offense_index"] = offense_index
        out["defense_index"] = defense_index
        out["true_ovr_raw"] = true_ovr_raw
        out["true_ovr"] = scale_raw_to_ovr_band(
            true_ovr_raw, ovr_min=OVR_SCALE_MIN, ovr_max=OVR_SCALE_MAX
        )
        out["ovr_gap"] = out["ovr_2k"].to_numpy(dtype=float) - out["true_ovr"].to_numpy(dtype=float)
        out["overrated_flag"] = out["ovr_gap"] >= 5
        out["underrated_flag"] = out["ovr_gap"] <= -5
        return out


MODEL_V3 = TrueOvrModelV3()

