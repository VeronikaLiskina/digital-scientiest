import { apiClient } from "./client";
import type { Keyword } from "../types/entities";
import type { KeywordFormData } from "../types/forms";

export const keywordsApi = {
  getAll: () => apiClient.get<Keyword[]>("/keywords"),
  create: (data: KeywordFormData) => apiClient.post<Keyword>("/keywords", data),
  update: (id: number, data: Partial<KeywordFormData>) =>
    apiClient.patch<Keyword>(`/keywords/${id}`, data),
  delete: (id: number) => apiClient.delete<void>(`/keywords/${id}`),
};
