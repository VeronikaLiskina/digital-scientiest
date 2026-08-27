import { useState } from "react";

import { ListTitle } from "../common/ListTitle";
import { DictionaryCard } from "./DictionaryCard";

export interface DictionaryListItem {
  id: number;
  title: string;
  subtitle?: string | null;
}

interface DictionaryListProps {
  items: DictionaryListItem[];
  emptyText: string;
  onEdit: (item: DictionaryListItem) => void;
  onDelete: (item: DictionaryListItem) => void;
}

const VISIBLE_COUNT = 6;

export function DictionaryList({ items, emptyText, onEdit, onDelete }: DictionaryListProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const visibleItems = isExpanded ? items : items.slice(0, VISIBLE_COUNT);
  const hiddenCount = items.length - VISIBLE_COUNT;

  return (
    <section className="dictionary-list">
      <ListTitle count={items.length} />

      <div className="dictionary-list__items">
        {visibleItems.map((item) => (
          <DictionaryCard
            key={item.id}
            title={item.title}
            subtitle={item.subtitle}
            onEdit={() => onEdit(item)}
            onDelete={() => onDelete(item)}
          />
        ))}

        {!items.length && <p className="empty">{emptyText}</p>}
      </div>

      {items.length > VISIBLE_COUNT && (
        <button
          className="button button_secondary dictionary-list__show-more"
          type="button"
          onClick={() => setIsExpanded((prev) => !prev)}
        >
          {isExpanded ? "Свернуть список" : `Показать ещё ${hiddenCount}`}
        </button>
      )}
    </section>
  );
}
