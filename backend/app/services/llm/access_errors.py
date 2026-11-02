from typing import Any

from app.services.llm.base import LLMAccessDeniedError, LLMConfigurationError, LocalLLMError


MODEL_PERMISSION_CODES = {"model_permission_blocked_org", "model_permission_blocked_project"}


def provider_access_error(response: Any, *, body: Any = None) -> LocalLLMError:
    """Keep only documented codes; provider bodies may repeat private prompts."""
    if body is None:
        try:
            body = response.json()
        except (ValueError, AttributeError):
            body = None
    error = body.get("error", body) if isinstance(body, dict) else None
    code = error.get("code") if isinstance(error, dict) else None
    known_permission = isinstance(code, str) and code in MODEL_PERMISSION_CODES
    if response.status_code == 403 and not known_permission:
        exc = LLMAccessDeniedError("API модели отклонил запрос: HTTP 403")
    else:
        exc = LLMConfigurationError(
            "Доступ к модели запрещён в настройках проекта или организации"
            if known_permission else "Проверьте адрес API, ключ и доступ к модели"
        )
    exc.provider_status = response.status_code
    exc.provider_error_code = code if known_permission else None
    return exc
