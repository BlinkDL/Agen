from __future__ import annotations
import json
from pathlib import Path
from agen_runtime import State, agen_loop

if __name__ == "__main__":
    state = agen_loop(State(), source_path=Path(__file__).with_name("npc.agen"))
    print(json.dumps(state.public_dict(), ensure_ascii=False, indent=2))
