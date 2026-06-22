import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { authorsApi } from "../api/authorsApi";
import { keywordsApi } from "../api/keywordsApi";
import { publicationsApi, type PublicationsFilters } from "../api/publicationsApi";
import { ListTitle } from "../components/common/ListTitle";
import { PageHeader } from "../components/common/PageHeader";
import { StatusBadge } from "../components/common/StatusBadge";
import type { Author, Keyword, Publication } from "../types/entities";
import { getPublicationTypeLabel } from "../utils/publicationTypes";

export function PublicationsPage() {
  const [publications, setPublications] = useState<Publication[]>([]);
  const [authors, setAuthors] = useState<Author[]>([]);
  const [keywords, setKeywords] = useState<Keyword[]>([]);
  const [filters, setFilters] = useState<PublicationsFilters>({});
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(true);

  async function loadPublications(currentFilters = filters) {
    const data = await publicationsApi.getAll(currentFilters);
    setPublications(data);
  }

  useEffect(() => {
    Promise.all([authorsApi.getAll(), keywordsApi.getAll()])
      .then(([authorsData, keywordsData]) => {
        setAuthors(authorsData);
        setKeywords(keywordsData);
      })
      .catch(() => setError("Не удалось загрузить справочники"));
  }, []);

  useEffect(() => {
    setIsLoading(true);
    loadPublications()
      .catch(() => setError("Не удалось загрузить публикации"))
      .finally(() => setIsLoading(false));
  }, []);

  async function handleFilterChange(nextFilters: PublicationsFilters) {
    setFilters(nextFilters);
    await loadPublications(nextFilters);
  }

  async function handleDelete(publication: Publication) {
    const confirmed = confirm(`Удалить публикацию "${publication.title}"?`);

    if (!confirmed) return;

    try {
      setError("");
      await publicationsApi.delete(publication.id);
      await loadPublications();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось удалить публикацию");
    }
  }

  return (
    <section className="publications-page">
      <PageHeader
        title="Публикации"
        description="Список карточек научных публикаций."
        actions={
          <div className="form-actions">
            <Link className="button button_secondary" to="/admin">
              На главную
            </Link>
            <Link className="button" to="/admin/publications/new">
              Добавить публикацию
            </Link>
          </div>
        }
      />

      {error && <p className="error">{error}</p>}

      <section className="card">
        <div className="publications-page__filters">
          <input
            placeholder="Поиск по названию"
            value={filters.title ?? ""}
            onChange={(event) =>
              handleFilterChange({ ...filters, title: event.target.value }).catch(() =>
                setError("Не удалось применить фильтры"),
              )
            }
          />

          <input
            placeholder="Год"
            value={filters.year ?? ""}
            onChange={(event) =>
              handleFilterChange({ ...filters, year: event.target.value }).catch(() =>
                setError("Не удалось применить фильтры"),
              )
            }
          />

          <select
            value={filters.author_id ?? ""}
            onChange={(event) =>
              handleFilterChange({ ...filters, author_id: event.target.value }).catch(() =>
                setError("Не удалось применить фильтры"),
              )
            }
          >
            <option value="">Автор</option>
            {authors.map((author) => (
              <option key={author.id} value={author.id}>
                {author.full_name}
              </option>
            ))}
          </select>

          <select
            value={filters.keyword_id ?? ""}
            onChange={(event) =>
              handleFilterChange({ ...filters, keyword_id: event.target.value }).catch(() =>
                setError("Не удалось применить фильтры"),
              )
            }
          >
            <option value="">Ключевое слово</option>
            {keywords.map((keyword) => (
              <option key={keyword.id} value={keyword.id}>
                {keyword.name}
              </option>
            ))}
          </select>
        </div>

        <ListTitle count={publications.length} />

        <div className="table-wrapper">
          <table>
            <thead>
              <tr>
                <th>Название</th>
                <th>Год</th>
                <th>Тип</th>
                <th>Авторы</th>
                <th>Статус</th>
                <th>Действия</th>
              </tr>
            </thead>

            <tbody>
              {publications.map((publication) => (
                <tr key={publication.id}>
                  <td>{publication.title}</td>
                  <td>{publication.year ?? "—"}</td>
                  <td>{getPublicationTypeLabel(publication.publication_type)}</td>
                  <td>{publication.authors.map((author) => author.full_name).join(", ") || "—"}</td>
                  <td>
                    <StatusBadge value={publication.status} />
                  </td>
                  <td>
                    <div className="table-actions">
                      <Link className="button button_secondary" to={`/admin/publications/${publication.id}`}>
                        Открыть
                      </Link>
                      <button
                        className="button button_danger"
                        type="button"
                        onClick={() => handleDelete(publication)}
                      >
                        Удалить
                      </button>
                    </div>
                  </td>
                </tr>
              ))}

              {!isLoading && !publications.length && (
                <tr>
                  <td colSpan={6} className="empty">
                    Публикации пока не добавлены.
                  </td>
                </tr>
              )}

              {isLoading && (
                <tr>
                  <td colSpan={6} className="muted">
                    Загрузка...
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </section>
  );
}
