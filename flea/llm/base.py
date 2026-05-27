from typing import Protocol


class LLMClient(Protocol):
    """Provider-agnostic LLM interface.

    Two methods cover the project's needs:
      extract_structured -> cheap model, returns JSON conforming to a schema
      reason             -> better model, returns free-form text
    Each method accepts an optional `model` override; otherwise the client's
    pre-configured default for that role is used.
    """

    def extract_structured(
        self,
        system: str,
        user: str,
        schema: dict,
        *,
        model: str | None = None,
    ) -> dict: ...

    def reason(
        self,
        system: str,
        user: str,
        *,
        model: str | None = None,
    ) -> str: ...
