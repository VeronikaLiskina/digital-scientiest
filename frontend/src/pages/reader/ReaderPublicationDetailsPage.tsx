import { useEffect, useMemo, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";

import { documentChunksApi } from "../../api/documentChunksApi";
import { publicationsApi } from "../../api/publicationsApi";
import { sourceFilesApi } from "../../api/sourceFilesApi";
import { PageHeader } from "../../components/common/PageHeader";
import type { DocumentChunk, Publication } from "../../types/entities";
import { getPublicationTypeLabel } from "../../utils/publicationTypes";

function getChunkText(chunk: DocumentChunk) {
  return chunk.text ?? chunk.chunk_text ?? "";
}

function getSelectedChunkId(search: string, hash: string) {
  const params = new URLSearchParams(search);
  const chunkFromSearch = Number(params.get("chunk"));

  if (Number.isFinite(chunkFromSearch) && chunkFromSearch > 0) {
    return chunkFromSearch;
  }

  const chunkFromHash = Number(hash.replace("#chunk-", ""));

  if (Number.isFinite(chunkFromHash) && chunkFromHash > 0) {
    return chunkFromHash;
  }

  return null;
}

export function ReaderPublicationDetailsPage() {
  const { publicationId } = useParams();
  const { search, hash } = useLocation();
  const id = Number(publicationId);

  const [publication, setPublication] = useState<Publication | null>(null);
  const [chunks, setChunks] = useState<DocumentChunk[]>([]);
  const [error, setError] = useState("");
  const [chunkError, setChunkError] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isChunksLoading, setIsChunksLoading] = useState(true);

  const selectedChunkId = useMemo(
    () => getSelectedChunkId(search, hash),
    [search, hash],
  );
  const isAssistantSource = new URLSearchParams(search).get("source") === "assistant";

  useEffect(() => {
    if (!id) return;

    setIsLoading(true);
    setIsChunksLoading(true);
    setError("");
    setChunkError("");

    publicationsApi
      .getOne(id)
      .then((data) => {
        setPublication(data);
        setIsLoading(false);

        return documentChunksApi
          .getAll(data.id)
          .then(setChunks)
          .catch((err) => {
            setChunks([]);
            setChunkError(
              err instanceof Error
                ? err.message
                : "Не удалось загрузить фрагменты публикации",
            );
          });
      })
      .catch((err) => {
        setError(
          err instanceof Error
            ? err.message
            : "Не удалось загрузить публикацию",
        );
      })
      .finally(() => {
        setIsLoading(false);
        setIsChunksLoading(false);
      });
  }, [id]);

  useEffect(() => {
    if (!selectedChunkId || isChunksLoading) return;

    const target = document.getElementById(`chunk-${selectedChunkId}`);

    if (target) {
      target.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [isChunksLoading, selectedChunkId, chunks.length]);

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

      {isAssistantSource && selectedChunkId && (
        <div className="reader-source-context">
          <strong>Источник из ответа ассистента</strong>
          <span>
            Открыт фрагмент #{selectedChunkId}. Он подсвечен ниже в списке
            текстовых фрагментов.
          </span>
        </div>
      )}

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

      <section className="card page-section reader-source-fragments">
        <div className="reader-source-fragments__header">
          <div>
            <h2>Текстовые фрагменты</h2>
            <p>
              Эти фрагменты используются поиском и ассистентом как проверяемые
              источники.
            </p>
          </div>

          <span>{chunks.length} фрагментов</span>
        </div>

        {chunkError && <p className="error">{chunkError}</p>}

        {isChunksLoading ? (
          <p className="muted">Загрузка фрагментов...</p>
        ) : chunks.length > 0 ? (
          <div className="reader-source-fragments__list">
            {chunks.map((chunk) => {
              const isSelected = chunk.id === selectedChunkId;

              return (
                <article
                  className={
                    isSelected
                      ? "reader-source-fragment reader-source-fragment_selected"
                      : "reader-source-fragment"
                  }
                  id={`chunk-${chunk.id}`}
                  key={chunk.id}
                >
                  <div className="reader-source-fragment__header">
                    <h3>Фрагмент {chunk.chunk_index ?? chunk.id}</h3>
                    {isSelected && <span>Источник ответа</span>}
                  </div>

                  <p>{getChunkText(chunk)}</p>
                </article>
              );
            })}
          </div>
        ) : (
          <p className="empty">Текстовые фрагменты пока не созданы.</p>
        )}
      </section>
    </section>
  );
}
