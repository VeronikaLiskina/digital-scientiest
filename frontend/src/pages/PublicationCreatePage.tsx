import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { authorsApi } from "../api/authorsApi";
import { keywordsApi } from "../api/keywordsApi";
import { publicationImportsApi } from "../api/publicationImportsApi";
import { publicationsApi } from "../api/publicationsApi";
import { sourceFilesApi } from "../api/sourceFilesApi";
import { topicsApi } from "../api/topicsApi";
import { PageHeader } from "../components/common/PageHeader";
import { PdfUpload } from "../components/files/PdfUpload";
import { PublicationFormFields } from "../components/publications/PublicationFormFields";
import type { Author, Keyword, SourceFile, Topic } from "../types/entities";
import type { PublicationFormData } from "../types/forms";
import {
  getMatchedIds,
  getNewNames,
  mergeById,
  uniqueIds,
} from "../utils/publicationForm";

const emptyForm: PublicationFormData = {
  title: "",
  year: "",
  language: "ru",
  publication_type: "article",
  doi: "",
  status: "draft",
  source_file_id: "",
  import_item_id: "",
  author_ids: [],
  topic_ids: [],
  keyword_ids: [],
  author_names: "",
  topic_names: "",
  keyword_names: "",
};

type CatalogMatch = {
  id: number;
  name: string;
  extracted_name?: string;
};

type ExtractedWithMatches = {
  title?: string | null;
  title_source?: string | null;
  title_confidence?: string | null;
  title_warning?: string | null;
  year?: number | null;
  language?: string | null;
  publication_type?: string | null;
  doi?: string | null;

  authors?: string[];
  topics?: string[];
  keywords?: string[];

  matched_author_ids?: number[];
  matched_authors?: CatalogMatch[];
  new_authors?: string[];

  matched_topic_ids?: number[];
  matched_topics?: CatalogMatch[];
  new_topics?: string[];

  matched_keyword_ids?: number[];
  matched_keywords?: CatalogMatch[];
  new_keywords?: string[];
};

