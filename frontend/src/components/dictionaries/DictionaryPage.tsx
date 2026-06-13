import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { PageHeader } from "../common/PageHeader";

export interface DictionaryItem {
  id: number;
  title: string;
  subtitle?: string | null;
}

interface FieldConfig<TForm> {
  name: keyof TForm;
  label: string;
  placeholder?: string;
  type?: "input" | "textarea";
  required?: boolean;
}

interface DictionaryPageProps<TItem, TForm> {
  title: string;
  description: string;
  createTitle: string;
  editTitle: string;
  submitCreateText: string;
  submitEditText: string;
  emptyText: string;
  initialForm: TForm;
  fields: FieldConfig<TForm>[];
  loadItems: () => Promise<TItem[]>;
  createItem: (data: TForm) => Promise<TItem>;
  updateItem: (id: number, data: Partial<TForm>) => Promise<TItem>;
  deleteItem: (id: number) => Promise<void>;
  mapItem: (item: TItem) => DictionaryItem;
  itemToForm: (item: TItem) => TForm;
  validate: (data: TForm) => string | null;
}

export function DictionaryPage<TItem, TForm extends Record<string, string>>({
  title,
  description,
  createTitle,
  editTitle,
  submitCreateText,
  submitEditText,
  emptyText,
  initialForm,
  fields,
  loadItems,
  createItem,
  updateItem,
  deleteItem,
  mapItem,
  itemToForm,
  validate,
}: DictionaryPageProps<TItem, TForm>) {
  const [items, setItems] = useState<TItem[]>([]);
  const [form, setForm] = useState<TForm>(initialForm);
  const [editing, setEditing] = useState<TItem | null>(null);
  const [error, setError] = useState("");

  async function refresh() {
    const data = await loadItems();
    setItems(data);
  }

  useEffect(() => {
    refresh().catch(() => setError("Не удалось загрузить данные"));
  }, []);

  function reset() {
    setEditing(null);
    setForm(initialForm);
  }

  function startEdit(item: TItem) {
    setEditing(item);
    setForm(itemToForm(item));
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const validationError = validate(form);
    if (validationError) {
      setError(validationError);
      return;
    }

    try {
      setError("");
      if (editing) {
        await updateItem(mapItem(editing).id, form);
      } else {
        await createItem(form);
      }
      reset();
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось сохранить запись");
    }
  }

  async function handleDelete(item: TItem) {
    const view = mapItem(item);
    if (!confirm(`Удалить запись "${view.title}"?`)) return;

    try {
      setError("");
      await deleteItem(view.id);
      if (editing && mapItem(editing).id === view.id) reset();
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось удалить запись");
    }
  }

  return (
    <main className="page-container dictionary-page">
      <PageHeader title={title} description={description} />
      {error && <p className="error">{error}</p>}

      <div className="dictionary-layout">
        <section className="card">
          <h2>{editing ? editTitle : createTitle}</h2>
          <form className="form" onSubmit={handleSubmit}>
            {fields.map((field) => (
              <label key={String(field.name)}>
                {field.label}{field.required && " *"}
                {field.type === "textarea" ? (
                  <textarea
                    rows={4}
                    placeholder={field.placeholder}
                    value={form[field.name]}
                    onChange={(event) => setForm((prev) => ({ ...prev, [field.name]: event.target.value }))}
                  />
                ) : (
                  <input
                    placeholder={field.placeholder}
                    value={form[field.name]}
                    onChange={(event) => setForm((prev) => ({ ...prev, [field.name]: event.target.value }))}
                  />
                )}
              </label>
            ))}

            <div className="form-actions">
              <button className="button" type="submit">{editing ? submitEditText : submitCreateText}</button>
              {editing && <button className="button button_secondary" type="button" onClick={reset}>Отмена</button>}
            </div>
          </form>
        </section>

        <section>
          <h2 className="list-title">Список <span>{items.length}</span></h2>
          <div className="dictionary-list">
            {items.map((item) => {
              const view = mapItem(item);
              return (
                <article className="dictionary-card" key={view.id}>
                  <div>
                    <h3>{view.title}</h3>
                    {view.subtitle && <p>{view.subtitle}</p>}
                  </div>
                  <div className="dictionary-card__actions">
                    <button className="button button_secondary" type="button" onClick={() => startEdit(item)}>Редактировать</button>
                    <button className="button button_danger" type="button" onClick={() => handleDelete(item)}>Удалить</button>
                  </div>
                </article>
              );
            })}
            {!items.length && <p className="empty">{emptyText}</p>}
          </div>
        </section>
      </div>
    </main>
  );
}
