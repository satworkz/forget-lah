"""Export the strict decision contract used by the M2a runtime."""

import json
from pathlib import Path

from forget_lah.runtime.contracts import decision_adapter

target = Path(__file__).resolve().parents[1] / "docs/contracts/agent-decision-v1.json"
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(json.dumps(decision_adapter.json_schema(), indent=2) + "\n", encoding="utf-8")
print(f"Exported {target.name}")
