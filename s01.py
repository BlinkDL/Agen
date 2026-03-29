from __future__ import annotations
import json
from pathlib import Path
from agen_runtime import State, agen_loop
from dataclasses import dataclass

@dataclass
class DummyResponse:
    stop_reason: str
    content: list[dict]

class DummyAPI:
    def query(self, *, messages: list[dict]) -> DummyResponse:
        last_message = messages[-1] if messages else None
        last_content = last_message.get("content") if isinstance(last_message, dict) else None
        if (
            last_message is not None
            and last_message.get("role") == "user"
            and isinstance(last_content, list)
            and all(item.get("type") == "tool_result" for item in last_content)
        ):
            tool_outputs = [item.get("content") for item in last_content]
            return DummyResponse(stop_reason="end_turn", content=[{"type": "text", "text": f"done: {', '.join(tool_outputs)}"}])
        return DummyResponse(
            stop_reason="tool_use",
            content=[
                {"type": "text", "text": "I'll check."},
                {"type": "tool_use", "id": "tool-1", "name": "bash", "input": {"command": "pwd"}},
                {"type": "tool_use", "id": "tool-2", "name": "bash", "input": {"command": "ls"}},
            ],
        )

_API = DummyAPI()

def QUERY(*, messages: list[dict]) -> DummyResponse:
    return _API.query(messages=messages)

def BASH(*, command: str) -> str:
    return f"OUT:{command}"

HELPERS = {"QUERY": QUERY, "BASH": BASH}

if __name__ == "__main__":
    state = agen_loop(State(query="check"), source_path=Path(__file__).with_name("s01.agen"), helpers=HELPERS)
    print(json.dumps(state.messages, ensure_ascii=False, indent=2))
