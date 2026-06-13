import { useEffect, useState } from "react";

import { processingLogsApi } from "../api/processingLogsApi";
import { ListTitle } from "../components/common/ListTitle";
import { PageHeader } from "../components/common/PageHeader";
import { StatusBadge } from "../components/common/StatusBadge";
import type { ProcessingLog } from "../types/entities";

export function ProcessingLogsPage() {
  const [logs, setLogs] = useState<ProcessingLog[]>([]);
  const [error, setError] = useState("");

  async function loadLogs() {
    const data = await processingLogsApi.getAll();
    setLogs(data);
  }

  useEffect(() => {
    loadLogs().catch(() => setError("Не удалось загрузить журнал обработки"));
  }, []);

  return (
    <section>
      <PageHeader
        title="Журнал обработки"
        description="Служебные этапы обработки файлов. Для MVP журнал только просматривается."
      />

      {error && <p className="error">{error}</p>}

      <section className="card">
        <ListTitle count={logs.length} />

        <div className="table-wrapper">
          <table>
            <thead>
              <tr>
                <th>ID файла</th>
                <th>Этап</th>
                <th>Статус</th>
                <th>Ошибка</th>
                <th>Дата</th>
              </tr>
            </thead>

            <tbody>
              {logs.map((log) => (
                <tr key={log.id}>
                  <td>{log.source_file_id}</td>
                  <td>{log.step ?? log.step_name ?? "—"}</td>
                  <td><StatusBadge value={log.status} /></td>
                  <td>{log.message ?? log.error_message ?? "—"}</td>
                  <td>{new Date(log.created_at).toLocaleString()}</td>
                </tr>
              ))}

              {!logs.length && (
                <tr>
                  <td colSpan={5} className="empty">Записей журнала пока нет.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </section>
  );
}
