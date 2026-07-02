import { FormEvent, useState } from "react";
import { Link } from "react-router-dom";

import {
  assistantApi,
  type AssistantAskResponse,
} from "../../api/assistantApi";

function formatSimilarity(value: number) {
  return `${Math.round(value * 100)}%`;
}

export function ReaderAssistantPage() {
  const [query, setQuery] = useState("");
  const [response, setResponse] = useState<AssistantAskResponse | null>(null);
  const [submittedQuery, setSubmittedQuery] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const normalizedQuery = query.trim();

    if (normalizedQuery.length < 2) {
      setError("Введите запрос длиной не меньше двух символов.");
      return;
    }

    setIsLoading(true);
    setError(null);

    try {
      const assistantResponse = await assistantApi.ask({
        question: normalizedQuery,
        limit: 10,
        min_similarity: 0.55,
      });

      setSubmittedQuery(assistantResponse.question);
      setResponse(assistantResponse);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Не удалось получить ответ ассистента.",
      );
      setResponse(null);
      setSubmittedQuery(normalizedQuery);
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <section className="reader-assistant-page">
      <div className="page-header">
        <div>
          <h1>Ассистент по материалам</h1>
          <p>
            Задайте вопрос по базе публикаций и получите подборку релевантных
            фрагментов с источниками.
          </p>
        </div>
      </div>

      <form className="card reader-assistant" onSubmit={handleSubmit}>
        <textarea
          className="reader-assistant__textarea"
          placeholder="Например: Какие публикации есть по магматизму?"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />

        <div className="reader-assistant__actions">
          <button className="button" type="submit" disabled={isLoading}>
            {isLoading ? "Ассистент думает..." : "Задать вопрос"}
          </button>

          {submittedQuery && (
            <span className="reader-assistant__query">
              Запрос: {submittedQuery}
            </span>
          )}
        </div>

        {error && <p className="message message--error">{error}</p>}

        <div className="reader-assistant__answer">
          {response ? (
            <>
              {response.answer.trim() && <p>{response.answer}</p>}

              {response.sources.length > 0 && (
                <div className="reader-assistant__results">
                  {response.sources.map((source) => (
                    <article
                      className="reader-assistant__result"
                      key={source.chunk_id}
                    >
                      <div className="reader-assistant__result-header">
                        <Link
                          to={`/publications/${source.publication_id}`}
                          className="reader-assistant__source"
                        >
                          {source.publication_title ??
                            `Публикация #${source.publication_id}`}
                        </Link>

                        <span>
                          Сходство {formatSimilarity(source.similarity)}
                        </span>
                      </div>

                      <p>
                        {source.text ??
                          `Фрагмент #${source.chunk_id}${
                            source.chunk_index !== null &&
                            source.chunk_index !== undefined
                              ? `, индекс ${source.chunk_index}`
                              : ""
                          }`}
                      </p>
                    </article>
                  ))}
                </div>
              )}
            </>
          ) : submittedQuery ? (
            <p className="empty">
              Ответ не получен. Проверьте текст ошибки выше и попробуйте еще раз.
            </p>
          ) : (
            <p className="empty">
              Ответ появится здесь после вопроса по публикациям.
            </p>
          )}
        </div>
      </form>
    </section>
  );
}
