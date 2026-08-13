from __future__ import annotations

import importlib.util
import re
import sys
import uuid
from importlib.machinery import SourceFileLoader
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def load_script_module(script_name: str):
    script_path = REPO_ROOT / script_name
    normalized_name = re.sub(r"\W+", "_", script_name)
    module_name = f"tests._loaded_{normalized_name}_{uuid.uuid4().hex}"
    loader = SourceFileLoader(module_name, str(script_path))
    spec = importlib.util.spec_from_loader(module_name, loader)
    if spec is None:
        raise ImportError(f"Unable to create import spec for {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    loader.exec_module(module)
    return module
