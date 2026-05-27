import json

from openai import OpenAI


class OpenAIClient:
    def __init__(
        self,
        api_key: str,
        default_extraction_model: str,
        default_reasoning_model: str,
    ):
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is not set. Copy .env.example to .env and fill it in."
            )
        self._client = OpenAI(api_key=api_key)
        self.default_extraction_model = default_extraction_model
        self.default_reasoning_model = default_reasoning_model

    def extract_structured(
        self,
        system: str,
        user: str,
        schema: dict,
        *,
        model: str | None = None,
    ) -> dict:
        response = self._client.responses.create(
            model=model or self.default_extraction_model,
            input=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "extraction",
                    "schema": schema,
                    "strict": True,
                }
            },
        )
        return json.loads(response.output_text or "{}")

    def reason(
        self,
        system: str,
        user: str,
        *,
        model: str | None = None,
    ) -> str:
        response = self._client.responses.create(
            model=model or self.default_reasoning_model,
            input=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return response.output_text or ""
