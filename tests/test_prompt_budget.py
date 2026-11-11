import json
from unittest.mock import MagicMock, patch

import pytest

from farol import local, prompt_budget

MESSAGES = [{"role": "system", "content": "fixture"}, {"role": "user", "content": "{}"}]


def test_template_schema_and_output_reservation_all_count():
    with patch.object(prompt_budget, "render_chat", return_value="rendered-with-template") as render, \
         patch.object(prompt_budget, "token_count", side_effect=[5000, 600]) as count:
        receipt = prompt_budget.enforce(MESSAGES, {"type": "object"}, thinking=False, output_tokens=700)
    assert receipt["input_tokens"] == 5600 and receipt["input_ceiling"] == 6500
    assert receipt["output_reserved"] == 700 and receipt["headroom"] == 128
    assert count.call_args_list[0].args[0] == "rendered-with-template"
    assert json.loads(count.call_args_list[1].args[0]) == {"type": "object"}
    assert render.call_args.kwargs["thinking"] is False


@pytest.mark.parametrize("prompt,schema,output", [(6400, 101, 700), (6000, 100, 2200)])
def test_over_budget_request_sends_no_http_and_never_truncates(prompt, schema, output):
    with patch.object(prompt_budget, "render_chat", return_value="complete input"), \
         patch.object(prompt_budget, "token_count", side_effect=[prompt, schema]), \
         patch.object(local, "urlopen") as http, pytest.raises(prompt_budget.PromptBudgetExceeded):
        local.complete(system="fixture", user="{}", cache_key="unused", model_profile="qwen", max_tokens=output)
    http.assert_not_called()


def test_unavailable_tokenizer_does_not_send_unmeasured_prompt():
    with patch.object(prompt_budget, "render_chat", side_effect=FileNotFoundError()), \
         patch.object(local, "urlopen") as http, pytest.raises(prompt_budget.PromptBudgetUnavailable):
        local.complete(system="fixture", user="{}", cache_key="unused", model_profile="qwen")
    http.assert_not_called()


def test_verified_measurement_is_attached_to_response():
    response = MagicMock()
    response.__enter__.return_value.read.return_value = b'{"choices": []}'
    with patch.object(prompt_budget, "enforce", return_value={"input_tokens": 4500}), \
         patch.object(local, "urlopen", return_value=response):
        payload, _, _ = local.complete(system="fixture", user="{}", cache_key="unused", model_profile="qwen")
    assert payload["rideedge_prompt_budget"]["input_tokens"] == 4500
