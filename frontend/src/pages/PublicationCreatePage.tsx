import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { authorsApi } from "../api/authorsApi";
import { keywordsApi } from "../api/keywordsApi";
import { publicationsApi } from "../api/publicationsApi";
import { sourceFilesApi } from "../api/sourceFilesApi";
import { topicsApi } from "../api/topicsApi";
import { MultiSelect } from "../components/common/MultiSelect";
import { PageHeader } from "../components/common/PageHeader";
import { PdfUpload } from "../components/files/PdfUpload";
import type { Author, Keyword, SourceFile, Topic } from "../types/entities";
import type { PublicationFormData } from "../types/forms";

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
};

export function PublicationCreatePage() {
  const navigate = useNavigate();

  const [authors, setAuthors] = useState<Author[]>([]);
  const [topics, setTopics] = useState<Topic[]>([]);
  const [keywords, setKeywords] = useState<Keyword[]>([]);
  const [sourceFiles, setSourceFiles] = useState<SourceFile[]>([]);
  const [formData, setFormData] = useState<PublicationFormData>(emptyForm);
  const [error, setError] = useState("");
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    Promise.all([
      authorsApi.getAll(),
      topicsApi.getAll(),
      keywordsApi.getAll(),
      sourceFilesApi.getAll(),
    ])
      .then(([authorsData, topicsData, keywordsData, filesData]) => {
        setAuthors(authorsData);
        setTopics(topicsData);
        setKeywords(keywordsData);
        setSourceFiles(filesData);
      })
      .catch(() => setError("Не удалось загрузить справочники"));
  }, []);

  function updateForm<K extends keyof PublicationFormData>(key: K, value: PublicationFormData[K]) {
    setFormData((prev) => ({ ...prev, [key]: value }));
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();

    if (!formData.title.trim()) {
      setError("Заполните название публикации");
      return;
    }

    try {
      setIsSaving(true);
      setError("");

      const created = await publicationsApi.create(formData);
      navigate(`/publications/${created.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось создать публикацию");
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <section className="publication-create-page">
      <PageHeader
        title="Добавить публикацию"
        description="Загрузите PDF и заполните карточку публикации."
        actions={
          <Link className="button button_secondary" to="/publications">
            К списку
          </Link>
        }
      />

      {error && <p className="error">{error}</p>}

      <section className="card page-section">
        <form className="form" onSubmit={handleSubmit}>
          <div className="publication-create-page__file-block">
            <PdfUpload
              onUploaded={(file) => {
                setSourceFiles((prev) => [file, ...prev]);
                updateForm("source_file_id", String(file.id));
              }}
            />

            <label className="source-file-select">
              <span>Или выберите файл из уже загруженных</span>
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
          </div>

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
                <option value="article">Article</option>
                <option value="conference">Conference</option>
                <option value="report">Report</option>
                <option value="book">Book</option>
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

          <MultiSelect
            label="Авторы"
            values={formData.author_ids}
            options={authors.map((author) => ({ id: author.id, label: author.full_name }))}
            onChange={(values) => updateForm("author_ids", values)}
          />

          <MultiSelect
            label="Темы"
            values={formData.topic_ids}
            options={topics.map((topic) => ({ id: topic.id, label: topic.name }))}
            onChange={(values) => updateForm("topic_ids", values)}
          />

          <MultiSelect
            label="Ключевые слова"
            values={formData.keyword_ids}
            options={keywords.map((keyword) => ({ id: keyword.id, label: keyword.name }))}
            onChange={(values) => updateForm("keyword_ids", values)}
          />

          <div className="form-actions">
            <button className="button" type="submit" disabled={isSaving}>
              {isSaving ? "Сохраняем..." : "Создать публикацию"}
            </button>

            <Link className="button button_secondary" to="/publications">
              Отмена
            </Link>
          </div>
        </form>
      </section>
    </section>
  );
}
