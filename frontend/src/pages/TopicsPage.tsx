import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import { topicsApi } from "../api/topicsApi";
import { PageHeader } from "../components/common/PageHeader";
import { DictionaryList, type DictionaryListItem } from "../components/dictionaries/DictionaryList";
import type { Topic } from "../types/entities";
import type { TopicFormData } from "../types/forms";

const emptyForm: TopicFormData = {
  name: "",
  description: "",
};

export function TopicsPage() {
  const [topics, setTopics] = useState<Topic[]>([]);
  const [formData, setFormData] = useState<TopicFormData>(emptyForm);
  const [editingTopic, setEditingTopic] = useState<Topic | null>(null);
  const [error, setError] = useState("");

  async function loadTopics() {
    const data = await topicsApi.getAll();
    setTopics(data);
  }

  useEffect(() => {
    loadTopics().catch(() => setError("Не удалось загрузить темы"));
  }, []);

  function startEdit(topic: Topic) {
    setEditingTopic(topic);
    setFormData({
      name: topic.name,
      description: topic.description ?? "",
    });
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function resetForm() {
    setEditingTopic(null);
    setFormData(emptyForm);
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();

    if (!formData.name.trim()) {
      setError("Заполните название темы");
      return;
    }

    try {
      setError("");

      if (editingTopic) {
        await topicsApi.update(editingTopic.id, formData);
      } else {
        await topicsApi.create(formData);
      }

      resetForm();
      await loadTopics();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось сохранить тему");
    }
  }

  async function handleDelete(topic: Topic) {
    const confirmed = confirm(`Удалить тему "${topic.name}"?`);

    if (!confirmed) return;

    try {
      await topicsApi.delete(topic.id);
      await loadTopics();

      if (editingTopic?.id === topic.id) {
        resetForm();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось удалить тему");
    }
  }

  const listItems: DictionaryListItem[] = topics.map((topic) => ({
    id: topic.id,
    title: topic.name,
    subtitle: topic.description,
  }));

  return (
    <section className="dictionary-page">
      <PageHeader title="Темы" description="Добавляйте темы для классификации публикаций." />

      {error && <p className="error">{error}</p>}

      <div className="dictionary-page__content">
        <section className="card dictionary-page__form-card">
          <h2>{editingTopic ? "Редактирование темы" : "Новая запись"}</h2>

          <form className="form" onSubmit={handleSubmit}>
            <label>
              Название темы *
              <input
                value={formData.name}
                onChange={(event) =>
                  setFormData((prev) => ({ ...prev, name: event.target.value }))
                }
                placeholder="Байкало-Муйский пояс"
              />
            </label>

            <label>
              Описание
              <textarea
                value={formData.description}
                onChange={(event) =>
                  setFormData((prev) => ({ ...prev, description: event.target.value }))
                }
                placeholder="Краткое описание темы"
                rows={4}
              />
            </label>

            <div className="form-actions">
              <button className="button" type="submit">
                {editingTopic ? "Сохранить изменения" : "Добавить тему"}
              </button>

              {editingTopic && (
                <button className="button button_secondary" type="button" onClick={resetForm}>
                  Отмена
                </button>
              )}
            </div>
          </form>
        </section>

        <DictionaryList
          items={listItems}
          emptyText="Темы пока не добавлены."
          onEdit={(item) => {
            const topic = topics.find((topicItem) => topicItem.id === item.id);
            if (topic) startEdit(topic);
          }}
          onDelete={(item) => {
            const topic = topics.find((topicItem) => topicItem.id === item.id);
            if (topic) void handleDelete(topic);
          }}
        />
      </div>
    </section>
  );
}
