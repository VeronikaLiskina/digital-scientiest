import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { publicationsApi } from "../../api/publicationsApi";
import { sourceFilesApi } from "../../api/sourceFilesApi";
import { PageHeader } from "../../components/common/PageHeader";
import type { Publication } from "../../types/entities";
import { getPublicationTypeLabel } from "../../utils/publicationTypes";

export function ReaderPublicationDetailsPage() {
  const { publicationId } = useParams();
  const id = Number(publicationId);

  const [publication, setPublication] = useState<Publication | null>(null);
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    if (!id) return;

    setIsLoading(true);

    publicationsApi
      .getOne(id)
      .then(setPublication)
      .catch((err) => {
        setError(
          err instanceof Error
            ? err.message
            : "Не удалось загрузить публикацию",
        );
      })
      .finally(() => {
        setIsLoading(false);
      });
  }, [id]);

  if (error) {
    return <p className="error">{error}</p>;
  }

  if (isLoading || !publication) {
    return <p className="muted">Загрузка...</p>;
  }

  return (
    <section className="reader-publication-details-page">
      <PageHeader
        title={publication.title}
        description="Карточка публикации для просмотра."
        actions={
          <div className="form-actions">
            {publication.source_file_id ? (
              <a
                className="button"
                href={sourceFilesApi.getDownloadUrl(publication.source_file_id)}
                target="_blank"
                rel="noreferrer"
              >
                Открыть PDF
              </a>
            ) : (
              <span className="muted">PDF не привязан</span>
            )}

            <Link className="button button_secondary" to="/publications">
              К списку
            </Link>
          </div>
        }
      />

      <section className="card page-section details">
        <h2>Основная информация</h2>

        <dl>
          <dt>Год</dt>
          <dd>{publication.year ?? "—"}</dd>

          <dt>Язык</dt>
          <dd>{publication.language ?? "—"}</dd>

          <dt>Тип</dt>
          <dd>{getPublicationTypeLabel(publication.publication_type)}</dd>

          <dt>DOI</dt>
          <dd>{publication.doi ?? "—"}</dd>

          <dt>Авторы</dt>
          <dd>
            {publication.authors.map((author) => author.full_name).join(", ") ||
              "—"}
          </dd>

          <dt>Темы</dt>
          <dd>{publication.topics.map((topic) => topic.name).join(", ") || "—"}</dd>

          <dt>Ключевые слова</dt>
          <dd>
            {publication.keywords.map((keyword) => keyword.name).join(", ") ||
              "—"}
          </dd>
        </dl>
      </section>
    </section>
  );
}
