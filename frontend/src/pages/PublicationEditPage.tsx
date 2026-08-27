import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { authorsApi } from "../api/authorsApi";
import { keywordsApi } from "../api/keywordsApi";
import { publicationsApi } from "../api/publicationsApi";
import { sourceFilesApi } from "../api/sourceFilesApi";
import type { ExtractedPublicationMetadata } from "../api/sourceFilesApi";
import { topicsApi } from "../api/topicsApi";
import { PageHeader } from "../components/common/PageHeader";
import { PublicationFormFields } from "../components/publications/PublicationFormFields";
import type { Author, Keyword, SourceFile, Topic } from "../types/entities";
import type { PublicationFormData } from "../types/forms";
import {
  mergeIds,
  mergeNames,
  pickExtractedValue,
} from "../utils/publicationForm";

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

function renderMetadataList(title: string, values?: string[]) {
  const preparedValues = (values ?? []).filter(Boolean);

  if (!preparedValues.length) {
    return null;
  }

  return (
    <div className="pdf-automation__result-group">
      <p className="pdf-automation__result-title">{title}</p>
      <div className="pdf-automation__chips">
        {preparedValues.map((value) => (
          <span className="pdf-automation__chip" key={`${title}-${value}`}>
            {value}
          </span>
        ))}
      </div>
    </div>
  );
}

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
  const [metadataMessage, setMetadataMessage] = useState("");
  const [extractedMetadata, setExtractedMetadata] =
    useState<ExtractedPublicationMetadata | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [isExtracting, setIsExtracting] = useState(false);
  const [fillEmptyOnly, setFillEmptyOnly] = useState(true);

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

  function handleSourceFileChange(value: string) {
    updateForm("source_file_id", value);
    setExtractedMetadata(null);
    setMetadataMessage("");
  }

  function applyExtractedMetadata(metadata: ExtractedPublicationMetadata) {
    setFormData((prev) => ({
      ...prev,
      title: pickExtractedValue(prev.title, metadata.title, fillEmptyOnly),
      year: pickExtractedValue(prev.year, metadata.year, fillEmptyOnly),
      language: pickExtractedValue(prev.language, metadata.language, fillEmptyOnly),
      publication_type: pickExtractedValue(
        prev.publication_type,
        metadata.publication_type,
        fillEmptyOnly,
      ),
      doi: pickExtractedValue(prev.doi, metadata.doi, fillEmptyOnly),
      author_ids: mergeIds(prev.author_ids, metadata.matched_author_ids),
      topic_ids: mergeIds(prev.topic_ids, metadata.matched_topic_ids),
      keyword_ids: mergeIds(prev.keyword_ids, metadata.matched_keyword_ids),
      author_names: mergeNames(prev.author_names, metadata.new_authors),
      topic_names: mergeNames(prev.topic_names, metadata.new_topics),
      keyword_names: mergeNames(prev.keyword_names, metadata.new_keywords),
    }));
  }

  async function handleExtractMetadata() {
    const sourceFileId = Number(formData.source_file_id);

    if (!sourceFileId) {
      setMetadataMessage("Выберите PDF-файл для автоматического заполнения.");
      return;
    }

    try {
      setIsExtracting(true);
      setError("");
      setMetadataMessage("");
      setExtractedMetadata(null);

      const preview = await sourceFilesApi.extractStoredMetadata(sourceFileId);

      if (!preview.extracted) {
        setMetadataMessage(
          preview.message || "Не удалось извлечь метаданные из PDF.",
        );
        return;
      }

      applyExtractedMetadata(preview.extracted);
      setExtractedMetadata(preview.extracted);
      setMetadataMessage("Данные из PDF применены к форме. Проверьте результат перед сохранением.");
    } catch (err) {
      setMetadataMessage(
        err instanceof Error
          ? err.message
          : "Не удалось обработать PDF для автозаполнения.",
      );
    } finally {
      setIsExtracting(false);
    }
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
              onChange={(event) => handleSourceFileChange(event.target.value)}
            >
              <option value="">Без файла</option>
              {sourceFiles.map((file) => (
                <option key={file.id} value={file.id}>
                  {file.file_name}
                </option>
              ))}
            </select>
          </label>

          <div className="pdf-automation">
            <div className="pdf-automation__content">
              <p className="pdf-automation__title">Автозаполнение из PDF</p>
              <label className="pdf-automation__toggle">
                <input
                  type="checkbox"
                  checked={fillEmptyOnly}
                  onChange={(event) => setFillEmptyOnly(event.target.checked)}
                />
                <span>Заполнять только пустые поля</span>
              </label>
              {metadataMessage && (
                <p className="pdf-automation__message">{metadataMessage}</p>
              )}
            </div>

            <div className="pdf-automation__actions">
              {extractedMetadata && (
                <button
                  className="button button_secondary"
                  type="button"
                  onClick={() => applyExtractedMetadata(extractedMetadata)}
                >
                  Применить снова
                </button>
              )}

              <button
                className="button button_secondary"
                type="button"
                disabled={!formData.source_file_id || isExtracting}
                onClick={handleExtractMetadata}
              >
                {isExtracting
                  ? "Обрабатываем..."
                  : extractedMetadata
                    ? "Обновить из PDF"
                    : "Заполнить из PDF"}
              </button>
            </div>
          </div>

          {extractedMetadata && (
            <div className="pdf-automation__preview">
              {extractedMetadata.title_warning && (
                <p className="pdf-automation__warning">
                  {extractedMetadata.title_warning}
                </p>
              )}

              <div className="pdf-automation__summary">
                <span>Заголовок: {extractedMetadata.title || "не найден"}</span>
                <span>Год: {extractedMetadata.year || "не найден"}</span>
                <span>DOI: {extractedMetadata.doi || "не найден"}</span>
              </div>

              {renderMetadataList("Авторы из PDF", extractedMetadata.authors)}
              {renderMetadataList("Темы из PDF", extractedMetadata.topics)}
              {renderMetadataList("Ключевые слова из PDF", extractedMetadata.keywords)}
              {renderMetadataList("Новые авторы", extractedMetadata.new_authors)}
              {renderMetadataList("Новые темы", extractedMetadata.new_topics)}
              {renderMetadataList("Новые ключевые слова", extractedMetadata.new_keywords)}

              {(formData.author_names ||
                formData.topic_names ||
                formData.keyword_names) && (
                <p>
                  Новые значения будут созданы в справочниках после сохранения
                  публикации.
                </p>
              )}
            </div>
          )}

          <PublicationFormFields
            formData={formData}
            authors={authors}
            topics={topics}
            keywords={keywords}
            onChange={updateForm}
            onCreateAuthor={handleCreateAuthor}
            onCreateTopic={handleCreateTopic}
            onCreateKeyword={handleCreateKeyword}
          />

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
