import { apiClient } from "./client";
import type { DocumentChunk } from "../types/entities";

export const documentChunksApi = {
  getAll: (publicationId?: number) => {
    const query = publicationId ? `?publication_id=${publicationId}` : "";
    return apiClient.get<DocumentChunk[]>(`/document-chunks${query}`);
  },
  getOne: (id: number) => apiClient.get<DocumentChunk>(`/document-chunks/${id}`),
  update: (id: number, chunkText: string) =>
    apiClient.patch<DocumentChunk>(`/document-chunks/${id}`, {
      chunk_text: chunkText,
    }),
  delete: (id: number) => apiClient.delete<void>(`/document-chunks/${id}`),
};
