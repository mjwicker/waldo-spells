"""Tests for llama_backend stub behavior (no model required)."""

import os
import sys
import pathlib
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import llama_backend


def _clear_env():
    for k in ("LLAMA_MODEL_PATH", "LLAMA_SERVER_BIN", "LLAMA_SERVER_PORT", "LLAMA_SERVER_HOST"):
        os.environ.pop(k, None)


def test_is_available_no_env():
    _clear_env()
    assert llama_backend.is_available() is False


def test_is_available_nonexistent_model():
    _clear_env()
    os.environ["LLAMA_MODEL_PATH"] = "/tmp/nonexistent_model.gguf"
    assert llama_backend.is_available() is False


def test_is_available_file_exists_no_server():
    _clear_env()
    with tempfile.NamedTemporaryFile(suffix=".gguf", delete=False) as f:
        f.write(b"fake")
        tmp = f.name
    try:
        os.environ["LLAMA_MODEL_PATH"] = tmp
        # No server binary in env — returns False unless llama-server happens to be in PATH
        # We force it absent by pointing to a nonexistent binary
        os.environ["LLAMA_SERVER_BIN"] = "/nonexistent/llama-server"
        assert llama_backend.is_available() is False
    finally:
        pathlib.Path(tmp).unlink(missing_ok=True)


def test_correct_raises_when_unavailable():
    _clear_env()
    try:
        llama_backend.correct("Hello world")
        assert False, "Should have raised RuntimeError"
    except RuntimeError as e:
        assert "unavailable" in str(e).lower()
        assert "LLAMA_MODEL_PATH" in str(e)


def test_correct_error_message_includes_install_hint():
    _clear_env()
    try:
        llama_backend.correct("test")
    except RuntimeError as e:
        assert "llama.cpp" in str(e) or "LLAMA_MODEL_PATH" in str(e)


def test_is_available_returns_bool():
    _clear_env()
    result = llama_backend.is_available()
    assert isinstance(result, bool)


# Tests for _parse_json_with_repair

def test_parse_json_with_repair_valid_json_passes_through():
    """Valid JSON should parse without modification."""
    valid = '{"corrections": [{"original": "foo", "suggestion": "bar"}]}'
    result = llama_backend._parse_json_with_repair(valid)
    assert result == {"corrections": [{"original": "foo", "suggestion": "bar"}]}


def test_parse_json_with_repair_empty_corrections():
    """Valid JSON with empty corrections array should parse."""
    valid = '{"corrections": []}'
    result = llama_backend._parse_json_with_repair(valid)
    assert result == {"corrections": []}


def test_parse_json_with_repair_pass2_double_brace_before_bracket():
    """Pass 2: Replace }}] → }] (extra closing brace before array close)."""
    # Single item with extra closing brace
    malformed = '{"corrections": [{"original": "of", "suggestion": "have"}]}]'
    result = llama_backend._parse_json_with_repair(malformed)
    assert result == {"corrections": [{"original": "of", "suggestion": "have"}]}


def test_parse_json_with_repair_pass2_multiple_extra_braces():
    """Pass 2: Replace }}}] → }] (multiple extra closing braces before bracket)."""
    # This case has extra braces before the array closing bracket
    malformed = '{"corrections": [{"original": "foo", "suggestion": "bar"}}]'
    result = llama_backend._parse_json_with_repair(malformed)
    assert result == {"corrections": [{"original": "foo", "suggestion": "bar"}]}


def test_parse_json_with_repair_pass2_multiple_items_with_extra_braces():
    """Pass 2: Handle multiple items in array, each with extra brace."""
    # Model generates array with }}] pattern at the very end
    malformed = '{"corrections": [{"original": "a", "suggestion": "b"}, {"original": "c", "suggestion": "d"}]}]'
    result = llama_backend._parse_json_with_repair(malformed)
    # After pass 2 repair: }}] → }], this becomes valid
    assert len(result["corrections"]) == 2
    assert result["corrections"][0] == {"original": "a", "suggestion": "b"}
    assert result["corrections"][1] == {"original": "c", "suggestion": "d"}


