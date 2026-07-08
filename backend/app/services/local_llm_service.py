import re

import httpx

from app.core.config import settings


CHINESE_RE = re.compile(r"[\u4e00-\u9fff]")

RAG_SYSTEM_PROMPT = (
    "Ты AI-ассистент системы «Цифровой учёный».\n"
    "Ты работаешь по подходу RAG: Retrieval-Augmented Generation.\n"
    "Отвечай на том же языке, на котором задан вопрос пользователя.\n"
    "Если вопрос на русском, отвечай только на русском.\n"
    "Если вопрос на английском, отвечай только на английском.\n"
    "Категорически запрещено использовать китайский язык, китайские иероглифы "
    "или китайские пояснения, если пользователь сам не задал вопрос на китайском.\n"
    "Не смешивай языки.\n"
    "Не выдумывай факты.\n"
    "Отвечай только на основе предоставленного контекста из научных публикаций.\n"
    "Если в контексте недостаточно информации, прямо скажи об этом "
    "на языке вопроса пользователя."
)

GENERAL_SYSTEM_PROMPT = (
    "Ты AI-ассистент системы «Цифровой учёный».\n"
    "Отвечай на том же языке, на котором задан вопрос пользователя.\n"
    "Если вопрос на русском, отвечай только на русском.\n"
    "Если вопрос на английском, отвечай только на английском.\n"
    "Категорически запрещено использовать китайский язык, китайские иероглифы "
    "или китайские пояснения, если пользователь сам не задал вопрос на китайском.\n"
    "Не смешивай языки.\n"
    "Можно дать короткую справочную информацию из общих знаний, если prompt явно говорит, "
    "что в материалах цифрового архива не найдено релевантных фрагментов.\n"
    "Не выдумывай точные данные, даты и источники. Если не уверен, формулируй осторожно."
)


class LocalLLMService:
    def __init__(self) -> None:
        self.base_url = settings.ollama_base_url.rstrip("/")
        self.model = settings.ollama_model
        self.timeout = settings.ollama_timeout_seconds

    async def generate_answer(
        self,
        prompt: str,
        *,
        allow_general_knowledge: bool = False,
    ) -> str:
        system_prompt = (
            GENERAL_SYSTEM_PROMPT if allow_general_knowledge else RAG_SYSTEM_PROMPT
        )
        answer = await self._request_ollama(prompt, system_prompt=system_prompt)

        if CHINESE_RE.search(answer):
            retry_prompt = (
                "Предыдущий ответ содержал китайские символы. "
                "Перепиши ответ полностью без китайского языка и без китайских иероглифов. "
                "Сохрани смысл, не добавляй новых фактов и отвечай строго на языке вопроса пользователя.\n\n"
                f"{prompt}"
            )
            answer = await self._request_ollama(
                retry_prompt,
                system_prompt=system_prompt,
            )

        return answer

    async def _request_ollama(self, prompt: str, *, system_prompt: str) -> str:
        url = f"{self.base_url}/api/chat"

        payload = {
            "model": self.model,
            "stream": False,
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            "options": {
                "temperature": 0.1,
                "top_p": 0.8,
                "repeat_penalty": 1.1,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
        except httpx.ConnectError as exc:
            raise RuntimeError(
                "Ollama не запущена или недоступна по адресу http://127.0.0.1:11434"
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"Ошибка ответа Ollama: {exc.response.status_code}"
            ) from exc

        data = response.json()

        try:
            return data["message"]["content"]
        except KeyError as exc:
            raise RuntimeError("Ollama вернула неожиданный формат ответа") from exc
