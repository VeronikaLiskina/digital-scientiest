import type { Author, Keyword, Topic } from "../../types/entities";
import type { PublicationFormData } from "../../types/forms";
import { publicationTypeOptions } from "../../utils/publicationTypes";
import { MultiSelect } from "../common/MultiSelect";
import { QuickCreateField } from "./QuickCreateField";

type PublicationFormFieldsProps = {
  formData: PublicationFormData;
  authors: Author[];
  topics: Topic[];
  keywords: Keyword[];
  onChange: <K extends keyof PublicationFormData>(
    key: K,
    value: PublicationFormData[K],
  ) => void;
  onCreateAuthor: (name: string) => Promise<void>;
  onCreateTopic: (name: string) => Promise<void>;
  onCreateKeyword: (name: string) => Promise<void>;
  showExtractedFields?: boolean;
  highlightExtracted?: boolean;
};

export function PublicationFormFields({
  formData,
  authors,
  topics,
  keywords,
  onChange,
  onCreateAuthor,
  onCreateTopic,
  onCreateKeyword,
  showExtractedFields = false,
  highlightExtracted = false,
}: PublicationFormFieldsProps) {
  const extractedClassName = highlightExtracted
    ? "publication-form__field_review"
    : undefined;

  return (
    <div className="publication-form">
      <label>
        Название *
        <input
          className={extractedClassName}
          value={formData.title}
          onChange={(event) => onChange("title", event.target.value)}
          placeholder="Название публикации"
        />
      </label>

      <div className="publication-form__grid">
        <label>
          Год
          <input
            value={formData.year}
            onChange={(event) => onChange("year", event.target.value)}
            placeholder="2024"
          />
        </label>

        <label>
          Язык
          <select
            value={formData.language}
            onChange={(event) => onChange("language", event.target.value)}
          >
            <option value="ru">Русский</option>
            <option value="en">English</option>
          </select>
        </label>

        <label>
          Тип
          <select
            value={formData.publication_type}
            onChange={(event) => onChange("publication_type", event.target.value)}
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
            onChange={(event) => onChange("status", event.target.value)}
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
          onChange={(event) => onChange("doi", event.target.value)}
          placeholder="10.1234/example"
        />
      </label>

      <DictionarySection
        label="Авторы"
        values={formData.author_ids}
        options={authors.map((author) => ({ id: author.id, label: author.full_name }))}
        onChange={(values) => onChange("author_ids", values)}
        createLabel="Заполните ФИО автора"
        createPlaceholder="Новый автор"
        createButtonText="+ Добавить автора"
        onCreate={onCreateAuthor}
      >
        {showExtractedFields && (
          <ExtractedNamesField
            label="Авторы из PDF"
            value={formData.author_names}
            rows={3}
            className={extractedClassName}
            placeholder="Демонтерова Е.И.; Левицкий И.В.; Иванов А.В."
            hint="Проверьте предложенных авторов: удалите ошибочные значения или исправьте написание перед сохранением."
            onChange={(value) => onChange("author_names", value)}
          />
        )}
      </DictionarySection>

      <DictionarySection
        label="Темы"
        values={formData.topic_ids}
        options={topics.map((topic) => ({ id: topic.id, label: topic.name }))}
        onChange={(values) => onChange("topic_ids", values)}
        createLabel="Заполните название темы"
        createPlaceholder="Новая тема"
        createButtonText="+ Добавить тему"
        onCreate={onCreateTopic}
      >
        {showExtractedFields && (
          <ExtractedNamesField
            label="Темы из PDF"
            value={formData.topic_names}
            rows={2}
            className={extractedClassName}
            placeholder="Островодужные базальты; Платиновая группа"
            hint="Проверьте предложенные темы: оставьте только подходящие для публикации."
            onChange={(value) => onChange("topic_names", value)}
          />
        )}
      </DictionarySection>

      <DictionarySection
        label="Ключевые слова"
        values={formData.keyword_ids}
        options={keywords.map((keyword) => ({ id: keyword.id, label: keyword.name }))}
        onChange={(values) => onChange("keyword_ids", values)}
        createLabel="Заполните ключевое слово"
        createPlaceholder="Новое ключевое слово"
        createButtonText="+ Добавить ключевое слово"
        onCreate={onCreateKeyword}
      >
        {showExtractedFields && (
          <ExtractedNamesField
            label="Ключевые слова из PDF"
            value={formData.keyword_names}
            rows={3}
            className={extractedClassName}
            placeholder="островодужные базальты; элементы платиновой группы; geochemistry"
            hint="Разделяйте значения точкой с запятой, запятой или переносом строки."
            onChange={(value) => onChange("keyword_names", value)}
          />
        )}
      </DictionarySection>
    </div>
  );
}

type DictionarySectionProps = {
  label: string;
  values: number[];
  options: { id: number; label: string }[];
  onChange: (values: number[]) => void;
  createLabel: string;
  createPlaceholder: string;
  createButtonText: string;
  onCreate: (value: string) => Promise<void>;
  children?: ReactNode;
};

function DictionarySection({
  label,
  values,
  options,
  onChange,
  createLabel,
  createPlaceholder,
  createButtonText,
  onCreate,
  children,
}: DictionarySectionProps) {
  return (
    <div className="publication-form__section">
      <MultiSelect
        label={label}
        values={values}
        options={options}
        onChange={onChange}
      />
      <QuickCreateField
        label={createLabel}
        placeholder={createPlaceholder}
        buttonText={createButtonText}
        onCreate={onCreate}
      />
      {children}
    </div>
  );
}

type ExtractedNamesFieldProps = {
  label: string;
  value: string;
  rows: number;
  className?: string;
  placeholder: string;
  hint: string;
  onChange: (value: string) => void;
};

function ExtractedNamesField({
  label,
  value,
  rows,
  className,
  placeholder,
  hint,
  onChange,
}: ExtractedNamesFieldProps) {
  return (
    <label>
      {label}
      <textarea
        className={className}
        rows={rows}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
      />
      <span className="muted">{hint}</span>
    </label>
  );
}
import type { ReactNode } from "react";
