import type { Author, Keyword, PublicationFilters as Filters, Topic } from '../../api/types';

type Props = {
  filters: Filters;
  authors: Author[];
  topics: Topic[];
  keywords: Keyword[];
  onChange: (filters: Filters) => void;
};

export function PublicationFilters({ filters, authors, topics, keywords, onChange }: Props) {
  return (
    <div className="card filters">
      <input
        placeholder="Поиск по названию"
        value={filters.title ?? ''}
        onChange={(event) => onChange({ ...filters, title: event.target.value })}
      />

      <input
        placeholder="Год"
        type="number"
        value={filters.year ?? ''}
        onChange={(event) => onChange({ ...filters, year: event.target.value })}
      />

      <select
        value={filters.author_id ?? ''}
        onChange={(event) => onChange({ ...filters, author_id: event.target.value })}
      >
        <option value="">Все авторы</option>
        {authors.map((author) => (
          <option key={author.id} value={author.id}>
            {author.full_name}
          </option>
        ))}
      </select>

      <select
        value={filters.topic_id ?? ''}
        onChange={(event) => onChange({ ...filters, topic_id: event.target.value })}
      >
        <option value="">Все темы</option>
        {topics.map((topic) => (
          <option key={topic.id} value={topic.id}>
            {topic.name}
          </option>
        ))}
      </select>

      <select
        value={filters.keyword_id ?? ''}
        onChange={(event) => onChange({ ...filters, keyword_id: event.target.value })}
      >
        <option value="">Все ключевые слова</option>
        {keywords.map((keyword) => (
          <option key={keyword.id} value={keyword.id}>
            {keyword.name}
          </option>
        ))}
      </select>
    </div>
  );
}
