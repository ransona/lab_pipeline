"""Worker used by the pipeline to write legacy Suite2p object .npy files."""

from __future__ import annotations

import datetime as _datetime
import json
import sys

import numpy as np


def _decode(value):
    if isinstance(value, dict) and value.get("__ndarray__"):
        dtype = value["dtype"]
        data = _decode(value["data"])
        if dtype == "object":
            return np.array(data, dtype=object).reshape(value["shape"])
        return np.array(data, dtype=np.dtype(dtype)).reshape(value["shape"])
    if isinstance(value, dict) and "__tuple__" in value:
        return tuple(_decode(item) for item in value["__tuple__"])
    if isinstance(value, dict) and "__datetime__" in value:
        return _datetime.datetime.fromisoformat(value["__datetime__"])
    if isinstance(value, dict) and "__date__" in value:
        return _datetime.date.fromisoformat(value["__date__"])
    if isinstance(value, dict) and "__time__" in value:
        return _datetime.time.fromisoformat(value["__time__"])
    if isinstance(value, dict):
        return {key: _decode(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_decode(item) for item in value]
    return value


def main():
    with open(sys.argv[1], "r", encoding="utf-8") as handle:
        request = json.load(handle)
    if request["action"] != "save":
        raise ValueError(f"Unknown action: {request['action']}")
    np.save(request["path"], _decode(request["value"]))


if __name__ == "__main__":
    main()
