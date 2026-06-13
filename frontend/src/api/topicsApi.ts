import { apiClient } from "./client";
import type { Topic } from "../types/entities";
import type { TopicFormData } from "../types/forms";

export const topicsApi = {
  getAll: () => apiClient.get<Topic[]>("/topics"),
  create: (data: TopicFormData) => apiClient.post<Topic>("/topics", data),
  update: (id: number, data: Partial<TopicFormData>) =>
    apiClient.patch<Topic>(`/topics/${id}`, data),
  delete: (id: number) => apiClient.delete<void>(`/topics/${id}`),
};
