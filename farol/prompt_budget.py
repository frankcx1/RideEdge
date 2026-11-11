"""Count Qwen tokens with its GGUF vocabulary and chat template, without a GPU.

Schema tokens are additionally reserved as conservative overhead even when the
server applies the schema only as a decoding grammar. Nothing is truncated.
"""
from __future__ import annotations

import json
import os
import subprocess
from functools import lru_cache
from pathlib import Path

from farol.adapters.base import FeedError
from farol.local_models import profile

INPUT_CEILING = 6500
HEADROOM = 128


class PromptBudgetExceeded(FeedError):
    code = "prompt_budget_exceeded"


class PromptBudgetUnavailable(FeedError):
    code = "prompt_budget_unavailable"


@lru_cache(maxsize=2)
def _template(path: str, modified: int, size: int) -> str:
    del modified, size  # Invalidate when the configured artifact changes.
    from gguf import GGUFReader

    reader = GGUFReader(path, mode="r")
    field = reader.fields.get("tokenizer.chat_template")
    if field is None:
        raise PromptBudgetUnavailable("The configured Qwen model has no chat template")
    return field.contents()


def render_chat(messages: list[dict], *, thinking: bool, model: dict) -> str:
    from jinja2.sandbox import ImmutableSandboxedEnvironment

    path = Path(model["gguf"])
    stat = path.stat()
    environment = ImmutableSandboxedEnvironment(trim_blocks=True, lstrip_blocks=True)

    def reject(message):
        raise PromptBudgetUnavailable("The model chat template rejected the request")

    environment.globals["raise_exception"] = reject
    template = environment.from_string(_template(str(path), stat.st_mtime_ns, stat.st_size))
    return template.render(messages=messages, add_generation_prompt=True, enable_thinking=thinking,
                           tools=None)


def token_count(text: str, *, model: dict) -> int:
    executable = Path(model["server_exe"]).with_name("llama-tokenize.exe")
    if not executable.is_file():
        raise PromptBudgetUnavailable("The local model tokenizer is unavailable")
    result = subprocess.run(
        [str(executable), "-m", model["gguf"], "--stdin", "--ids", "--no-escape", "--log-disable"],
        input=text.encode("utf-8"), capture_output=True, timeout=40, check=False,
        env={**os.environ, "CUDA_VISIBLE_DEVICES": "-1"},
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode:
        raise PromptBudgetUnavailable("The local tokenizer could not verify the prompt budget")
    try:
        tokens = json.loads(result.stdout)
        if not isinstance(tokens, list) or any(type(token) is not int for token in tokens):
            raise ValueError("Invalid token list")
        return len(tokens)
    except (ValueError, TypeError) as error:
        raise PromptBudgetUnavailable("The local tokenizer returned an invalid measurement") from error


def enforce(messages: list[dict], schema: dict, *, thinking: bool, output_tokens: int) -> dict:
    model = profile("qwen")
    context = int(model["context_size"])
    if type(output_tokens) is not int or output_tokens <= 0 or output_tokens + HEADROOM >= context:
        raise PromptBudgetExceeded("The requested Qwen output reservation exceeds its context")
    try:
        chat = render_chat(messages, thinking=thinking, model=model)
        # Two counts keep the receipt explicit and avoid relying on character length.
        prompt_tokens = token_count(chat, model=model)
        schema_tokens = token_count(json.dumps(schema, ensure_ascii=False), model=model)
    except PromptBudgetUnavailable:
        raise
    except (OSError, ValueError, ImportError, subprocess.TimeoutExpired) as error:
        raise PromptBudgetUnavailable("The local Qwen prompt budget could not be verified") from error
    total = prompt_tokens + schema_tokens
    ceiling = min(INPUT_CEILING, context - output_tokens - HEADROOM)
    if total > ceiling:
        raise PromptBudgetExceeded(
            f"Qwen input needs {total} tokens including schema allowance; limit is {ceiling}. "
            "Evidence ranking remains available; no prompt was truncated.")
    return {"prompt_tokens": prompt_tokens, "schema_allowance_tokens": schema_tokens,
            "input_tokens": total, "input_ceiling": ceiling, "output_reserved": output_tokens,
            "headroom": HEADROOM, "context_tokens": context, "method": "gguf-template-and-tokenizer"}
