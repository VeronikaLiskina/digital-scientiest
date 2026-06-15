import { useState } from 'react';
import type { ChangeEvent, FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';

import type { Author, Id, Keyword, PublicationCreate, SourceFile, Topic } from '../../api/types';
import type { PublicationFormData } from '../../types/forms';
import { publicationsApi } from '../../api/publicationsApi';
import { PdfUpload } from '../files/PdfUpload';

type Props = {
  authors: Author[];
  topics: Topic[];
  keywords: Keyword[];
};

function selectedIds(event: ChangeEvent<HTMLSelectElement>): Id[] {
  return Array.from(event.target.selectedOptions).map((option) => Number(option.value));
}

export function PublicationForm({ authors, topics, keywords }: Props) {
  const navigate = useNavigate();

  const [sourceFile, setSourceFile] = useState<SourceFile | null>(null);
  const [form, setForm] = useState<PublicationCreate>({
    title: '',
    year: new Date().getFullYear(),
    language: 'ru',
    publication_type: 'article',
    doi: '',
    status: 'draft',
    source_file_id: null,
    author_ids: [],
    topic_ids: [],
    keyword_ids: [],
  });
  const [error, setError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  function update<K extends keyof PublicationCreate>(key: K, value: PublicationCreate[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();

    if (!form.title.trim()) {
      setError('Название публикации обязательно.');
      return;
    }

    try {
      setIsSaving(true);
      setError(null);

      const payload: PublicationFormData = {
        title: form.title,
        year: form.year ? String(form.year) : "",
        language: form.language ?? "",
        publication_type: form.publication_type ?? "",
        doi: form.doi ?? "",
        status: form.status ?? "draft",
        source_file_id: sourceFile?.id
          ? String(sourceFile.id)
          : form.source_file_id
            ? String(form.source_file_id)
            : "",
        author_ids: form.author_ids,
        topic_ids: form.topic_ids,
        keyword_ids: form.keyword_ids,
      };

      const created = await publicationsApi.create(payload);

      navigate(`/admin/publications/${created.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось сохранить публикацию.');
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <form className="card form" onSubmit={handleSubmit}>
      <PdfUpload
        onUploaded={(uploaded) => {
          setSourceFile(uploaded);
          update('source_file_id', uploaded.id);
        }}
      />

      <label>
        <span>Название *</span>
        <input value={form.title} onChange={(event) => update('title', event.target.value)} />
      </label>

      <div className="form-grid">
        <label>
          <span>Год</span>
          <input
            type="number"
            value={form.year ?? ''}
            onChange={(event) => update('year', event.target.value ? Number(event.target.value) : null)}
          />
        </label>

        <label>
          <span>Язык</span>
          <select value={form.language ?? ''} onChange={(event) => update('language', event.target.value)}>
            <option value="ru">ru</option>
            <option value="en">en</option>
          </select>
        </label>

        <label>
          <span>Тип публикации</span>
          <select
            value={form.publication_type ?? ''}
            onChange={(event) => update('publication_type', event.target.value)}
          >
            <option value="article">article</option>
            <option value="conference">conference</option>
            <option value="monograph">monograph</option>
            <option value="report">report</option>
          </select>
        </label>

        <label>
          <span>Статус</span>
          <select value={form.status ?? ''} onChange={(event) => update('status', event.target.value)}>
            <option value="draft">draft</option>
            <option value="ready">ready</option>
            <option value="processed">processed</option>
          </select>
        </label>
      </div>

      <label>
        <span>DOI</span>
        <input value={form.doi ?? ''} onChange={(event) => update('doi', event.target.value)} />
      </label>

      <label>
        <span>Авторы</span>
        <select multiple value={form.author_ids.map(String)} onChange={(event) => update('author_ids', selectedIds(event))}>
          {authors.map((author) => (
            <option key={author.id} value={author.id}>
              {author.full_name}
            </option>
          ))}
        </select>
      </label>

      <label>
        <span>Темы</span>
        <select multiple value={form.topic_ids.map(String)} onChange={(event) => update('topic_ids', selectedIds(event))}>
          {topics.map((topic) => (
            <option key={topic.id} value={topic.id}>
              {topic.name}
            </option>
          ))}
        </select>
      </label>

      <label>
        <span>Ключевые слова</span>
        <select
          multiple
          value={form.keyword_ids.map(String)}
          onChange={(event) => update('keyword_ids', selectedIds(event))}
        >
          {keywords.map((keyword) => (
            <option key={keyword.id} value={keyword.id}>
              {keyword.name}
            </option>
          ))}
        </select>
      </label>

      {error && <p className="error">{error}</p>}

      <button className="button" type="submit" disabled={isSaving}>
        {isSaving ? 'Сохраняем...' : 'Сохранить публикацию'}
      </button>
    </form>
  );
}
