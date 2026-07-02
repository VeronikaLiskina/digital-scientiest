import { rootApiClient } from "./client";

export interface AssistantAskRequest {
  question: string;
  limit?: number;
  min_similarity?: number;
}

export interface AssistantSource {
  publication_id: number;
  publication_title?: string | null;
  chunk_id: number;
  chunk_index?: number | null;
  text?: string | null;
  similarity: number;
}

export interface AssistantAskResponse {
  question: string;
  answer: string;
  sources: AssistantSource[];
}

export const assistantApi = {
  ask: (data: AssistantAskRequest) =>
    rootApiClient.post<AssistantAskResponse>("/assistant/ask", data),
};
