from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx
from openai import OpenAI

from local_gmail_agent.config import Settings
from local_gmail_agent.label_store import ManagedLabelConfig
from local_gmail_agent.schemas import (
    ClassificationPromptPayload,
    EmailMessage,
    LLMRawDecision,
    classification_json_schema,
)


LOGGER = logging.getLogger("local_gmail_agent")


def parse_json_response(content: str) -> dict[str, Any]:
    normalized = content.strip()
    if not normalized:
        raise ValueError("Model returned an empty response.")

    candidates = [
        normalized,
        _strip_code_fences(normalized),
        _strip_thinking_blocks(normalized),
    ]
    candidates.append(_strip_code_fences(candidates[-1]))

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed

    extracted = _extract_first_json_object(_strip_code_fences(_strip_thinking_blocks(normalized)))
    if extracted is not None:
        parsed = json.loads(extracted)
        if isinstance(parsed, dict):
            return parsed

    raise ValueError("Could not parse a JSON object from the model response.")


def _strip_code_fences(content: str) -> str:
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", content, flags=re.DOTALL)
    if fenced:
        return fenced.group(1).strip()
    return content


def _strip_thinking_blocks(content: str) -> str:
    without_think = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL | re.IGNORECASE)
    return without_think.strip()


def _extract_first_json_object(content: str) -> str | None:
    start = content.find("{")
    end = content.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    return content[start : end + 1]


class LMStudioClient:
    def __init__(self, settings: Settings, label_config: ManagedLabelConfig) -> None:
        self.settings = settings
        self.label_config = label_config
        self.openai_client = OpenAI(
            base_url=settings.lm_studio_openai_base_url,
            api_key=settings.llm_api_key,
            timeout=settings.llm_timeout_seconds,
        )
        self.http_client = httpx.Client(
            base_url=settings.lm_studio_native_base_url,
            timeout=settings.llm_timeout_seconds,
            headers=self._native_headers(),
        )
        self._resolved_model: str | None = settings.llm_model

    def classify_email(self, email: EmailMessage) -> LLMRawDecision:
        if self.settings.lm_studio_api_mode == "native":
            return self._classify_via_native_api(email)
        return self._classify_via_openai_compat(email)

    def _classify_via_openai_compat(self, email: EmailMessage) -> LLMRawDecision:
        response = self._create_openai_completion(email, use_schema=True)
        content = self._extract_openai_content(response)

        try:
            payload = parse_json_response(content)
        except ValueError:
            LOGGER.warning("Structured response was not valid JSON. Retrying in text mode.")
            response = self._create_openai_completion(email, use_schema=False)
            payload = parse_json_response(self._extract_openai_content(response))

        return LLMRawDecision.model_validate(payload)

    def _classify_via_native_api(self, email: EmailMessage) -> LLMRawDecision:
        response = self.http_client.post(
            "/chat",
            json={
                "model": self._resolve_model(),
                "input": self._user_prompt(email),
                "system_prompt": self._system_prompt(),
                "temperature": self.settings.llm_temperature,
                "top_p": self.settings.llm_top_p,
                "max_output_tokens": self.settings.llm_max_tokens,
                "context_length": self.settings.llm_context_length,
                "store": False,
            },
        )
        response.raise_for_status()
        payload = response.json()
        content = self._extract_native_content(payload)
        return LLMRawDecision.model_validate(parse_json_response(content))

    def _create_openai_completion(self, email: EmailMessage, use_schema: bool) -> Any:
        params: dict[str, Any] = {
            "model": self._resolve_model(),
            "messages": self._openai_messages(email),
            "temperature": self.settings.llm_temperature,
            "top_p": self.settings.llm_top_p,
            "max_tokens": self.settings.llm_max_tokens,
        }

        if self.settings.llm_seed is not None:
            params["seed"] = self.settings.llm_seed

        if use_schema:
            params["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "gmail_classification",
                    "schema": classification_json_schema(self.label_config.classification_labels),
                },
            }
        else:
            params["response_format"] = {"type": "text"}

        try:
            return self.openai_client.chat.completions.create(**params)
        except Exception as exc:
            if use_schema:
                LOGGER.warning(
                    "LM Studio rejected json_schema output: %s. Falling back to text mode.",
                    exc,
                )
                return self._create_openai_completion(email, use_schema=False)
            raise

    def _resolve_model(self) -> str:
        if self._resolved_model:
            return self._resolved_model

        if self.settings.lm_studio_api_mode == "native":
            response = self.http_client.get("/models")
            response.raise_for_status()
            models = response.json().get("models", [])
            llm_models = [model for model in models if model.get("type") == "llm"]
            if not llm_models:
                raise RuntimeError(
                    "No LLM model is available in LM Studio. Start the local server and load a model first."
                )
            self._resolved_model = llm_models[0]["key"]
        else:
            models = self.openai_client.models.list().data
            if not models:
                raise RuntimeError(
                    "No model is loaded in LM Studio. Start the local server and load a model first."
                )
            self._resolved_model = models[0].id

        LOGGER.info("Using LM Studio model: %s", self._resolved_model)
        return self._resolved_model

    def _openai_messages(self, email: EmailMessage) -> list[dict[str, str]]:
        return [
            {
                "role": "system",
                "content": self._system_prompt(),
            },
            {
                "role": "user",
                "content": self._user_prompt(email),
            },
        ]

    def _extract_openai_content(self, response: Any) -> str:
        message = response.choices[0].message
        content = message.content
        if isinstance(content, str):
            return content

        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(item.get("text", ""))
                elif hasattr(item, "text"):
                    parts.append(getattr(item, "text"))
            joined = "".join(parts).strip()
            if joined:
                return joined

        raise RuntimeError("LM Studio returned an empty response.")

    def _extract_native_content(self, response_payload: dict[str, Any]) -> str:
        output = response_payload.get("output", [])
        messages = [
            item.get("content", "")
            for item in output
            if item.get("type") == "message" and isinstance(item.get("content"), str)
        ]
        content = "\n".join(chunk for chunk in messages if chunk.strip()).strip()
        if not content:
            raise RuntimeError("LM Studio native API returned no message content.")
        return content

    def _system_prompt(self) -> str:
        return (
            "You classify Gmail emails for local labeling. "
            "Choose exactly one label from the allowed taxonomy. "
            "Set archive=true only when the email does not need a human reply or follow-up. "
            "Keep the reason concise and grounded in the email content. "
            "Return only a JSON object. Do not use markdown fences. "
            "Do not add commentary before or after the JSON."
        )

    def _user_prompt(self, email: EmailMessage) -> str:
        prompt_payload = ClassificationPromptPayload.from_email(
            email,
            allowed_labels=self.label_config.classification_labels,
        )
        return (
            "Classify this email using the following typed payload. "
            "Return a JSON object with the output_fields exactly as specified.\n\n"
            f"{prompt_payload.model_dump_json(indent=2)}"
        )

    def _native_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.settings.lm_studio_api_token:
            headers["Authorization"] = f"Bearer {self.settings.lm_studio_api_token}"
        return headers
