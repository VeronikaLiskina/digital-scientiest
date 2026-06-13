import { apiClient } from "./client";
import type { Author } from "../types/entities";
import type { AuthorFormData } from "../types/forms";

export const authorsApi = {
  getAll: () => apiClient.get<Author[]>("/authors"),
  create: (data: AuthorFormData) => apiClient.post<Author>("/authors", data),
  update: (id: number, data: Partial<AuthorFormData>) =>
    apiClient.patch<Author>(`/authors/${id}`, data),
  delete: (id: number) => apiClient.delete<void>(`/authors/${id}`),
};
