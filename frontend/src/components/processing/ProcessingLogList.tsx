import type { ProcessingLog } from '../../api/types';

type Props = {
  logs: ProcessingLog[];
};

export function ProcessingLogList({ logs }: Props) {
  if (logs.length === 0) {
    return <p className="muted">Журнал обработки пока пуст.</p>;
  }

  return (
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
              <td>{log.step ?? '—'}</td>
              <td>{log.status ?? '—'}</td>
              <td>{log.message ?? '—'}</td>
              <td>{log.created_at ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
