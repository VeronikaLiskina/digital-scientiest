import { API_BASE_URL, apiClient } from "./client";
import type { SourceFile } from "../types/entities";

export type ProcessPdfResult = {
  source_file_id: number;
  publication_id: number;
  chunks_created: number;
  status: string;
};

export type CatalogMatch = {
  id: number;
  name: string;
  extracted_name?: string;
};

export type ExtractedPublicationMetadata = {
  title?: string | null;
  title_source?: "pdf" | "filename" | "unknown" | string;
  title_confidence?: "high" | "medium" | "low" | string;
  title_warning?: string | null;
  year?: number | null;
  language?: string | null;
  publication_type?: string | null;
  doi?: string | null;
  authors: string[];
  keywords: string[];
  topics: string[];
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

export type SourceFileMetadataPreview = {
  status: "metadata_extracted" | "metadata_error" | "duplicate_file" | string;
  file_hash: string;
  review_status?: "needs_review" | "manual_entry" | "blocked" | string;
  duplicate_source_file_id?: number | null;
  message?: string | null;
  extracted?: ExtractedPublicationMetadata | null;
};

export const sourceFilesApi = {
  getAll: () => apiClient.get<SourceFile[]>("/source-files"),
  upload: (file: File) => {
    const formData = new FormData();
    formData.append("file", file);

    return apiClient.postForm<SourceFile>("/source-files/upload", formData);
  },
  extractMetadata: (file: File) => {
    const formData = new FormData();
    formData.append("file", file);

    return apiClient.postForm<SourceFileMetadataPreview>(
      "/source-files/extract-metadata",
      formData,
    );
  },
  update: (id: number, data: Partial<SourceFile>) =>
    apiClient.patch<SourceFile>(`/source-files/${id}`, data),
  delete: (id: number) => apiClient.delete<void>(`/source-files/${id}`),
  process: (sourceFileId: number) =>
    apiClient.post<ProcessPdfResult>(
      `/source-files/${sourceFileId}/process`,
      {},
    ),
  getDownloadUrl: (id: number) => `${API_BASE_URL}/source-files/${id}/download`,
};