export function PublicationCreatePage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const importItemId = searchParams.get("import_item_id");
  const batchId = searchParams.get("batch_id");

  const [authors, setAuthors] = useState<Author[]>([]);
  const [topics, setTopics] = useState<Topic[]>([]);
  const [keywords, setKeywords] = useState<Keyword[]>([]);
  const [sourceFiles, setSourceFiles] = useState<SourceFile[]>([]);
  const [formData, setFormData] = useState<PublicationFormData>(emptyForm);
  const [selectedPdfFile, setSelectedPdfFile] = useState<File | null>(null);
  const [error, setError] = useState("");
  const [metadataMessage, setMetadataMessage] = useState("");
  const [metadataReviewStatus, setMetadataReviewStatus] = useState<"idle" | "needs_review" | "manual_entry">("idle");
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

  useEffect(() => {
    if (!importItemId) {
      return;
    }

    setIsExtractingMetadata(true);
    setMetadataReviewStatus("idle");
    setMetadataMessage("");
    setError("");

    publicationImportsApi
      .getItem(Number(importItemId))
      .then((item) => {
        const extracted = item.extracted_metadata as ExtractedWithMatches | null;

        if (!extracted) {
          setMetadataReviewStatus("manual_entry");
          setMetadataMessage("Данные из PDF не найдены. Карточку можно заполнить вручную.");
          setFormData((prev) => ({
            ...prev,
            import_item_id: String(item.id),
            source_file_id: item.source_file_id ? String(item.source_file_id) : prev.source_file_id,
          }));
          return;
        }

        applyExtractedMetadata(extracted, {
          sourceFileId: item.source_file_id,
          importItemId: String(item.id),
          replaceSelection: true,
        });
        setMetadataReviewStatus("needs_review");
        setMetadataMessage(
          [
            "Данные автоматически извлечены из PDF. Проверьте название, авторов, темы и ключевые слова перед сохранением.",
            extracted.title_warning,
          ]
            .filter(Boolean)
            .join(" "),
        );
      })
      .catch((err) => {
        setMetadataReviewStatus("manual_entry");
        setMetadataMessage("Не удалось загрузить данные массового импорта. Карточку можно заполнить вручную.");
        setError(err instanceof Error ? err.message : "Не удалось загрузить данные массового импорта");
      })
      .finally(() => setIsExtractingMetadata(false));
  }, [importItemId]);

  function updateForm<K extends keyof PublicationFormData>(key: K, value: PublicationFormData[K]) {
    setFormData((prev) => ({ ...prev, [key]: value }));
  }

  function applyExtractedMetadata(
    extracted: ExtractedWithMatches,
    options: { sourceFileId?: number | null; importItemId?: string; replaceSelection?: boolean } = {},
  ) {
    const matchedAuthorIds = getMatchedIds(extracted.matched_author_ids, extracted.matched_authors);
    const matchedTopicIds = getMatchedIds(extracted.matched_topic_ids, extracted.matched_topics);
    const matchedKeywordIds = getMatchedIds(extracted.matched_keyword_ids, extracted.matched_keywords);

    const newAuthorNames = getNewNames(extracted.new_authors, extracted.authors);
    const newTopicNames = getNewNames(extracted.new_topics, extracted.topics);
    const newKeywordNames = getNewNames(extracted.new_keywords, extracted.keywords);

    setAuthors((prev) =>
      mergeById(
        prev,
        (extracted.matched_authors ?? []).map(
          (author) =>
            ({
              id: author.id,
              full_name: author.name,
              organization: "",
            }) as Author,
        ),
      ),
    );

    setTopics((prev) =>
      mergeById(
        prev,
        (extracted.matched_topics ?? []).map(
          (topic) =>
            ({
              id: topic.id,
              name: topic.name,
              description: "",
            }) as Topic,
        ),
      ),
    );

    setKeywords((prev) =>
      mergeById(
        prev,
        (extracted.matched_keywords ?? []).map(
          (keyword) =>
            ({
              id: keyword.id,
              name: keyword.name,
            }) as Keyword,
        ),
      ),
    );

    setFormData((prev) => ({
      ...prev,
      title: extracted.title || prev.title,
      year: extracted.year ? String(extracted.year) : prev.year,
      language: extracted.language || prev.language,
      publication_type: extracted.publication_type || prev.publication_type,
      doi: extracted.doi || prev.doi,
      source_file_id: options.sourceFileId ? String(options.sourceFileId) : prev.source_file_id,
      import_item_id: options.importItemId ?? prev.import_item_id,
      author_ids: options.replaceSelection
        ? uniqueIds(matchedAuthorIds)
        : uniqueIds([...prev.author_ids, ...matchedAuthorIds]),
      topic_ids: options.replaceSelection
        ? uniqueIds(matchedTopicIds)
        : uniqueIds([...prev.topic_ids, ...matchedTopicIds]),
      keyword_ids: options.replaceSelection
        ? uniqueIds(matchedKeywordIds)
        : uniqueIds([...prev.keyword_ids, ...matchedKeywordIds]),
      author_names: newAuthorNames.join("; "),
      topic_names: newTopicNames.join("; "),
      keyword_names: newKeywordNames.join("; "),
    }));
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
    setMetadataReviewStatus("idle");

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

      const extracted = preview.extracted as ExtractedWithMatches | null;

      if (!extracted) {
        setMetadataReviewStatus("manual_entry");
        setMetadataMessage(
          preview.message?.trim() ||
            "PDF выбран, но данные для автозаполнения не найдены. Заполните карточку вручную.",
        );
        return;
      }

      applyExtractedMetadata(extracted);
      setFormData((prev) => ({
        ...prev,
        source_file_id: "",
        import_item_id: "",
      }));

      setMetadataReviewStatus("needs_review");
      setMetadataMessage(
        [
          "Данные автоматически извлечены из PDF. Проверьте название, авторов, темы и ключевые слова перед сохранением.",
          extracted.title_warning,
        ]
          .filter(Boolean)
          .join(" "),
      );
    } catch (err) {
      setMetadataReviewStatus("manual_entry");
      setMetadataMessage("Не удалось автоматически извлечь данные из PDF. Карточку можно заполнить вручную.");
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

      if (selectedPdfFile && created.source_file_id) {
        await sourceFilesApi.startProcessing(created.source_file_id);
      }

      navigate(
        batchId
          ? `/admin/publications/import?batch_id=${batchId}`
          : `/admin/publications/${created.id}${selectedPdfFile ? "?processing=started" : ""}`,
      );
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
      {metadataMessage && (
        <p className={metadataReviewStatus === "needs_review" ? "warning" : "success"}>
          {metadataMessage}
        </p>
      )}

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

          <PublicationFormFields
            formData={formData}
            authors={authors}
            topics={topics}
            keywords={keywords}
            onChange={updateForm}
            onCreateAuthor={handleCreateAuthor}
            onCreateTopic={handleCreateTopic}
            onCreateKeyword={handleCreateKeyword}
            showExtractedFields
            highlightExtracted={metadataReviewStatus === "needs_review"}
          />

          <div className="form-actions">
            <button className="button" type="submit" disabled={isSaving || isExtractingMetadata}>
              {isSaving
                ? "Сохраняем..."
                : metadataReviewStatus === "needs_review"
                  ? "Проверить и создать публикацию"
                  : "Создать публикацию"}
            </button>

            <Link
              className="button button_secondary"
              to={batchId ? `/admin/publications/import?batch_id=${batchId}` : "/admin/publications"}
            >
              Отмена
            </Link>
          </div>
        </form>
      </section>
    </section>
  );
}









