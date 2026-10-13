from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agents import (
    AgentError,
    HermesPlanner,
    extract_json,
    hermes_command,
    validate_design,
)


def test_extract_json_plain() -> None:
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_fenced() -> None:
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('```\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_rejects_python_literal() -> None:
    with pytest.raises(AgentError):
        extract_json("{'a': 1}")


def test_extract_json_rejects_extra_text() -> None:
    with pytest.raises(AgentError):
        extract_json('前缀 {"a": 1}')


def test_validate_design_ok() -> None:
    value = {
        "design": "设计",
        "shots": [
            {"start": 0, "end": 5, "description": "开场"},
            {"start": 5, "end": 10, "description": "结尾"},
        ],
        "prompt": "提示词",
    }
    out = validate_design(value, 10)
    assert out["design"] == "设计"
    assert out["prompt"] == "提示词"
    assert len(out["shots"]) == 2


def test_validate_design_rejects_gap() -> None:
    value = {
        "design": "d",
        "shots": [
            {"start": 0, "end": 5, "description": "a"},
            {"start": 6, "end": 10, "description": "b"},
        ],
        "prompt": "p",
    }
    with pytest.raises(AgentError):
        validate_design(value, 10)


def test_validate_design_rejects_wrong_cover() -> None:
    value = {
        "design": "d",
        "shots": [{"start": 0, "end": 9, "description": "a"}],
        "prompt": "p",
    }
    with pytest.raises(AgentError):
        validate_design(value, 10)


def test_validate_design_rejects_too_many_shots() -> None:
    shots = [{"start": i, "end": i + 1, "description": "x"} for i in range(25)]
    value = {"design": "d", "shots": shots, "prompt": "p"}
    with pytest.raises(AgentError):
        validate_design(value, 25)


def test_validate_design_rejects_long_prompt() -> None:
    value = {
        "design": "d",
        "shots": [{"start": 0, "end": 1, "description": "a"}],
        "prompt": "x" * 12001,
    }
    with pytest.raises(AgentError):
        validate_design(value, 1)


def test_hermes_command_uses_absolute_query_file(tmp_path: Path) -> None:
    q = tmp_path / "q.txt"
    argv = hermes_command("hermes", q)
    assert argv[:2] == ["hermes", "chat"]
    assert "--query-file" in argv
    assert str(q.resolve()) in argv
    assert "--oneshot" in argv
    assert "--format" in argv
    assert "stream-json" in argv
    assert "--safe-mode" in argv
    assert "--toolsets" in argv
    assert "workflow_no_tools" in argv
    assert "--model" in argv
    assert "deepseek-v4-flash" in argv
    assert "--provider" in argv
    assert "deepseek" in argv


def test_hermes_command_no_shell_metachar_injection(tmp_path: Path) -> None:
    q = tmp_path / "a b; rm -rf.txt"
    argv = hermes_command("hermes", q)
    assert argv[3] == str(q.resolve())


def test_hermes_parse_result_event() -> None:
    planner = HermesPlanner()
    text = json.dumps({"type": "result", "result": '{"actions": ["verify_generation", "upload_references", "fill_prompt", "read_quote"]}'})
    assert planner._parse_actions(text) == planner.EXPECTED


def test_hermes_parse_message_event() -> None:
    planner = HermesPlanner()
    text = json.dumps({
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": '{"actions": ["verify_generation", "upload_references", "fill_prompt", "read_quote"]}'}],
    })
    assert planner._parse_actions(text) == planner.EXPECTED


def test_hermes_parse_final_response() -> None:
    planner = HermesPlanner()
    text = json.dumps({"type": "message", "role": "assistant", "final_response": '{"actions": ["verify_generation", "upload_references", "fill_prompt", "read_quote"]}'})
    assert planner._parse_actions(text) == planner.EXPECTED


def test_hermes_reject_tool_events() -> None:
    planner = HermesPlanner()
    text = json.dumps({"type": "tool_call", "result": '{"actions": []}'})
    with pytest.raises(AgentError):
        planner._parse_actions(text)


def test_hermes_reject_wrong_sequence() -> None:
    planner = HermesPlanner()
    text = json.dumps({"type": "result", "result": '{"actions": ["upload_references", "verify_generation"]}'})
    with pytest.raises(AgentError):
        planner._parse_actions(text)
