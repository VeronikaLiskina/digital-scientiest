import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { documentChunksApi } from "../api/documentChunksApi";
import { processingLogsApi } from "../api/processingLogsApi";
import { publicationsApi } from "../api/publicationsApi";
import { sourceFilesApi } from "../api/sourceFilesApi";
import { PageHeader } from "../components/common/PageHeader";
import { StatusBadge } from "../components/common/StatusBadge";
import type {
  DocumentChunk,
  ProcessingLog,
  Publication,
} from "../types/entities";
import { getPublicationTypeLabel } from "../utils/publicationTypes";

function getChunkText(chunk: DocumentChunk) {
  return chunk.text ?? chunk.chunk_text ?? "";
}

function getLogStep(log: ProcessingLog) {
  return log.step ?? log.step_name ?? "—";
}

function getLogMessage(log: ProcessingLog) {
  return log.message ?? log.error_message ?? "—";
}

export function PublicationDetailsPage() {
  const { publicationId } = useParams();
  const id = Number(publicationId);

  const [publication, setPublication] = useState<Publication | null>(null);
  const [chunks, setChunks] = useState<DocumentChunk[]>([]);
  const [logs, setLogs] = useState<ProcessingLog[]>([]);
  const [error, setError] = useState("");
  const [isProcessing, setIsProcessing] = useState(false);
  const [processingMessage, setProcessingMessage] = useState("");
  const [editingChunkId, setEditingChunkId] = useState<number | null>(null);
  const [editingChunkText, setEditingChunkText] = useState("");
  const [chunkActionError, setChunkActionError] = useState("");

  async function loadPublication() {
    const data = await publicationsApi.getOne(id);
    setPublication(data);

    documentChunksApi
      .getAll(data.id)
      .then(setChunks)
      .catch(() => setChunks([]));

    if (data.source_file_id) {
      processingLogsApi
        .getAll(data.source_file_id)
        .then(setLogs)
        .catch(() => setLogs([]));
    } else {
      setLogs([]);
    }
  }

  useEffect(() => {
    if (!id) return;

    loadPublication().catch((err) => {
      setError(
        err instanceof Error ? err.message : "Не удалось загрузить публикацию",
      );
    });
  }, [id]);

  async function handleProcessPdf() {
    if (!publication?.source_file_id) {
      setProcessingMessage("К публикации не привязан PDF-файл.");
      return;
    }

    const confirmed = window.confirm(
      "При повторной обработке PDF фрагменты будут пересозданы. Ручные изменения могут быть потеряны. Продолжить?",
    );

    if (!confirmed) {
      return;
    }

    try {
      setIsProcessing(true);
      setProcessingMessage("");

      const result = await sourceFilesApi.process(publication.source_file_id);
      const [updatedChunks, updatedLogs] = await Promise.all([
        documentChunksApi.getAll(publication.id),
        processingLogsApi.getAll(publication.source_file_id),
      ]);

      setChunks(updatedChunks);
      setLogs(updatedLogs);

      setProcessingMessage(
        `Обработка завершена. Создано фрагментов: ${result.chunks_created}`,
      );
    } catch (err) {
      setProcessingMessage(
        err instanceof Error ? err.message : "Не удалось обработать PDF.",
      );
    } finally {
      setIsProcessing(false);
    }
  }

  function startEditChunk(chunk: DocumentChunk) {
    setEditingChunkId(chunk.id);
    setEditingChunkText(getChunkText(chunk));
    setChunkActionError("");
  }

  function cancelEditChunk() {
    setEditingChunkId(null);
    setEditingChunkText("");
  }

  async function handleSaveChunk(chunkId: number) {
    try {
      setChunkActionError("");
      const updatedChunk = await documentChunksApi.update(
        chunkId,
        editingChunkText,
      );

      setChunks((prev) =>
        prev.map((chunk) => (chunk.id === chunkId ? updatedChunk : chunk)),
      );
      cancelEditChunk();
    } catch (err) {
      setChunkActionError(
        err instanceof Error ? err.message : "Не удалось обновить фрагмент",
      );
    }
  }

  async function handleDeleteChunk(chunkId: number) {
    const confirmed = window.confirm("Удалить этот фрагмент?");

    if (!confirmed) {
      return;
    }

    try {
      setChunkActionError("");
      await documentChunksApi.delete(chunkId);
      setChunks((prev) => prev.filter((chunk) => chunk.id !== chunkId));
    } catch (err) {
      setChunkActionError(
        err instanceof Error ? err.message : "Не удалось удалить фрагмент",
      );
    }
  }

  if (error) {
    return <p className="error">{error}</p>;
  }

  if (!publication) {
    return <p className="muted">Загрузка...</p>;
  }

  return (
    <section className="publication-details-page">
      <PageHeader
        title={publication.title}
        description="Карточка публикации, исходный PDF и текстовые фрагменты."
        actions={
          <div className="form-actions">
            {publication.source_file_id ? (
              <a
                className="button button_secondary"
                href={sourceFilesApi.getDownloadUrl(publication.source_file_id)}
                target="_blank"
                rel="noreferrer"
              >
                Открыть PDF
              </a>
            ) : (
              <span className="muted publication-details-page__pdf-empty">
                PDF не привязан
              </span>
            )}

            {publication.source_file_id && (
              <button
                className="button"
                type="button"
                onClick={handleProcessPdf}
                disabled={isProcessing}
              >
                {isProcessing ? "Обработка..." : "Обработать PDF"}
              </button>
            )}

            <Link
              className="button button_secondary"
              to={`/admin/publications/${publication.id}/edit`}
            >
              Редактировать
            </Link>

            <Link className="button button_secondary" to="/admin/publications">
              К списку
            </Link>
          </div>
        }
      />

      {processingMessage && (
        <p
          className={
            processingMessage.includes("завершена") ? "success" : "error"
          }
        >
          {processingMessage}
        </p>
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

          <dt>Статус</dt>
          <dd>
            <StatusBadge value={publication.status} />
          </dd>

          <dt>Авторы</dt>
          <dd>
            {publication.authors.map((author) => author.full_name).join(", ") ||
              "—"}
          </dd>

          <dt>Темы</dt>
          <dd>
            {publication.topics.map((topic) => topic.name).join(", ") || "—"}
          </dd>

          <dt>Ключевые слова</dt>
          <dd>
            {publication.keywords.map((keyword) => keyword.name).join(", ") ||
              "—"}
          </dd>
        </dl>
      </section>

      <section className="card page-section">
        <h2>Текстовые фрагменты</h2>

        <div className="chunks-list">
          {chunkActionError && <p className="error">{chunkActionError}</p>}

          {chunks.map((chunk) => {
            const isEditing = editingChunkId === chunk.id;

            return (
              <article className="chunk-card" key={chunk.id}>
                <div className="chunk-card__header">
                  <h3>Фрагмент {chunk.chunk_index ?? chunk.id}</h3>
                  <div className="chunk-card__actions">
                    {isEditing ? (
                      <>
                        <button
                          className="button"
                          type="button"
                          onClick={() => handleSaveChunk(chunk.id)}
                        >
                          Сохранить
                        </button>
                        <button
                          className="button button_secondary"
                          type="button"
                          onClick={cancelEditChunk}
                        >
                          Отмена
                        </button>
                      </>
                    ) : (
                      <>
                        <button
                          className="button button_secondary"
                          type="button"
                          onClick={() => startEditChunk(chunk)}
                        >
                          Редактировать
                        </button>
                        <button
                          className="button button_danger"
                          type="button"
                          onClick={() => handleDeleteChunk(chunk.id)}
                        >
                          Удалить
                        </button>
                      </>
                    )}
                  </div>
                </div>

                {isEditing ? (
                  <textarea
                    className="chunk-card__textarea"
                    value={editingChunkText}
                    onChange={(event) =>
                      setEditingChunkText(event.target.value)
                    }
                  />
                ) : (
                  <p>{getChunkText(chunk)}</p>
                )}
              </article>
            );
          })}

          {!chunks.length && (
            <p className="empty">Текстовые фрагменты пока не созданы.</p>
          )}
        </div>
      </section>

      <section className="card">
        <h2>Журнал обработки</h2>

        <div className="table-wrapper">
          <table>
            <thead>
              <tr>
                <th>Этап</th>
                <th>Статус</th>
                <th>Сообщение</th>
                <th>Дата</th>
              </tr>
            </thead>
            <tbody>
              {logs.map((log) => (
                <tr key={log.id}>
                  <td>{getLogStep(log)}</td>
                  <td>
                    <StatusBadge value={log.status} />
                  </td>
                  <td>{getLogMessage(log)}</td>
                  <td>{log.created_at ?? "—"}</td>
                </tr>
              ))}

              {!logs.length && (
                <tr>
                  <td colSpan={4} className="empty">
                    Журнал обработки пока пуст.
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
