import { useEffect, useState } from "react";

import { sourceFilesApi } from "../api/sourceFilesApi";
import { ListTitle } from "../components/common/ListTitle";
import { PageHeader } from "../components/common/PageHeader";
import { StatusBadge } from "../components/common/StatusBadge";
import { PdfUpload } from "../components/files/PdfUpload";
import type { SourceFile } from "../types/entities";

export function FilesPage() {
  const [files, setFiles] = useState<SourceFile[]>([]);
  const [error, setError] = useState("");

  async function loadFiles() {
    const data = await sourceFilesApi.getAll();
    setFiles(data);
  }

  useEffect(() => {
    loadFiles().catch(() => setError("Не удалось загрузить файлы"));
  }, []);

  async function handleDelete(file: SourceFile) {
    const confirmed = confirm(`Удалить файл "${file.file_name}"?`);

    if (!confirmed) return;

    try {
      await sourceFilesApi.delete(file.id);
      await loadFiles();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось удалить файл");
    }
  }

  return (
    <section>
      <PageHeader
        title="Файлы"
        description="Загружайте PDF-файлы и управляйте исходными документами."
      />

      {error && <p className="error">{error}</p>}

      <section className="card page-section">
        <h2>Загрузка PDF</h2>
        <PdfUpload onUploaded={() => loadFiles()} />
      </section>

      <section className="card">
        <ListTitle count={files.length} />

        <div className="table-wrapper">
          <table>
            <thead>
              <tr>
                <th>Файл</th>
                <th>Тип</th>
                <th>Статус</th>
                <th>Действия</th>
              </tr>
            </thead>

            <tbody>
              {files.map((file) => (
                <tr key={file.id}>
                  <td>{file.file_name}</td>
                  <td>{file.file_type}</td>
                  <td><StatusBadge value={file.processing_status} /></td>
                  <td>
                    <div className="table-actions">
                      <a
                        className="button button_secondary"
                        href={sourceFilesApi.getDownloadUrl(file.id)}
                        target="_blank"
                        rel="noreferrer"
                      >
                        Открыть
                      </a>
                      <button
                        className="button button_danger"
                        type="button"
                        onClick={() => handleDelete(file)}
                      >
                        Удалить
                      </button>
                    </div>
                  </td>
                </tr>
              ))}

              {!files.length && (
                <tr>
                  <td colSpan={4} className="empty">Файлы пока не загружены.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </section>
  );
}
