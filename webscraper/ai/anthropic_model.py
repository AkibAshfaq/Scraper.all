"""Claude via the official Anthropic SDK.

Credentials resolve the SDK's usual way: ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN,
or an `ant auth login` profile.
"""

from __future__ import annotations

import logging
from typing import Iterator

import anthropic

from webscraper.ai.base import ChatError, ChatModel, ChatTurn

log = logging.getLogger(__name__)

# Refusal fallbacks: if Claude's safety classifiers decline, the API re-runs the
# request on Anthropic's recommended fallback model inside the same call.
FALLBACK_BETA = "server-side-fallback-2026-07-01"

NOT_CONFIGURED = (
    "AI chat isn't set up: no Anthropic credentials found. "
    "Set ANTHROPIC_API_KEY and restart the server."
)


class AnthropicChatModel(ChatModel):
    def __init__(self, model: str = "claude-opus-5-5", effort: str = "medium", max_tokens: int = 16000) -> None:
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens
        self._client: anthropic.Anthropic | None = None

    def stream(self, instructions: str, context: str, turns: list[ChatTurn]) -> Iterator[str]:
        system = [
            {"type": "text", "text": instructions},
            # Breakpoint after the documents: follow-up questions about the same
            # search reuse the cached prefix instead of re-billing it.
            {"type": "text", "text": context, "cache_control": {"type": "ephemeral"}},
        ]
        messages = [{"role": t.role, "content": t.content} for t in turns]
        try:
            with self._get_client().beta.messages.stream(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system,
                messages=messages,
                output_config={"effort": self.effort},
                betas=[FALLBACK_BETA],
                fallbacks="default",
            ) as stream:
                yield from stream.text_stream
                final = stream.get_final_message()
        except anthropic.AuthenticationError as exc:
            raise ChatError("The Anthropic API key was rejected. Check ANTHROPIC_API_KEY.") from exc
        except anthropic.PermissionDeniedError as exc:
            raise ChatError(f"The API key can't use {self.model}.") from exc
        except anthropic.RateLimitError as exc:
            raise ChatError("The AI service is rate-limiting requests. Wait a moment and try again.") from exc
        except anthropic.APIStatusError as exc:
            raise ChatError(f"The AI service returned an error ({exc.status_code}). Try again.") from exc
        except anthropic.APIConnectionError as exc:
            raise ChatError("Couldn't reach the AI service. Check your internet connection.") from exc
        except TypeError as exc:
            # The SDK raises TypeError at request time when no credentials resolve.
            if "authentication" not in str(exc).lower():
                raise
            raise ChatError(NOT_CONFIGURED) from exc

        usage = final.usage
        log.info(
            "chat reply: %s in, %s cached, %s out",
            usage.input_tokens, usage.cache_read_input_tokens, usage.output_tokens,
        )
        if final.stop_reason == "refusal":
            raise ChatError("The AI declined to answer this request.")
        if final.stop_reason == "max_tokens":
            yield "\n\n*(Reply cut off at the length limit. Ask me to continue.)*"

    def _get_client(self) -> anthropic.Anthropic:
        if self._client is None:
            try:
                self._client = anthropic.Anthropic()
            except anthropic.AnthropicError as exc:
                raise ChatError(NOT_CONFIGURED) from exc
        return self._client
