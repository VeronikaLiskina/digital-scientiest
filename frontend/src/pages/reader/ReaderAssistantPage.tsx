import { FormEvent, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import {
  assistantApi,
  type AssistantAskResponse,
  type AssistantSource,
} from "../../api/assistantApi";

const EXAMPLE_QUESTIONS = [
  "Какие публикации есть по магматизму?",
];

function formatSimilarity(value: number) {
  return `${Math.round(value * 100)}%`;
}

function formatChunkMeta(source: AssistantSource) {
  if (source.chunk_index === null || source.chunk_index === undefined) {
    return `Фрагмент #${source.chunk_id}`;
  }

  return `Фрагмент #${source.chunk_id}, индекс ${source.chunk_index}`;
}

function getSourceText(source: AssistantSource) {
  return source.text?.trim() || formatChunkMeta(source);
}

function getSourceLink(source: AssistantSource) {
  return {
    pathname: `/publications/${source.publication_id}`,
    search: `?source=assistant&chunk=${source.chunk_id}`,
    hash: `#chunk-${source.chunk_id}`,
  };
}

function normalizeErrorMessage(err: unknown) {
  if (err instanceof Error && err.message.trim()) {
    if (err.message.includes("500")) {
      return "Ассистент сейчас не смог получить данные из базы. Проверьте подключение backend к PostgreSQL и попробуйте еще раз.";
    }

    return err.message;
  }

  return "Не удалось получить ответ ассистента. Попробуйте еще раз.";
}

export function ReaderAssistantPage() {
  const [query, setQuery] = useState("");
  const [response, setResponse] = useState<AssistantAskResponse | null>(null);
  const [submittedQuery, setSubmittedQuery] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canSubmit = query.trim().length >= 2 && !isLoading;
  const sourceCount = response?.sources.length ?? 0;
  const answerText = response?.answer.trim();

  const topSources = useMemo(
    () => response?.sources.slice(0, 3) ?? [],
    [response],
  );

  function useExample(question: string) {
    setQuery(question);
    setError(null);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const normalizedQuery = query.trim();

    if (normalizedQuery.length < 2) {
      setError("Введите запрос длиной не меньше двух символов.");
      return;
    }

    setIsLoading(true);
    setError(null);
    setSubmittedQuery(normalizedQuery);

    try {
      const assistantResponse = await assistantApi.ask({
        question: normalizedQuery,
        limit: 10,
        min_similarity: 0.55,
      });

      setSubmittedQuery(assistantResponse.question);
      setResponse(assistantResponse);
    } catch (err) {
      setError(normalizeErrorMessage(err));
      setResponse(null);
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
            Задайте вопрос по базе публикаций и получите ответ с релевантными
            источниками для быстрой проверки.
          </p>
        </div>
      </div>

      <form className="card reader-assistant" onSubmit={handleSubmit}>
        <div className="reader-assistant__composer">
          <label className="reader-assistant__label" htmlFor="assistant-query">
            Вопрос
          </label>

          <textarea
            id="assistant-query"
            className="reader-assistant__textarea"
            placeholder="Например: какие публикации есть по магматизму?"
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setError(null);
            }}
          />

          <div className="reader-assistant__examples" aria-label="Примеры запросов">
            {EXAMPLE_QUESTIONS.map((question) => (
              <button
                className="reader-assistant__example"
                type="button"
                key={question}
                onClick={() => useExample(question)}
              >
                {question}
              </button>
            ))}
          </div>
        </div>

        <div className="reader-assistant__actions">
          <button className="button" type="submit" disabled={!canSubmit}>
            {isLoading ? "Готовлю ответ..." : "Задать вопрос"}
          </button>

          {submittedQuery && (
            <span className="reader-assistant__query">
              Последний запрос: {submittedQuery}
            </span>
          )}
        </div>

        {error && (
          <div className="message message--error reader-assistant__error" role="alert">
            <strong>Ответ не получен.</strong>
            <span>{error}</span>
          </div>
        )}

        <div className="reader-assistant__answer" aria-live="polite">
          {isLoading ? (
            <div className="reader-assistant__loading">
              <span className="reader-assistant__spinner" aria-hidden="true" />
              <div>
                <strong>Ищу фрагменты и формирую ответ</strong>
                <p>
                  Обычно это занимает немного времени: ассистент сначала ищет
                  источники, затем собирает ответ по найденному контексту.
                </p>
              </div>
            </div>
          ) : response ? (
            <div className="reader-assistant__response">
              <div className="reader-assistant__answer-header">
                <div>
                  <span className="reader-assistant__eyebrow">Ответ</span>
                  <h2>По вашему вопросу</h2>
                </div>
                <span className="reader-assistant__source-count">
                  {sourceCount} источников
                </span>
              </div>

              {answerText ? (
                <p className="reader-assistant__answer-text">{answerText}</p>
              ) : (
                <p className="empty">
                  Ассистент вернул источники, но не сформировал текст ответа.
                </p>
              )}

              {topSources.length > 0 && (
                <div className="reader-assistant__source-strip">
                  {topSources.map((source) => (
                    <Link
                      to={getSourceLink(source)}
                      className="reader-assistant__source-chip"
                      key={source.chunk_id}
                    >
                      {source.publication_title ||
                        `Публикация #${source.publication_id}`}
                    </Link>
                  ))}
                </div>
              )}

              {response.sources.length > 0 ? (
                <div className="reader-assistant__results">
                  {response.sources.map((source) => (
                    <article
                      className="reader-assistant__result"
                      key={source.chunk_id}
                    >
                      <div className="reader-assistant__result-header">
                        <div>
                          <Link
                            to={getSourceLink(source)}
                            className="reader-assistant__source"
                          >
                            {source.publication_title ||
                              `Публикация #${source.publication_id}`}
                          </Link>
                          <span className="reader-assistant__meta">
                            {formatChunkMeta(source)}
                          </span>
                        </div>

                        <span className="reader-assistant__score">
                          Сходство {formatSimilarity(source.similarity)}
                        </span>
                      </div>

                      <p>{getSourceText(source)}</p>

                      <div className="reader-assistant__result-actions">
                        <Link
                          className="reader-assistant__fragment-link"
                          to={getSourceLink(source)}
                        >
                          Открыть этот фрагмент
                        </Link>
                      </div>
                    </article>
                  ))}
                </div>
              ) : (
                <p className="empty">
                  В базе не найдено достаточно релевантных фрагментов для ответа.
                </p>
              )}
            </div>
          ) : submittedQuery ? (
            <p className="empty">
              Ответ не получен. Проверьте сообщение выше и повторите запрос.
            </p>
          ) : (
            <div className="reader-assistant__empty">
              <strong>Задайте вопрос, чтобы начать</strong>
              <p>
                Ответ появится здесь вместе со ссылками на публикации, на
                которые опирался ассистент.
              </p>
            </div>
          )}
        </div>
      </form>
    </section>
  );
}
