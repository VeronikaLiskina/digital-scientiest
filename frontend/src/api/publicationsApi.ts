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

function normalizePublicationForm(data: PublicationFormData) {
  return {
    title: data.title.trim(),
    year: data.year ? Number(data.year) : null,
    language: data.language || null,
    publication_type: data.publication_type || null,
    doi: data.doi || null,
    status: data.status || "draft",
    source_file_id: data.source_file_id ? Number(data.source_file_id) : null,
    author_ids: data.author_ids,
    topic_ids: data.topic_ids,
    keyword_ids: data.keyword_ids,
  };
}

export const publicationsApi = {
  getAll: (filters: PublicationsFilters = {}) =>
    apiClient.get<Publication[]>(`/publications${buildQuery(filters)}`),
  getOne: (id: number) => apiClient.get<Publication>(`/publications/${id}`),
  create: (data: PublicationFormData) =>
    apiClient.post<Publication>("/publications", normalizePublicationForm(data)),
  update: (id: number, data: PublicationFormData) =>
    apiClient.patch<Publication>(`/publications/${id}`, normalizePublicationForm(data)),
  delete: (id: number) => apiClient.delete<void>(`/publications/${id}`),
};