def test_parse_json_with_repair_pass3_missing_array_close():
    """Pass 3: Replace }}} (or more) at end → }]} (missing array close bracket)."""
    # Model emits }} at end (no closing bracket for array)
    malformed = '{"corrections": [{"original": "test", "suggestion": "check"}]}'
    # Simulate truncation: missing ] before final }
    malformed = '{"corrections": [{"original": "test", "suggestion": "check"}}'
    result = llama_backend._parse_json_with_repair(malformed)
    assert result == {"corrections": [{"original": "test", "suggestion": "check"}]}


def test_parse_json_with_repair_pass4_truncated_missing_outer_brace():
    """Pass 4: Truncated output ending in ] — append final }."""
    # Missing outer closing brace
    malformed = '{"corrections": [{"original": "foo", "suggestion": "bar"}]'
    result = llama_backend._parse_json_with_repair(malformed)
    assert result == {"corrections": [{"original": "foo", "suggestion": "bar"}]}


def test_parse_json_with_repair_pass5_junk_after_last_brace():
    """Pass 5: Strip junk after the last } and retry."""
    malformed = '{"corrections": [{"original": "test", "suggestion": "pass"}]} garbage data here'
    result = llama_backend._parse_json_with_repair(malformed)
    assert result == {"corrections": [{"original": "test", "suggestion": "pass"}]}


def test_parse_json_with_repair_all_passes_fail_raises():
    """When all repair passes fail, JSONDecodeError is raised."""
    import json
    completely_malformed = '{{[[['
    try:
        llama_backend._parse_json_with_repair(completely_malformed)
        assert False, "Should have raised json.JSONDecodeError"
    except json.JSONDecodeError:
        pass


def test_parse_json_with_repair_empty_string_raises():
    """Empty string should raise JSONDecodeError."""
    import json
    try:
        llama_backend._parse_json_with_repair('')
        assert False, "Should have raised json.JSONDecodeError"
    except json.JSONDecodeError:
        pass


def test_parse_json_with_repair_complex_multi_item_array():
    """Complex case: multiple corrections with real-world malformation pattern."""
    # Real pattern from Qwen: }}] at the end
    malformed = '{"corrections": [{"original": "soooooo", "suggestion": "so"}, {"original": "teh", "suggestion": "the"}]}]'
    result = llama_backend._parse_json_with_repair(malformed)
    # This tests the regex repair on more complex structures
    assert "corrections" in result
    assert len(result["corrections"]) == 2


# New tests for T-SPELLS-JSON-1: mixed bracket/paren close repair (e.g. [) → [])
# These would have raised "All repair passes failed" before the fix; now succeed.
# Sprint Close Gate: new tests added for parsing/repair change.

def test_parse_json_with_repair_paren_array_close_simple():
    """Pass 2 paren normalize: {"corrections": [)}  (bare [) case) → [] ."""
    import json
    malformed = '{"corrections": [)}'
    result = llama_backend._parse_json_with_repair(malformed)
    assert result == {"corrections": []}


def test_parse_json_with_repair_paren_array_close_after_item():
    """Pass 2: ) used after object item in array, e.g. ...} ) } → proper [] close."""
    malformed = '{"corrections": [{"original": "of", "suggestion": "have"})}'
    result = llama_backend._parse_json_with_repair(malformed)
    assert result == {"corrections": [{"original": "of", "suggestion": "have"}]}


def test_parse_json_with_repair_paren_normalize_multi():
    """Pass 2 + subsequent: mixed paren on complex output still recovers items."""
    malformed = '{"corrections": [{"original": "teh", "suggestion": "the"}, {"original": "recieve", "suggestion": "receive"}) }'
    result = llama_backend._parse_json_with_repair(malformed)
    assert "corrections" in result
    assert len(result["corrections"]) == 2
    assert result["corrections"][0]["original"] == "teh"


def test_parse_json_with_repair_paren_normalize_then_later_pass_append():
    """Pass 2 paren fix turns ) to ], leaving unclosed root obj; later pass 5 appends }."""
    # Input has paren close + missing final } for object (common truncation mix)
    malformed = '{"corrections": [{"original": "x", "suggestion": "y"} )'
    result = llama_backend._parse_json_with_repair(malformed)
    assert result == {"corrections": [{"original": "x", "suggestion": "y"}]}
