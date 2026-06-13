import { useEffect, useState } from "react";

import { keywordsApi } from "../api/keywordsApi";
import { PageHeader } from "../components/common/PageHeader";
import { DictionaryList, type DictionaryListItem } from "../components/dictionaries/DictionaryList";
import type { Keyword } from "../types/entities";
import type { KeywordFormData } from "../types/forms";

const emptyForm: KeywordFormData = {
  name: "",
};

export function KeywordsPage() {
  const [keywords, setKeywords] = useState<Keyword[]>([]);
  const [formData, setFormData] = useState<KeywordFormData>(emptyForm);
  const [editingKeyword, setEditingKeyword] = useState<Keyword | null>(null);
  const [error, setError] = useState("");

  async function loadKeywords() {
    const data = await keywordsApi.getAll();
    setKeywords(data);
  }

  useEffect(() => {
    loadKeywords().catch(() => setError("Не удалось загрузить ключевые слова"));
  }, []);

  function startEdit(keyword: Keyword) {
    setEditingKeyword(keyword);
    setFormData({ name: keyword.name });
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function resetForm() {
    setEditingKeyword(null);
    setFormData(emptyForm);
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();

    if (!formData.name.trim()) {
      setError("Заполните ключевое слово");
      return;
    }

    try {
      setError("");

      if (editingKeyword) {
        await keywordsApi.update(editingKeyword.id, formData);
      } else {
        await keywordsApi.create(formData);
      }

      resetForm();
      await loadKeywords();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось сохранить ключевое слово");
    }
  }

  async function handleDelete(keyword: Keyword) {
    const confirmed = confirm(`Удалить ключевое слово "${keyword.name}"?`);

    if (!confirmed) return;

    try {
      await keywordsApi.delete(keyword.id);
      await loadKeywords();

      if (editingKeyword?.id === keyword.id) {
        resetForm();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось удалить ключевое слово");
    }
  }

  const listItems: DictionaryListItem[] = keywords.map((keyword) => ({
    id: keyword.id,
    title: keyword.name,
  }));

  return (
    <section className="dictionary-page">
      <PageHeader
        title="Ключевые слова"
        description="Добавляйте ключевые слова для поиска и фильтрации."
      />

      {error && <p className="error">{error}</p>}

      <div className="dictionary-page__content">
        <section className="card dictionary-page__form-card">
          <h2>{editingKeyword ? "Редактирование ключевого слова" : "Новая запись"}</h2>

          <form className="form" onSubmit={handleSubmit}>
            <label>
              Ключевое слово *
              <input
                value={formData.name}
                onChange={(event) =>
                  setFormData((prev) => ({ ...prev, name: event.target.value }))
                }
                placeholder="40Ar/39Ar dating"
              />
            </label>

            <div className="form-actions">
              <button className="button" type="submit">
                {editingKeyword ? "Сохранить изменения" : "Добавить ключевое слово"}
              </button>

              {editingKeyword && (
                <button className="button button_secondary" type="button" onClick={resetForm}>
                  Отмена
                </button>
              )}
            </div>
          </form>
        </section>

        <DictionaryList
          items={listItems}
          emptyText="Ключевые слова пока не добавлены."
          onEdit={(item) => {
            const keyword = keywords.find((keywordItem) => keywordItem.id === item.id);
            if (keyword) startEdit(keyword);
          }}
          onDelete={(item) => {
            const keyword = keywords.find((keywordItem) => keywordItem.id === item.id);
            if (keyword) void handleDelete(keyword);
          }}
        />
      </div>
    </section>
  );
}
