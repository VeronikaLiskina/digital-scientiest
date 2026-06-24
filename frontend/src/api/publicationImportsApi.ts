import { apiClient } from "./client";
import type { ExtractedPublicationMetadata } from "./sourceFilesApi";

export type PublicationImportItem = {
  id: number;
  batch_id: number;
  source_file_id?: number | null;
  publication_id?: number | null;
  original_file_name: string;
  status: "processing" | "needs_review" | "saved" | "duplicate" | "error" | "skipped" | string;
  error_message?: string | null;
  extracted_metadata?: ExtractedPublicationMetadata | null;
  title?: string | null;
  title_source?: string | null;
  title_confidence?: string | null;
  created_at: string;
  updated_at: string;
};

export type PublicationImportBatch = {
  id: number;
  status: string;
  total_files: number;
  processed_count: number;
  needs_review_count: number;
  saved_count: number;
  duplicate_count: number;
  error_count: number;
  created_at: string;
  updated_at: string;
  items: PublicationImportItem[];
};

export const publicationImportsApi = {
  create: (files: File[]) => {
    const formData = new FormData();
    files.forEach((file) => formData.append("files", file));

    return apiClient.postForm<PublicationImportBatch>("/publication-imports", formData);
  },
  getBatch: (id: number) => apiClient.get<PublicationImportBatch>(`/publication-imports/${id}`),
  getItem: (id: number) => apiClient.get<PublicationImportItem>(`/publication-imports/items/${id}`),
};
