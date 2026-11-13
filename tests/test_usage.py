from app.openai_compat.stream import usage_dict


def test_usage_basic():
    assert usage_dict({}) == {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    assert usage_dict({"input_tokens": 10, "output_tokens": 5}) == {
        "prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15,
    }


def test_usage_cache_fields_surfaced():
    out = usage_dict({
        "input_tokens": 12,
        "output_tokens": 7,
        "cache_creation_input_tokens": 1000,
        "cache_read_input_tokens": 2000,
    })
    # OpenAI semantics: prompt_tokens is the whole prompt, cached part included.
    assert out["prompt_tokens"] == 3012
    assert out["total_tokens"] == 3019
    assert out["prompt_tokens_details"]["cached_tokens"] == 2000
    assert out["cache_creation_input_tokens"] == 1000
    assert out["cache_read_input_tokens"] == 2000


def test_usage_no_cache_fields_when_zero():
    out = usage_dict({"input_tokens": 3, "output_tokens": 1,
                      "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0})
    assert "prompt_tokens_details" not in out
    assert "cache_creation_input_tokens" not in out
    assert "cache_read_input_tokens" not in out


def test_usage_cost_and_session():
    out = usage_dict({"input_tokens": 10, "output_tokens": 5}, cost_usd=0.123,
                     session_id="abc")
    assert out["cost_usd"] == 0.123
    assert out["session_id"] == "abc"


def test_usage_cost_from_cli_usage():
    out = usage_dict({"input_tokens": 10, "output_tokens": 5, "cost_usd": 0.5})
    assert out["cost_usd"] == 0.5


def test_usage_cache_details():
    out = usage_dict({"input_tokens": 12, "output_tokens": 7,
                      "cache_creation_input_tokens": 1000,
                      "cache_read_input_tokens": 2000})
    assert out["prompt_tokens_details"] == {
        "cached_tokens": 2000, "cache_creation_tokens": 1000,
    }


def test_usage_cached_tokens_never_exceed_prompt_tokens():
    out = usage_dict({"input_tokens": 2, "output_tokens": 4,
                      "cache_creation_input_tokens": 449,
                      "cache_read_input_tokens": 12913})
    assert out["prompt_tokens"] == 2 + 449 + 12913
    assert out["prompt_tokens_details"]["cached_tokens"] <= out["prompt_tokens"]
