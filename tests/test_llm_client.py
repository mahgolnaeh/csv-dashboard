"""
Tests for insights/llm_client.py — written BEFORE implementation (TDD).

Three cases per tasks.md T-031:
  1. Mock httpx.post returns valid response → call_llm returns stripped content.
  2. Mock httpx.post raises httpx.HTTPError → LLMError raised.
  3. Mock httpx.post returns malformed JSON (missing 'choices') → LLMError raised.
"""

import pytest
import httpx

from csv_dashboard.insights.llm_client import call_llm, LLMError


def _make_response(mocker, content: str):
    """Build a minimal fake httpx response with the OpenRouter shape."""
    resp = mocker.Mock()
    resp.raise_for_status = mocker.Mock()
    resp.json.return_value = {
        "choices": [{"message": {"content": content}}]
    }
    return resp


def test_successful_call_returns_stripped_content(mocker) -> None:
    mocker.patch("httpx.post", return_value=_make_response(mocker, "  Hello from LLM  "))
    result = call_llm("sys-prompt", "user-prompt", "test-model")
    assert result == "Hello from LLM"


def test_http_error_raises_llm_error(mocker) -> None:
    mocker.patch("httpx.post", side_effect=httpx.HTTPError("connection failed"))
    with pytest.raises(LLMError):
        call_llm("sys-prompt", "user-prompt", "test-model")


def test_malformed_response_missing_choices_raises_llm_error(mocker) -> None:
    resp = mocker.Mock()
    resp.raise_for_status = mocker.Mock()
    resp.json.return_value = {"error": "upstream failure"}  # no 'choices' key
    mocker.patch("httpx.post", return_value=resp)
    with pytest.raises(LLMError):
        call_llm("sys-prompt", "user-prompt", "test-model")


def test_httpx_post_called_with_correct_url_and_timeout(mocker) -> None:
    mock_post = mocker.patch(
        "httpx.post", return_value=_make_response(mocker, "response")
    )
    call_llm("sys", "usr", "anthropic/claude-haiku-4.5", max_tokens=512)
    mock_post.assert_called_once()
    call_args = mock_post.call_args
    assert call_args.args[0] == "https://openrouter.ai/api/v1/chat/completions"
    assert call_args.kwargs["timeout"] == 60
    payload = call_args.kwargs["json"]
    assert payload["model"] == "anthropic/claude-haiku-4.5"
    assert payload["max_tokens"] == 512
    assert payload["messages"][0]["role"] == "system"
    assert payload["messages"][1]["role"] == "user"
