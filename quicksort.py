from __future__ import annotations
import json
from pathlib import Path
from agen_runtime import State, agen_loop

def run_quicksort(a: list[int] | None = None) -> list[int]:
    state = agen_loop(
        State(a=list(a or [5, 3, 8, 1, 4, 7, 2, 6])),
        source_path=Path(__file__).with_name("quicksort.agen"),
    )
    return state.a

if __name__ == "__main__":
    print(json.dumps(run_quicksort(), ensure_ascii=False, indent=2))
