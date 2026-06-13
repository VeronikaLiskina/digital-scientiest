interface DictionaryCardProps {
  title: string;
  subtitle?: string | null;
  onEdit: () => void;
  onDelete: () => void;
}

export function DictionaryCard({ title, subtitle, onEdit, onDelete }: DictionaryCardProps) {
  return (
    <article className="dictionary-card">
      <div className="dictionary-card__content">
        <h3>{title}</h3>
        {subtitle && <p>{subtitle}</p>}
      </div>

      <div className="dictionary-card__actions">
        <button className="button button_secondary" type="button" onClick={onEdit}>
          Редактировать
        </button>
        <button className="button button_danger" type="button" onClick={onDelete}>
          Удалить
        </button>
      </div>
    </article>
  );
}
