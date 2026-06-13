import { useMemo, useState } from "react";

interface MultiSelectOption {
  id: number;
  label: string;
}

interface MultiSelectProps {
  label: string;
  values: number[];
  options: MultiSelectOption[];
  onChange: (values: number[]) => void;
  placeholder?: string;
}

const DEFAULT_VISIBLE_COUNT = 8;

export function MultiSelect({ label, values, options, onChange, placeholder }: MultiSelectProps) {
  const [search, setSearch] = useState("");
  const [isExpanded, setIsExpanded] = useState(false);

  const selectedOptions = useMemo(
    () => options.filter((option) => values.includes(option.id)),
    [options, values],
  );

  const filteredOptions = useMemo(() => {
    const normalizedSearch = search.trim().toLowerCase();

    if (!normalizedSearch) {
      return options;
    }

    return options.filter((option) => option.label.toLowerCase().includes(normalizedSearch));
  }, [options, search]);

  const visibleOptions = isExpanded
    ? filteredOptions
    : filteredOptions.slice(0, DEFAULT_VISIBLE_COUNT);

  function toggleValue(id: number) {
    if (values.includes(id)) {
      onChange(values.filter((value) => value !== id));
      return;
    }

    onChange([...values, id]);
  }

  function clearAll() {
    onChange([]);
  }

  return (
    <div className="multi-select">
      <div className="multi-select__header">
        <span className="multi-select__label">{label}</span>
        {values.length > 0 && (
          <button className="multi-select__clear" type="button" onClick={clearAll}>
            Очистить
          </button>
        )}
      </div>

      <input
        className="multi-select__search"
        value={search}
        onChange={(event) => setSearch(event.target.value)}
        placeholder={placeholder ?? `Поиск: ${label.toLowerCase()}`}
      />

      {selectedOptions.length > 0 && (
        <div className="multi-select__chips" aria-label={`Выбранные ${label.toLowerCase()}`}>
          {selectedOptions.map((option) => (
            <button
              className="multi-select__chip"
              key={option.id}
              type="button"
              onClick={() => toggleValue(option.id)}
              title="Убрать из выбранных"
            >
              {option.label}
              <span>×</span>
            </button>
          ))}
        </div>
      )}

      <div className="multi-select__list">
        {visibleOptions.map((option) => {
          const checked = values.includes(option.id);

          return (
            <label className="multi-select__option" key={option.id}>
              <input
                type="checkbox"
                checked={checked}
                onChange={() => toggleValue(option.id)}
              />
              <span>{option.label}</span>
            </label>
          );
        })}

        {filteredOptions.length === 0 && (
          <p className="multi-select__empty">Ничего не найдено.</p>
        )}
      </div>

      {filteredOptions.length > DEFAULT_VISIBLE_COUNT && (
        <button
          className="multi-select__toggle"
          type="button"
          onClick={() => setIsExpanded((prev) => !prev)}
        >
          {isExpanded
            ? "Свернуть список"
            : `Показать ещё ${filteredOptions.length - DEFAULT_VISIBLE_COUNT}`}
        </button>
      )}
    </div>
  );
}
