import shutil

import pytest


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "cwb: needs CWB (cqp, cwb-encode); run in engine/Dockerfile.test"
    )
    config.addinivalue_line(
        "markers", "nlp: needs Stanza models; run in engine/Dockerfile.test"
    )


def pytest_collection_modifyitems(config, items):
    skip = pytest.mark.skip(reason="CWB not installed")
    for item in items:
        if "cwb" in item.keywords and not shutil.which("cqp"):
            item.add_marker(skip)
