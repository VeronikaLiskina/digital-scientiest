def build_rag_context(chunks: list[dict]) -> str:
    context_parts: list[str] = []

    for index, chunk in enumerate(chunks, start=1):
        context_parts.append(
            "\n".join(
                [
                    f"[Источник {index}]",
                    f"Название публикации: {chunk.get('publication_title')}",
                    f"ID публикации: {chunk.get('publication_id')}",
                    f"ID фрагмента: {chunk.get('chunk_id')}",
                    f"Сходство: {chunk.get('similarity'):.3f}",
                    "Текст фрагмента:",
                    chunk.get("text", ""),
                ]
            )
        )

    return "\n\n".join(context_parts)


def build_rag_prompt(question: str, context: str) -> str:
    return (
        "Ты AI-ассистент системы «Цифровой учёный».\n"
        "Отвечай только на основе предоставленного контекста из научных публикаций.\n"
        "Если в контексте недостаточно информации, прямо скажи об этом.\n"
        "Не выдумывай факты.\n"
        "Ответ должен быть на русском языке, в научно-деловом стиле.\n\n"
        f"Контекст:\n{context}\n\n"
        f"Вопрос пользователя:\n{question}\n\n"
        "Ответ:"
    )