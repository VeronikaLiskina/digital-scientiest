import { API_BASE_URL, apiClient } from "./client";
import type { SourceFile } from "../types/entities";

export type ProcessPdfResult = {
  source_file_id: number;
  publication_id: number;
  chunks_created: number;
  status: string;
};



export const sourceFilesApi = {
  getAll: () => apiClient.get<SourceFile[]>("/source-files"),
  upload: (file: File) => {
    const formData = new FormData();
    formData.append("file", file);

    return apiClient.postForm<SourceFile>("/source-files/upload", formData);
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
