import { FormEvent, useState } from "react";
import { Link } from "react-router-dom";

import {
  semanticSearchApi,
  type SemanticSearchResponse,
} from "../../api/semanticSearchApi";

function formatSimilarity(value: number) {
  return `${Math.round(value * 100)}%`;
}

export function ReaderSemanticSearchPage() {
  const [query, setQuery] = useState("");
  const [response, setResponse] = useState<SemanticSearchResponse | null>(null);
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
      const searchResponse = await semanticSearchApi.search({
        query: normalizedQuery,
        limit: 10,
        minSimilarity: 0.55,
      });

      setSubmittedQuery(searchResponse.query);
      setResponse(searchResponse);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Не удалось выполнить семантический поиск.",
      );
      setResponse(null);
      setSubmittedQuery(normalizedQuery);
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <section className="reader-semantic-search-page">
      <div className="page-header">
        <div>
          <h1>Семантический поиск</h1>
          <p>
            Найдите релевантные фрагменты публикаций по смыслу запроса без
            генерации ответа ассистента.
          </p>
        </div>
      </div>

      <form className="card reader-assistant" onSubmit={handleSubmit}>
        <textarea
          className="reader-assistant__textarea"
          placeholder="Например: исследования магматизма и геохимические маркеры"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />

        <div className="reader-assistant__actions">
          <button className="button" type="submit" disabled={isLoading}>
            {isLoading ? "Ищем..." : "Найти фрагменты"}
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
            response.results.length > 0 ? (
              <div className="reader-assistant__results reader-assistant__results_plain">
                {response.results.map((result) => (
                  <article
                    className="reader-assistant__result"
                    key={result.chunk_id}
                  >
                    <div className="reader-assistant__result-header">
                      <Link
                        to={`/publications/${result.publication_id}?chunk=${result.chunk_id}`}
                        className="reader-assistant__source"
                      >
                        {result.publication_title ||
                          `Публикация #${result.publication_id}`}
                      </Link>

                      <span>Сходство {formatSimilarity(result.similarity)}</span>
                    </div>

                    <p>{result.text}</p>
                  </article>
                ))}
              </div>
            ) : (
              <p className="empty">По этому запросу фрагменты не найдены.</p>
            )
          ) : submittedQuery ? (
            <p className="empty">
              Результаты не получены. Проверьте текст ошибки выше и попробуйте
              еще раз.
            </p>
          ) : (
            <p className="empty">
              Релевантные фрагменты появятся здесь после поиска.
            </p>
          )}
        </div>
      </form>
    </section>
  );
}
