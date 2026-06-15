import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import { authorsApi } from "../api/authorsApi";
import { PageHeader } from "../components/common/PageHeader";
import { DictionaryList, type DictionaryListItem } from "../components/dictionaries/DictionaryList";
import type { Author } from "../types/entities";
import type { AuthorFormData } from "../types/forms";

const emptyForm: AuthorFormData = {
  full_name: "",
  organization: "",
};

export function AuthorsPage() {
  const [authors, setAuthors] = useState<Author[]>([]);
  const [formData, setFormData] = useState<AuthorFormData>(emptyForm);
  const [editingAuthor, setEditingAuthor] = useState<Author | null>(null);
  const [error, setError] = useState("");

  async function loadAuthors() {
    const data = await authorsApi.getAll();
    setAuthors(data);
  }

  useEffect(() => {
    loadAuthors().catch(() => setError("Не удалось загрузить авторов"));
  }, []);

  function startEdit(author: Author) {
    setEditingAuthor(author);
    setFormData({
      full_name: author.full_name,
      organization: author.organization ?? "",
    });
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function resetForm() {
    setEditingAuthor(null);
    setFormData(emptyForm);
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();

    if (!formData.full_name.trim()) {
      setError("Заполните ФИО автора");
      return;
    }

    try {
      setError("");

      if (editingAuthor) {
        await authorsApi.update(editingAuthor.id, formData);
      } else {
        await authorsApi.create(formData);
      }

      resetForm();
      await loadAuthors();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось сохранить автора");
    }
  }

  async function handleDelete(author: Author) {
    const confirmed = confirm(`Удалить автора "${author.full_name}"?`);

    if (!confirmed) return;

    try {
      await authorsApi.delete(author.id);
      await loadAuthors();

      if (editingAuthor?.id === author.id) {
        resetForm();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось удалить автора");
    }
  }

  const listItems: DictionaryListItem[] = authors.map((author) => ({
    id: author.id,
    title: author.full_name,
    subtitle: author.organization,
  }));

  return (
    <section className="dictionary-page">
      <PageHeader
        title="Авторы"
        description="Добавляйте авторов, чтобы потом выбирать их в карточке публикации."
      />

      {error && <p className="error">{error}</p>}

      <div className="dictionary-page__content">
        <section className="card dictionary-page__form-card">
          <h2>{editingAuthor ? "Редактирование автора" : "Новая запись"}</h2>

          <form className="form" onSubmit={handleSubmit}>
            <label>
              ФИО автора *
              <input
                value={formData.full_name}
                onChange={(event) =>
                  setFormData((prev) => ({ ...prev, full_name: event.target.value }))
                }
                placeholder="Иванов И. И."
              />
            </label>

            <label>
              Организация
              <input
                value={formData.organization}
                onChange={(event) =>
                  setFormData((prev) => ({ ...prev, organization: event.target.value }))
                }
                placeholder="Институт земной коры СО РАН"
              />
            </label>

            <div className="form-actions">
              <button className="button" type="submit">
                {editingAuthor ? "Сохранить изменения" : "Добавить автора"}
              </button>

              {editingAuthor && (
                <button className="button button_secondary" type="button" onClick={resetForm}>
                  Отмена
                </button>
              )}
            </div>
          </form>
        </section>

        <DictionaryList
          items={listItems}
          emptyText="Авторы пока не добавлены."
          onEdit={(item) => {
            const author = authors.find((authorItem) => authorItem.id === item.id);
            if (author) startEdit(author);
          }}
          onDelete={(item) => {
            const author = authors.find((authorItem) => authorItem.id === item.id);
            if (author) void handleDelete(author);
          }}
        />
      </div>
    </section>
  );
}
