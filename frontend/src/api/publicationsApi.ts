import { apiClient } from "./client";
import type { Publication } from "../types/entities";
import type { PublicationFormData } from "../types/forms";

export interface PublicationsFilters {
  title?: string;
  year?: string;
  author_id?: string;
  topic_id?: string;
  keyword_id?: string;
}

function buildQuery(filters: PublicationsFilters) {
  const params = new URLSearchParams();

  Object.entries(filters).forEach(([key, value]) => {
    if (value) {
      params.set(key, value);
    }
  });

  const query = params.toString();
  return query ? `?${query}` : "";
}

function splitNames(value: string) {
  return value
    .split(/[;,\n]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function normalizePublicationForm(data: PublicationFormData) {
  return {
    title: data.title.trim(),
    year: data.year ? Number(data.year) : null,
    language: data.language || null,
    publication_type: data.publication_type || null,
    doi: data.doi || null,
    status: data.status || "draft",
    source_file_id: data.source_file_id ? Number(data.source_file_id) : null,
    import_item_id: data.import_item_id ? Number(data.import_item_id) : null,
    author_ids: data.author_ids,
    topic_ids: data.topic_ids,
    keyword_ids: data.keyword_ids,
    author_names: splitNames(data.author_names),
    topic_names: splitNames(data.topic_names),
    keyword_names: splitNames(data.keyword_names),
  };
}

function buildPublicationFormData(data: PublicationFormData, file: File) {
  const formData = new FormData();

  formData.append("title", data.title.trim());

  if (data.year) {
    formData.append("year", String(data.year));
  }

  formData.append("language", data.language || "");
  formData.append("publication_type", data.publication_type || "");
  formData.append("doi", data.doi || "");
  formData.append("status", data.status || "draft");

  if (data.import_item_id) {
    formData.append("import_item_id", data.import_item_id);
  }

  formData.append("author_ids", data.author_ids.join(","));
  formData.append("topic_ids", data.topic_ids.join(","));
  formData.append("keyword_ids", data.keyword_ids.join(","));

  formData.append("author_names", data.author_names);
  formData.append("topic_names", data.topic_names);
  formData.append("keyword_names", data.keyword_names);

  formData.append("file", file);

  return formData;
}

export const publicationsApi = {
  getAll: (filters: PublicationsFilters = {}) =>
    apiClient.get<Publication[]>(`/publications${buildQuery(filters)}`),
  getOne: (id: number) => apiClient.get<Publication>(`/publications/${id}`),
  create: (data: PublicationFormData) =>
    apiClient.post<Publication>("/publications", normalizePublicationForm(data)),
  createWithFile: (data: PublicationFormData, file: File) =>
    apiClient.postForm<Publication>(
      "/publications/with-file",
      buildPublicationFormData(data, file),
    ),
  update: (id: number, data: PublicationFormData) =>
    apiClient.patch<Publication>(`/publications/${id}`, normalizePublicationForm(data)),
  delete: (id: number) => apiClient.delete<void>(`/publications/${id}`),
};
