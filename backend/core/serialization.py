from __future__ import annotations


def model_to_dict(model, by_alias: bool = False):
    if hasattr(model, "model_dump"):
        return model.model_dump(by_alias=by_alias)
    return model.dict(by_alias=by_alias)


def model_to_json(model, by_alias: bool = False) -> str:
    if hasattr(model, "model_dump_json"):
        return model.model_dump_json(by_alias=by_alias)
    return model.json(by_alias=by_alias)
