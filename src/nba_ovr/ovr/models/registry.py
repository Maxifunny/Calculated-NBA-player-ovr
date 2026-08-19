from __future__ import annotations

from .v1 import MODEL_V1, TrueOvrModelV1
from .v2 import MODEL_V2, TrueOvrModelV2
from .v3 import MODEL_V3, TrueOvrModelV3


def available_models() -> dict[str, object]:
    return {
        MODEL_V1.model_name: MODEL_V1,
        MODEL_V2.model_name: MODEL_V2,
        MODEL_V3.model_name: MODEL_V3,
    }


def resolve_model_selection(model_arg: str) -> list[object]:
    """
    CLI resolver:
      - v1/v2/v3 → list with one model
      - all       → list with all models
    """
    models = available_models()
    if model_arg == "all":
        return [models["v1"], models["v2"], models["v3"]]
    if model_arg not in models:
        raise ValueError(f"Unknown --model {model_arg}. Expected one of: {sorted(models)} or 'all'.")
    return [models[model_arg]]

