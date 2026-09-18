"""scripts/evaluation/upload_langsmith_datasets.py must no-op cleanly (exit
0, no LangSmith SDK calls) when LANGSMITH_TRACING/LANGSMITH_API_KEY aren't
set - this is the path CI actually exercises, since it has no real
LangSmith project to upload to.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "evaluation" / "upload_langsmith_datasets.py"
)


def _load_script_module():
    spec = importlib.util.spec_from_file_location("upload_langsmith_datasets", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_main_no_ops_without_langsmith_configured(monkeypatch):
    from app.config import get_settings

    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    get_settings.cache_clear()
    try:
        module = _load_script_module()
        assert module.main() == 0
    finally:
        get_settings.cache_clear()


@pytest.mark.skip(reason="no real LangSmith project available in this environment")
def test_main_uploads_when_configured():
    """Documented as untestable here rather than silently unverified - see
    docs/EVALUATION.md. Exercise manually against a real LANGSMITH_API_KEY."""
