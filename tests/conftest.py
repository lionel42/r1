import shutil
from pathlib import Path

import pytest

from r1.io.config import R1Config

DATA_DIR = Path(__file__).parent / "data" / "medusa"
# outputs of r1, left over if r1 was run in DATA_DIR itself
OUTPUTS = shutil.ignore_patterns("calc", "plot", "results")


@pytest.fixture
def r1_dir(tmp_path: Path) -> Path:
    """A writable copy of the test R1 directory."""
    target = tmp_path / "medusa"
    shutil.copytree(DATA_DIR, target, ignore=OUTPUTS)
    return target


@pytest.fixture
def config(r1_dir: Path) -> R1Config:
    return R1Config.from_dir(r1_dir)
