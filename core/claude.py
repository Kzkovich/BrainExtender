import json
from typing import Optional

import anthropic

from config.settings import settings
from core.quotas import log_usage

_client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)


def _calc_cost(tokens_in: int, tokens_out: int) -> float:
    return (
        tokens_in * settings.CLAUDE_INPUT_PRICE_PER_1M / 1_000_000
        + tokens_out * settings.CLAUDE_OUTPUT_PRICE_PER_1M / 1_000_000
    )


async def call_claude(
    system: str,
    user_message: str,
    user_id: str,
    operation: str,
    model: "Optional[str]" = None,
    json_mode: bool = False,
) -> tuple[str, float]:
    """
    Returns (response_text, cost_usd).
    Logs usage automatically.
    """
    m = model or settings.DEFAULT_MODEL

    extra = {}
    if json_mode:
        extra["system"] = system + "\n\nОтвечай ТОЛЬКО валидным JSON без дополнительного текста."

    response = _client.messages.create(
        model=m,
        max_tokens=4096,
        system=extra.get("system", system),
        messages=[{"role": "user", "content": user_message}],
    )

    text = response.content[0].text
    tokens_in = response.usage.input_tokens
    tokens_out = response.usage.output_tokens
    cost = _calc_cost(tokens_in, tokens_out)

    await log_usage(user_id, operation, tokens_in, tokens_out, m, cost)
    return text, cost


async def call_claude_vision(
    system: str,
    image_b64: str,
    media_type: str,
    user_id: str,
    model: Optional[str] = None,
) -> tuple[str, float]:
    """Send image to Claude Vision. Returns (description, cost_usd)."""
    m = model or settings.DEFAULT_MODEL

    response = _client.messages.create(
        model=m,
        max_tokens=2048,
        system=system,
        messages=[{
            "role": "user",
            "content": [{
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": image_b64,
                },
            }],
        }],
    )

    text = response.content[0].text
    tokens_in = response.usage.input_tokens
    tokens_out = response.usage.output_tokens
    cost = _calc_cost(tokens_in, tokens_out)

    await log_usage(user_id, "ingest", tokens_in, tokens_out, m, cost)
    return text, cost
