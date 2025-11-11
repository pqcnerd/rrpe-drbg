import tempfile
from datetime import date
from pathlib import Path
from typing import Generator
import pytest
from src import config

@pytest.fixture
def temp_output_dir(monkeypatch) -> Generator[Path, None, None]:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        outputs_dir = tmp_path / "outputs"
        daily_dir = outputs_dir / "daily"
        outputs_dir.mkdir()
        daily_dir.mkdir()
        
        monkeypatch.setattr(config, "OUTPUTS_DIR", str(outputs_dir))
        monkeypatch.setattr(config, "DAILY_DIR", str(daily_dir))
        monkeypatch.setattr(config, "ENTROPY_LOG", str(outputs_dir / "entropy_log.csv"))
        
        yield tmp_path

@pytest.fixture
def test_salt_key(monkeypatch) -> str:
    test_key = "test-secret-key-for-testing-only"
    monkeypatch.setenv(config.SALT_ENV_VAR, test_key)
    return test_key


@pytest.fixture
def sample_trade_date() -> date:
    return date(2024, 1, 15)

