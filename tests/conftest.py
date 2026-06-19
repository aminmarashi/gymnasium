import json
import os

import pytest

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


@pytest.fixture
def fixtures_dir():
    return FIXTURES


def load_fixture(name):
    with open(os.path.join(FIXTURES, name), "r", encoding="utf-8") as fh:
        if name.endswith(".json"):
            return json.load(fh)
        return fh.read()


@pytest.fixture
def fixture():
    return load_fixture
