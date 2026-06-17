import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link } from "react-router-dom";

import { authorsApi } from "../../api/authorsApi";
import { keywordsApi } from "../../api/keywordsApi";
import {
  publicationsApi,
  type PublicationsFilters,
} from "../../api/publicationsApi";
import { topicsApi } from "../../api/topicsApi";
import { ListTitle } from "../../components/common/ListTitle";
import type { Author, Keyword, Publication, Topic } from "../../types/entities";
import { getPublicationTypeLabel } from "../../utils/publicationTypes";

const emptyFilters: PublicationsFilters = {
  title: "",
  year: "",
  author_id: "",
  topic_id: "",
  keyword_id: "",
};

export function ReaderPublicationsPage() {
  const [publications, setPublications] = useState<Publication[]>([]);
  const [authors, setAuthors] = useState<Author[]>([]);
  const [topics, setTopics] = useState<Topic[]>([]);
  const [keywords, setKeywords] = useState<Keyword[]>([]);
  const [filters, setFilters] = useState<PublicationsFilters>(emptyFilters);
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(true);

  async function loadPublications(currentFilters: PublicationsFilters = filters) {
    const data = await publicationsApi.getAll(currentFilters);
    setPublications(data);
  }

  useEffect(() => {
    Promise.all([
      authorsApi.getAll(),
      topicsApi.getAll(),
      keywordsApi.getAll(),
      publicationsApi.getAll(),
    ])
      .then(([authorsData, topicsData, keywordsData, publicationsData]) => {
        setAuthors(authorsData);
        setTopics(topicsData);
        setKeywords(keywordsData);
        setPublications(publicationsData);
      })
      .catch((err) => {
        setError(
          err instanceof Error
            ? err.message
            : "Не удалось загрузить данные для поиска",
        );
      })
      .finally(() => {
        setIsLoading(false);
      });
  }, []);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    try {
      setError("");
      setIsLoading(true);
      await loadPublications(filters);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Не удалось выполнить поиск",
      );
    } finally {
      setIsLoading(false);
    }
  }

  async function handleReset() {
    try {
      setError("");
      setIsLoading(true);
      setFilters(emptyFilters);
      await loadPublications(emptyFilters);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Не удалось сбросить фильтры",
      );
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <section className="reader-publications-page">
      <div className="page-header">
        <div>
          <h1>Публикации</h1>
          <p>Поиск и просмотр научных публикаций.</p>
        </div>
      </div>

      {error && <p className="error">{error}</p>}

      <section className="card page-section">
        <form className="reader-search-form" onSubmit={handleSubmit}>
          <div className="reader-search">
            <input
              className="reader-search__input"
              placeholder="Введите название публикации..."
              value={filters.title ?? ""}
              onChange={(event) =>
                setFilters((prev) => ({ ...prev, title: event.target.value }))
              }
            />
            <button className="button" type="submit" disabled={isLoading}>
              {isLoading ? "Ищем..." : "Найти"}
            </button>
          </div>

          <div className="reader-filters">
            <input
              placeholder="Год"
              value={filters.year ?? ""}
              onChange={(event) =>
                setFilters((prev) => ({ ...prev, year: event.target.value }))
              }
            />

            <select
              value={filters.author_id ?? ""}
              onChange={(event) =>
                setFilters((prev) => ({
                  ...prev,
                  author_id: event.target.value,
                }))
              }
            >
              <option value="">Все авторы</option>
              {authors.map((author) => (
                <option key={author.id} value={author.id}>
                  {author.full_name}
                </option>
              ))}
            </select>

            <select
              value={filters.topic_id ?? ""}
              onChange={(event) =>
                setFilters((prev) => ({
                  ...prev,
                  topic_id: event.target.value,
                }))
              }
            >
              <option value="">Все темы</option>
              {topics.map((topic) => (
                <option key={topic.id} value={topic.id}>
                  {topic.name}
                </option>
              ))}
            </select>

            <select
              value={filters.keyword_id ?? ""}
              onChange={(event) =>
                setFilters((prev) => ({
                  ...prev,
                  keyword_id: event.target.value,
                }))
              }
            >
              <option value="">Все ключевые слова</option>
              {keywords.map((keyword) => (
                <option key={keyword.id} value={keyword.id}>
                  {keyword.name}
                </option>
              ))}
            </select>
          </div>

          <div className="form-actions">
            <button className="button button_secondary" type="button" onClick={handleReset}>
              Сбросить
            </button>
          </div>
        </form>
      </section>

      <section className="card">
        <ListTitle count={publications.length} />

        <div className="reader-publication-list">
          {publications.map((publication) => (
            <article className="reader-publication-card" key={publication.id}>
              <div className="reader-publication-card__main">
                <h2>{publication.title}</h2>
                <p>
                  {publication.authors.map((author) => author.full_name).join(", ") ||
                    "Авторы не указаны"}
                </p>
                <p>
                  {publication.year ?? "год не указан"} · {getPublicationTypeLabel(publication.publication_type)}
                  {publication.doi ? ` · DOI: ${publication.doi}` : ""}
                </p>

                <div className="reader-publication-card__tags">
                  {publication.topics.map((topic) => (
                    <span key={`topic-${topic.id}`}>{topic.name}</span>
                  ))}
                  {publication.keywords.map((keyword) => (
                    <span key={`keyword-${keyword.id}`}>{keyword.name}</span>
                  ))}
                </div>
              </div>

              <Link className="button button_secondary" to={`/publications/${publication.id}`}>
                Открыть
              </Link>
            </article>
          ))}

          {!isLoading && !publications.length && (
            <p className="empty">Публикации не найдены.</p>
          )}

          {isLoading && <p className="muted">Загрузка...</p>}
        </div>
      </section>
    </section>
  );
}
