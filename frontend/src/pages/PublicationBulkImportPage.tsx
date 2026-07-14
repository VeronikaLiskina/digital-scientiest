import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import {
  publicationImportsApi,
  type PublicationImportBatch,
  type PublicationImportItem,
} from "../api/publicationImportsApi";
import { PageHeader } from "../components/common/PageHeader";
import { StatusBadge } from "../components/common/StatusBadge";

const MAX_FILES = 20;
const MAX_FILE_SIZE = 50 * 1024 * 1024;
const MAX_BATCH_SIZE = 300 * 1024 * 1024;

function formatBytes(value: number) {
  if (value < 1024 * 1024) {
    return `${Math.round(value / 1024)} КБ`;
  }

  return `${(value / 1024 / 1024).toFixed(1)} МБ`;
}

function validateFiles(files: File[]) {
  if (files.length > MAX_FILES) {
    return `За один раз можно загрузить не больше ${MAX_FILES} PDF.`;
  }

  const nonPdf = files.find((file) => !file.name.toLowerCase().endsWith(".pdf"));
  if (nonPdf) {
    return `Файл "${nonPdf.name}" не является PDF.`;
  }

  const oversized = files.find((file) => file.size > MAX_FILE_SIZE);
  if (oversized) {
    return `Файл "${oversized.name}" больше ${formatBytes(MAX_FILE_SIZE)}.`;
  }

  const totalSize = files.reduce((sum, file) => sum + file.size, 0);
  if (totalSize > MAX_BATCH_SIZE) {
    return `Общий размер файлов больше ${formatBytes(MAX_BATCH_SIZE)}.`;
  }

  return "";
}

function itemAuthors(item: PublicationImportItem) {
  const authors = item.extracted_metadata?.authors ?? [];

  if (!authors.length) {
    return "—";
  }

  if (authors.length <= 3) {
    return authors.join(", ");
  }

  return `${authors.slice(0, 3).join(", ")} +${authors.length - 3}`;
}

function itemWarning(item: PublicationImportItem) {
  if (item.error_message) {
    return item.error_message;
  }

  return item.extracted_metadata?.title_warning ?? "—";
}

export function PublicationBulkImportPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [batch, setBatch] = useState<PublicationImportBatch | null>(null);
  const [error, setError] = useState("");
  const [isProcessing, setIsProcessing] = useState(false);

  const batchId = searchParams.get("batch_id");

  useEffect(() => {
    if (!batchId) {
      return;
    }

    let cancelled = false;
    let refreshTimer: number | undefined;

    async function refreshBatch() {
      try {
        const nextBatch = await publicationImportsApi.getBatch(Number(batchId));
        if (cancelled) return;

        setBatch(nextBatch);
        const hasActiveProcessing = nextBatch.items.some(
          (item) => item.processing_status === "queued" || item.processing_status === "processing",
        );
        if (hasActiveProcessing) {
          refreshTimer = window.setTimeout(refreshBatch, 2000);
        }
      } catch {
        if (!cancelled) setError("Не удалось загрузить партию импорта");
      }
    }

    void refreshBatch();

    return () => {
      cancelled = true;
      if (refreshTimer !== undefined) window.clearTimeout(refreshTimer);
    };
  }, [batchId]);

  function handleFilesChange(files: FileList | null) {
    const nextFiles = Array.from(files ?? []);
    setSelectedFiles(nextFiles);
    setError(validateFiles(nextFiles));
  }

  async function handleUpload() {
    const validationError = validateFiles(selectedFiles);
    if (validationError) {
      setError(validationError);
      return;
    }

    if (!selectedFiles.length) {
      setError("Выберите PDF-файлы");
      return;
    }

    try {
      setIsProcessing(true);
      setError("");
      const createdBatch = await publicationImportsApi.create(selectedFiles);
      setBatch(createdBatch);
      setSearchParams({ batch_id: String(createdBatch.id) });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось загрузить PDF-файлы");
    } finally {
      setIsProcessing(false);
    }
  }

  return (
    <section className="publication-import-page">
      <PageHeader
        title="Массовая загрузка публикаций"
        description="Загрузите несколько PDF, проверьте результат по каждому файлу и создайте публикации по одной."
        actions={
          <Link className="button button_secondary" to="/admin/publications">
            К публикациям
          </Link>
        }
      />

      {error && <p className="error">{error}</p>}

      <section className="card page-section publication-import-page__upload">
        <label>
          Выберите PDF-файлы
          <input
            type="file"
            accept="application/pdf,.pdf"
            multiple
            onChange={(event) => handleFilesChange(event.target.files)}
          />
        </label>

        {selectedFiles.length > 0 && (
          <div className="publication-import-page__selected">
            <strong>Выбрано файлов: {selectedFiles.length}</strong>
            <ul>
              {selectedFiles.map((file) => (
                <li key={`${file.name}-${file.size}`}>
                  {file.name} <span className="muted">{formatBytes(file.size)}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="form-actions">
          <button
            className="button"
            type="button"
            disabled={isProcessing || !selectedFiles.length || Boolean(validateFiles(selectedFiles))}
            onClick={handleUpload}
          >
            {isProcessing ? "Файлы загружаются и обрабатываются..." : "Загрузить и извлечь данные"}
          </button>
        </div>
      </section>

      {batch && (
        <section className="card page-section">
          <div className="publication-import-page__summary">
            <span>Всего: {batch.total_files}</span>
            <span>К проверке: {batch.needs_review_count}</span>
            <span>Сохранено: {batch.saved_count}</span>
            <span>Дубли: {batch.duplicate_count}</span>
            <span>Ошибки: {batch.error_count}</span>
          </div>

          <div className="table-wrapper">
            <table>
              <thead>
                <tr>
                  <th>Файл</th>
                  <th>Название</th>
                  <th>Авторы</th>
                  <th>Статус</th>
                  <th>Обработка PDF</th>
                  <th>Предупреждение</th>
                  <th>Действие</th>
                </tr>
              </thead>
              <tbody>
                {batch.items.map((item) => {
                  const isPdfProcessing =
                    item.processing_status === "queued" || item.processing_status === "processing";

                  return (
                  <tr className={isPdfProcessing ? "publication-import-page__processing-row" : undefined} key={item.id}>
                    <td>{item.original_file_name}</td>
                    <td>{item.title ?? item.extracted_metadata?.title ?? "—"}</td>
                    <td>{itemAuthors(item)}</td>
                    <td>
                      <StatusBadge value={item.status} />
                    </td>
                    <td>
                      {item.publication_id && item.processing_status ? (
                        <div className="publication-import-page__processing-status">
                          {isPdfProcessing && <span aria-hidden="true" />}
                          <StatusBadge value={item.processing_status} />
                        </div>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                    <td>{itemWarning(item)}</td>
                    <td>
                      {item.status === "needs_review" ? (
                        <Link
                          className="button button_secondary"
                          to={`/admin/publications/new?import_item_id=${item.id}&batch_id=${batch.id}`}
                        >
                          Проверить
                        </Link>
                      ) : item.publication_id ? (
                        <Link className="button button_secondary" to={`/admin/publications/${item.publication_id}`}>
                          Открыть
                        </Link>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                  </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </section>
  );
}
