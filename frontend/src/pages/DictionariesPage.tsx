import { FormEvent, useEffect, useMemo, useState } from "react";

import { authorsApi } from "../api/authorsApi";
import { keywordsApi } from "../api/keywordsApi";
import { topicsApi } from "../api/topicsApi";

type DictionaryType = "authors" | "topics" | "keywords";

type Props = {
  type: DictionaryType;
};

type DictionaryItem = {
  id: number;
  title: string;
  subtitle?: string | null;
};

type DictionaryFormState = {
  full_name: string;
  organization: string;
  name: string;
  description: string;
};

const initialForm: DictionaryFormState = {
  full_name: "",
  organization: "",
  name: "",
  description: "",
};

function getDictionaryTitle(type: DictionaryType) {
  if (type === "authors") return "Авторы";
  if (type === "topics") return "Темы";
  return "Ключевые слова";
}

function getDictionaryDescription(type: DictionaryType) {
  if (type === "authors") return "Добавляйте авторов, чтобы потом выбирать их в карточке публикации.";
  if (type === "topics") return "Добавляйте темы для группировки и фильтрации публикаций.";
  return "Добавляйте ключевые слова для поиска и описания публикаций.";
}

function getCreateButtonText(type: DictionaryType) {
  if (type === "authors") return "Добавить автора";
  if (type === "topics") return "Добавить тему";
  return "Добавить ключевое слово";
}

export function DictionariesPage({ type }: Props) {
  const [items, setItems] = useState<DictionaryItem[]>([]);
  const [form, setForm] = useState<DictionaryFormState>(initialForm);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);

  const title = useMemo(() => getDictionaryTitle(type), [type]);
  const description = useMemo(() => getDictionaryDescription(type), [type]);

  function updateForm<K extends keyof DictionaryFormState>(key: K, value: DictionaryFormState[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  function mapAuthors() {
    return authorsApi.getAll().then((data) =>
      data.map((item) => ({
        id: item.id,
        title: item.full_name,
        subtitle: item.organization,
      })),
    );
  }

  function mapTopics() {
    return topicsApi.getAll().then((data) =>
      data.map((item) => ({
        id: item.id,
        title: item.name,
        subtitle: item.description,
      })),
    );
  }

  function mapKeywords() {
    return keywordsApi.getAll().then((data) =>
      data.map((item) => ({
        id: item.id,
        title: item.name,
      })),
    );
  }

  async function loadItems() {
    setIsLoading(true);
    setError(null);

    try {
      const data =
        type === "authors" ? await mapAuthors() : type === "topics" ? await mapTopics() : await mapKeywords();

      setItems(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось загрузить справочник.");
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    setForm(initialForm);
    setSuccess(null);
    void loadItems();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [type]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSuccess(null);

    try {
      setIsSaving(true);

      if (type === "authors") {
        const fullName = form.full_name.trim();
        if (!fullName) {
          setError("Укажите ФИО автора.");
          return;
        }

        await authorsApi.create({
          full_name: fullName,
          organization: form.organization.trim() || null,
        });
        setSuccess("Автор добавлен.");
      }

      if (type === "topics") {
        const name = form.name.trim();
        if (!name) {
          setError("Укажите название темы.");
          return;
        }

        await topicsApi.create({
          name,
          description: form.description.trim() || null,
        });
        setSuccess("Тема добавлена.");
      }

      if (type === "keywords") {
        const name = form.name.trim();
        if (!name) {
          setError("Укажите ключевое слово.");
          return;
        }

        await keywordsApi.create({ name });
        setSuccess("Ключевое слово добавлено.");
      }

      setForm(initialForm);
      await loadItems();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось сохранить запись.");
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <section className={`dictionary-page dictionary-page_type_${type}`}>
      <div className="dictionary-page__header page-header">
        <div>
          <h1>{title}</h1>
          <p>{description}</p>
        </div>
      </div>

      <div className="dictionary-page__content">
        <form className="dictionary-form card" onSubmit={handleSubmit}>
          <h2 className="dictionary-form__title">Новая запись</h2>

          {type === "authors" && (
            <>
              <label className="dictionary-form__field">
                <span className="dictionary-form__label">ФИО автора *</span>
                <input
                  className="dictionary-form__control"
                  value={form.full_name}
                  placeholder="Иванов И. И."
                  onChange={(event) => updateForm("full_name", event.target.value)}
                />
              </label>

              <label className="dictionary-form__field">
                <span className="dictionary-form__label">Организация</span>
                <input
                  className="dictionary-form__control"
                  value={form.organization}
                  placeholder="Институт земной коры СО РАН"
                  onChange={(event) => updateForm("organization", event.target.value)}
                />
              </label>
            </>
          )}

          {type === "topics" && (
            <>
              <label className="dictionary-form__field">
                <span className="dictionary-form__label">Название темы *</span>
                <input
                  className="dictionary-form__control"
                  value={form.name}
                  placeholder="Байкал"
                  onChange={(event) => updateForm("name", event.target.value)}
                />
              </label>

              <label className="dictionary-form__field">
                <span className="dictionary-form__label">Описание</span>
                <textarea
                  className="dictionary-form__control dictionary-form__control_textarea"
                  value={form.description}
                  placeholder="Публикации, связанные с Байкальским регионом"
                  onChange={(event) => updateForm("description", event.target.value)}
                />
              </label>
            </>
          )}

          {type === "keywords" && (
            <label className="dictionary-form__field">
              <span className="dictionary-form__label">Ключевое слово *</span>
              <input
                className="dictionary-form__control"
                value={form.name}
                placeholder="геология"
                onChange={(event) => updateForm("name", event.target.value)}
              />
            </label>
          )}

          {error && <p className="dictionary-form__message error">{error}</p>}
          {success && <p className="dictionary-form__message success">{success}</p>}

          <button className="dictionary-form__button button" type="submit" disabled={isSaving}>
            {isSaving ? "Сохраняем..." : getCreateButtonText(type)}
          </button>
        </form>

        <div className="dictionary-list">
          <div className="dictionary-list__header">
            <h2 className="dictionary-list__title">Список</h2>
            <span className="dictionary-list__count">{items.length}</span>
          </div>

          {isLoading && <p className="dictionary-list__empty muted">Загрузка...</p>}

          {!isLoading && items.length === 0 && (
            <p className="dictionary-list__empty muted">Записей пока нет. Добавьте первую запись через форму.</p>
          )}

          {!isLoading && items.length > 0 && (
            <div className="dictionary-list__items">
              {items.map((item) => (
                <article className="dictionary-list__item card" key={item.id}>
                  <h3 className="dictionary-list__item-title">{item.title}</h3>
                  {item.subtitle && <p className="dictionary-list__item-subtitle muted">{item.subtitle}</p>}
                </article>
              ))}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
