import { FormEvent, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import {
  semanticSearchApi,
  type SemanticSearchResult,
} from "../../api/semanticSearchApi";

function formatSimilarity(value: number) {
  return `${Math.round(value * 100)}%`;
}

function buildSummary(results: SemanticSearchResult[]) {
  if (results.length === 0) {
    return "По базе публикаций не найдено достаточно близких фрагментов.";
  }

  const publicationCount = new Set(
    results.map((result) => result.publication_id),
  ).size;

  return `Найдено ${results.length} релевантных фрагментов в ${publicationCount} публикациях. Ниже показаны наиболее близкие совпадения и источники.`;
}

export function ReaderAssistantPage() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SemanticSearchResult[]>([]);
  const [submittedQuery, setSubmittedQuery] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const answer = useMemo(() => buildSummary(results), [results]);

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
      const response = await semanticSearchApi.search({
        query: normalizedQuery,
        limit: 10,
        minSimilarity: 0.55,
      });

      setSubmittedQuery(response.query);
      setResults(response.results);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Не удалось выполнить семантический поиск.",
      );
      setResults([]);
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
            {isLoading ? "Идет поиск..." : "Задать вопрос"}
          </button>

          {submittedQuery && (
            <span className="reader-assistant__query">
              Запрос: {submittedQuery}
            </span>
          )}
        </div>

        {error && <p className="message message--error">{error}</p>}

        <div className="reader-assistant__answer">
          {submittedQuery ? (
            <>
              <p>{answer}</p>

              {results.length > 0 && (
                <div className="reader-assistant__results">
                  {results.map((result) => (
                    <article
                      className="reader-assistant__result"
                      key={result.chunk_id}
                    >
                      <div className="reader-assistant__result-header">
                        <Link
                          to={`/publications/${result.publication_id}`}
                          className="reader-assistant__source"
                        >
                          {result.publication_title}
                        </Link>

                        <span>
                          Сходство {formatSimilarity(result.similarity)}
                        </span>
                      </div>

                      <p>{result.text}</p>
                    </article>
                  ))}
                </div>
              )}
            </>
          ) : (
            <p className="empty">
              Ответ появится здесь после поиска по публикациям.
            </p>
          )}
        </div>
      </form>
    </section>
  );
}
