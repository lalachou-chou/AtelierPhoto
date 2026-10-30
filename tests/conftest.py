import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from atelier.store import Store


@pytest.fixture
def store(tmp_path):
    library = Store(tmp_path / "library")
    yield library
    library.close()


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])
