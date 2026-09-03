import runpy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_architecture_contract_validator_passes():
    module = runpy.run_path(str(ROOT / "scripts/validate_architecture_consistency.py"))
    module["validate"]()
