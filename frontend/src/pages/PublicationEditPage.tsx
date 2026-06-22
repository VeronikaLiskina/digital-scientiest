import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { authorsApi } from "../api/authorsApi";
import { keywordsApi } from "../api/keywordsApi";
import { publicationsApi } from "../api/publicationsApi";
import { sourceFilesApi } from "../api/sourceFilesApi";
import { topicsApi } from "../api/topicsApi";
import { MultiSelect } from "../components/common/MultiSelect";
import { PageHeader } from "../components/common/PageHeader";
import { QuickCreateField } from "../components/publications/QuickCreateField";
import type { Author, Keyword, SourceFile, Topic } from "../types/entities";
import type { PublicationFormData } from "../types/forms";
import { publicationTypeOptions } from "../utils/publicationTypes";

const emptyForm: PublicationFormData = {
  title: "",
  year: "",
  language: "ru",
  publication_type: "article",
  doi: "",
  status: "draft",
  source_file_id: "",
  author_ids: [],
  topic_ids: [],
  keyword_ids: [],
  author_names: "",
  topic_names: "",
  keyword_names: "",
};

export function PublicationEditPage() {
  const { publicationId } = useParams();
  const id = Number(publicationId);
  const navigate = useNavigate();

  const [formData, setFormData] = useState<PublicationFormData>(emptyForm);
  const [authors, setAuthors] = useState<Author[]>([]);
  const [topics, setTopics] = useState<Topic[]>([]);
  const [keywords, setKeywords] = useState<Keyword[]>([]);
  const [sourceFiles, setSourceFiles] = useState<SourceFile[]>([]);
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    if (!id) return;

    Promise.all([
      publicationsApi.getOne(id),
      authorsApi.getAll(),
      topicsApi.getAll(),
      keywordsApi.getAll(),
      sourceFilesApi.getAll(),
    ])
      .then(([publication, authorsData, topicsData, keywordsData, filesData]) => {
        setAuthors(authorsData);
        setTopics(topicsData);
        setKeywords(keywordsData);
        setSourceFiles(filesData);

        setFormData({
          title: publication.title ?? "",
          year: publication.year ? String(publication.year) : "",
          language: publication.language ?? "ru",
          publication_type: publication.publication_type ?? "article",
          doi: publication.doi ?? "",
          status: publication.status ?? "draft",
          source_file_id: publication.source_file_id
            ? String(publication.source_file_id)
            : "",
          author_ids: publication.authors.map((author) => author.id),
          topic_ids: publication.topics.map((topic) => topic.id),
          keyword_ids: publication.keywords.map((keyword) => keyword.id),
          author_names: "",
          topic_names: "",
          keyword_names: "",
        });
      })
      .catch((err) => {
        setError(
          err instanceof Error
            ? err.message
            : "Не удалось загрузить данные публикации",
        );
      })
      .finally(() => {
        setIsLoading(false);
      });
  }, [id]);

  function updateForm<K extends keyof PublicationFormData>(
    key: K,
    value: PublicationFormData[K],
  ) {
    setFormData((prev) => ({
      ...prev,
      [key]: value,
    }));
  }

  async function handleCreateAuthor(fullName: string) {
    const created = await authorsApi.create({ full_name: fullName, organization: "" });
    setAuthors((prev) => [created, ...prev]);
    setFormData((prev) => ({ ...prev, author_ids: [...prev.author_ids, created.id] }));
  }

  async function handleCreateTopic(name: string) {
    const created = await topicsApi.create({ name, description: "" });
    setTopics((prev) => [created, ...prev]);
    setFormData((prev) => ({ ...prev, topic_ids: [...prev.topic_ids, created.id] }));
  }

  async function handleCreateKeyword(name: string) {
    const created = await keywordsApi.create({ name });
    setKeywords((prev) => [created, ...prev]);
    setFormData((prev) => ({ ...prev, keyword_ids: [...prev.keyword_ids, created.id] }));
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!formData.title.trim()) {
      setError("Заполните название публикации");
      return;
    }

    try {
      setIsSaving(true);
      setError("");

      await publicationsApi.update(id, formData);

      navigate(`/admin/publications/${id}`);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Не удалось сохранить изменения",
      );
    } finally {
      setIsSaving(false);
    }
  }

  if (isLoading) {
    return <p className="muted">Загрузка...</p>;
  }

  return (
    <section className="publication-edit-page">
      <PageHeader
        title="Редактировать публикацию"
        description="Измените данные карточки публикации."
        actions={
          <Link className="button button_secondary" to={`/admin/publications/${id}`}>
            К карточке
          </Link>
        }
      />

      {error && <p className="error">{error}</p>}

      <section className="card page-section">
        <form className="form" onSubmit={handleSubmit}>
          <label>
            Исходный файл
            <select
              value={formData.source_file_id}
              onChange={(event) => updateForm("source_file_id", event.target.value)}
            >
              <option value="">Без файла</option>
              {sourceFiles.map((file) => (
                <option key={file.id} value={file.id}>
                  {file.file_name}
                </option>
              ))}
            </select>
          </label>

          <label>
            Название *
            <input
              value={formData.title}
              onChange={(event) => updateForm("title", event.target.value)}
              placeholder="Название публикации"
            />
          </label>

          <div className="form-grid">
            <label>
              Год
              <input
                value={formData.year}
                onChange={(event) => updateForm("year", event.target.value)}
                placeholder="2024"
              />
            </label>

            <label>
              Язык
              <select
                value={formData.language}
                onChange={(event) => updateForm("language", event.target.value)}
              >
                <option value="ru">Русский</option>
                <option value="en">English</option>
              </select>
            </label>

            <label>
              Тип
              <select
                value={formData.publication_type}
                onChange={(event) => updateForm("publication_type", event.target.value)}
              >
                {publicationTypeOptions.map((type) => (
                  <option key={type.value} value={type.value}>
                    {type.label}
                  </option>
                ))}
              </select>
            </label>

            <label>
              Статус
              <select
                value={formData.status}
                onChange={(event) => updateForm("status", event.target.value)}
              >
                <option value="draft">Черновик</option>
                <option value="review">На проверке</option>
                <option value="processed">Обработано</option>
              </select>
            </label>
          </div>

          <label>
            DOI
            <input
              value={formData.doi}
              onChange={(event) => updateForm("doi", event.target.value)}
              placeholder="10.1234/example"
            />
          </label>

          <div className="publication-form-section">
            <MultiSelect
              label="Авторы"
              values={formData.author_ids}
              options={authors.map((author) => ({ id: author.id, label: author.full_name }))}
              onChange={(values) => updateForm("author_ids", values)}
            />
            <QuickCreateField
              label="Заполните ФИО автора"
              placeholder="Новый автор"
              buttonText="+ Добавить автора"
              onCreate={handleCreateAuthor}
            />
          </div>

          <div className="publication-form-section">
            <MultiSelect
              label="Темы"
              values={formData.topic_ids}
              options={topics.map((topic) => ({ id: topic.id, label: topic.name }))}
              onChange={(values) => updateForm("topic_ids", values)}
            />
            <QuickCreateField
              label="Заполните название темы"
              placeholder="Новая тема"
              buttonText="+ Добавить тему"
              onCreate={handleCreateTopic}
            />
          </div>

          <div className="publication-form-section">
            <MultiSelect
              label="Ключевые слова"
              values={formData.keyword_ids}
              options={keywords.map((keyword) => ({ id: keyword.id, label: keyword.name }))}
              onChange={(values) => updateForm("keyword_ids", values)}
            />
            <QuickCreateField
              label="Заполните ключевое слово"
              placeholder="Новое ключевое слово"
              buttonText="+ Добавить ключевое слово"
              onCreate={handleCreateKeyword}
            />
          </div>

          <div className="form-actions">
            <button className="button" type="submit" disabled={isSaving}>
              {isSaving ? "Сохраняем..." : "Сохранить изменения"}
            </button>

            <Link className="button button_secondary" to={`/admin/publications/${id}`}>
              Отмена
            </Link>
          </div>
        </form>
      </section>
    </section>
  );
}
