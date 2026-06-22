import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";

import { authorsApi } from "../api/authorsApi";
import { keywordsApi } from "../api/keywordsApi";
import { publicationsApi } from "../api/publicationsApi";
import { sourceFilesApi } from "../api/sourceFilesApi";
import { topicsApi } from "../api/topicsApi";
import { MultiSelect } from "../components/common/MultiSelect";
import { PageHeader } from "../components/common/PageHeader";
import { PdfUpload } from "../components/files/PdfUpload";
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

function uniqueIds(ids: number[]) {
  return Array.from(new Set(ids));
}

function mergeById<T extends { id: number }>(current: T[], incoming: T[]) {
  const map = new Map<number, T>();

  [...current, ...incoming].forEach((item) => {
    map.set(item.id, item);
  });

  return Array.from(map.values());
}

export function PublicationCreatePage() {
  const navigate = useNavigate();

  const [authors, setAuthors] = useState<Author[]>([]);
  const [topics, setTopics] = useState<Topic[]>([]);
  const [keywords, setKeywords] = useState<Keyword[]>([]);
  const [sourceFiles, setSourceFiles] = useState<SourceFile[]>([]);
  const [formData, setFormData] = useState<PublicationFormData>(emptyForm);
  const [selectedPdfFile, setSelectedPdfFile] = useState<File | null>(null);
  const [error, setError] = useState("");
  const [metadataMessage, setMetadataMessage] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [isExtractingMetadata, setIsExtractingMetadata] = useState(false);

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

  async function handleCreateAuthor(fullName: string) {
    const created = await authorsApi.create({ full_name: fullName, organization: "" });
    setAuthors((prev) => mergeById(prev, [created]));
    setFormData((prev) => ({ ...prev, author_ids: uniqueIds([...prev.author_ids, created.id]) }));
  }

  async function handleCreateTopic(name: string) {
    const created = await topicsApi.create({ name, description: "" });
    setTopics((prev) => mergeById(prev, [created]));
    setFormData((prev) => ({ ...prev, topic_ids: uniqueIds([...prev.topic_ids, created.id]) }));
  }

  async function handleCreateKeyword(name: string) {
    const created = await keywordsApi.create({ name });
    setKeywords((prev) => mergeById(prev, [created]));
    setFormData((prev) => ({ ...prev, keyword_ids: uniqueIds([...prev.keyword_ids, created.id]) }));
  }

  async function handlePdfSelected(file: File | null) {
    setSelectedPdfFile(file);
    setMetadataMessage("");

    if (!file) {
      return;
    }

    try {
      setIsExtractingMetadata(true);
      setError("");

      const preview = await sourceFilesApi.extractMetadata(file);

      if (preview.status === "duplicate_file") {
        setError(preview.message ?? "Такой PDF уже загружался");
        return;
      }

      const extracted = preview.extracted;

      if (!extracted) {
        setMetadataMessage("PDF выбран. Данные для автозаполнения не найдены.");
        return;
      }

      setFormData((prev) => ({
        ...prev,
        title: extracted.title || prev.title,
        year: extracted.year ? String(extracted.year) : prev.year,
        language: extracted.language || prev.language,
        publication_type: extracted.publication_type || prev.publication_type,
        doi: extracted.doi || prev.doi,
        source_file_id: "",

        // Важно: эти значения реально подставляются в форму,
        // но НЕ создаются в справочниках при выборе PDF.
        // Они будут сохранены через get_or_create только после нажатия
        // "Создать публикацию".
        author_names: extracted.authors.join("; "),
        topic_names: extracted.topics.join("; "),
        keyword_names: extracted.keywords.join("; "),
      }));

      setMetadataMessage(
        "PDF выбран. Если системе удалось распознать данные, они уже подставлены в форму. Проверьте их перед сохранением.",
      );
    } catch (err) {
      setMetadataMessage("");
      setError(err instanceof Error ? err.message : "Не удалось извлечь данные из PDF");
    } finally {
      setIsExtractingMetadata(false);
    }
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();

    if (!formData.title.trim()) {
      setError("Заполните название публикации");
      return;
    }

    try {
      setIsSaving(true);
      setError("");

      const created = selectedPdfFile
        ? await publicationsApi.createWithFile(formData, selectedPdfFile)
        : await publicationsApi.create(formData);

      navigate(`/admin/publications/${created.id}`);
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
        description="Загрузите PDF и проверьте карточку публикации перед сохранением."
        actions={
          <Link className="button button_secondary" to="/admin/publications">
            К списку
          </Link>
        }
      />

      {error && <p className="error">{error}</p>}
      {metadataMessage && <p className="success">{metadataMessage}</p>}

      <section className="card page-section">
        <form className="form" onSubmit={handleSubmit}>
          <div className="publication-create-page__file-block">
            <PdfUpload onFileSelected={handlePdfSelected} />

            <label className="source-file-select">
              <span>Или выберите файл из уже загруженных</span>
              <select
                value={formData.source_file_id}
                onChange={(event) => updateForm("source_file_id", event.target.value)}
                disabled={Boolean(selectedPdfFile)}
              >
                <option value="">Без файла</option>
                {sourceFiles.map((file) => (
                  <option key={file.id} value={file.id}>
                    {file.file_name}
                  </option>
                ))}
              </select>
              {selectedPdfFile && (
                <span className="muted">
                  {isExtractingMetadata
                    ? "Пытаемся извлечь данные из PDF..."
                    : "Выбран новый PDF — он будет загружен и привязан при создании публикации."}
                </span>
              )}
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

            <label>
              Авторы из PDF
              <textarea
                rows={3}
                value={formData.author_names}
                onChange={(event) => updateForm("author_names", event.target.value)}
                placeholder="E. I. Dementerova; I. V. Levitsky; Иванов И.И."
              />
              <span className="muted">
                Эти данные автоматически подставляются из PDF. Отредактируйте список перед сохранением.
              </span>
            </label>
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

            <label>
              Темы из PDF
              <textarea
                rows={2}
                value={formData.topic_names}
                onChange={(event) => updateForm("topic_names", event.target.value)}
                placeholder="Геология; Базы данных"
              />
              <span className="muted">
                Темы автоматически подбираются только из существующего справочника.
              </span>
            </label>
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

            <label>
              Ключевые слова из PDF
              <textarea
                rows={3}
                value={formData.keyword_names}
                onChange={(event) => updateForm("keyword_names", event.target.value)}
                placeholder="mafic rocks; geochemistry; semantic search"
              />
              <span className="muted">
                Разделяйте значения точкой с запятой, запятой или переносом строки.
              </span>
            </label>
          </div>

          <div className="form-actions">
            <button className="button" type="submit" disabled={isSaving || isExtractingMetadata}>
              {isSaving ? "Сохраняем..." : "Создать публикацию"}
            </button>

            <Link className="button button_secondary" to="/admin/publications">
              Отмена
            </Link>
          </div>
        </form>
      </section>
    </section>
  );
}
