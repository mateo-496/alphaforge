import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from tools.portfolio_csv import convert_portfolio_csv


def test_convert_csv_to_validated_portfolio():
    result = convert_portfolio_csv("\ufeffticker,weight\n asml ,0.6\nNVDA,0.4\n")
    assert result == {"holdings": [{"ticker": "ASML", "weight": 0.6},
                                   {"ticker": "NVDA", "weight": 0.4}]}


@pytest.mark.parametrize("data", [
    "ticker,weight,weight\nASML,0.5,0.5\n",
    "ticker,weight\nASML,0.5,extra\n",
    "ticker,weight\nASML\n",
])
def test_rejects_malformed_csv(data):
    with pytest.raises(ValueError):
        convert_portfolio_csv(data)


def test_rejects_invalid_portfolio():
    with pytest.raises(ValidationError):
        convert_portfolio_csv("ticker,weight\nASML,0.8\nNVDA,0.3\n")


def test_cli_converts_example(tmp_path):
    output = tmp_path / "portfolio.json"
    result = subprocess.run(
        [sys.executable, "-m", "tools.portfolio_csv", "portefeuille-test.csv", str(output)],
        check=True, capture_output=True, text=True)
    assert result.returncode == 0
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data == convert_portfolio_csv(Path("portefeuille-test.csv").read_text(encoding="utf-8"))
