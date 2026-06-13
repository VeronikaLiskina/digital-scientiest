import { Link } from 'react-router-dom';
import type { Publication } from '../../api/types';

type Props = {
  publications: Publication[];
};

export function PublicationList({ publications }: Props) {
  if (publications.length === 0) {
    return <div className="empty">Публикации не найдены.</div>;
  }

  return (
    <div className="list">
      {publications.map((publication) => (
        <article className="card publication-item" key={publication.id}>
          <div>
            <h3>{publication.title}</h3>
            <p>
              {publication.year ?? 'год не указан'} · {publication.language ?? 'язык не указан'} ·{' '}
              {publication.publication_type ?? 'тип не указан'}
            </p>
            <p className="muted">
              Авторы: {publication.authors.map((author) => author.full_name).join(', ') || 'не указаны'}
            </p>
          </div>

          <Link className="button button_secondary" to={`/publications/${publication.id}`}>
            Открыть
          </Link>
        </article>
      ))}
    </div>
  );
}
