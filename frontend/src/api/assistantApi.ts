import { rootApiClient } from "./client";

export interface AssistantSource {
  source_id: string;
  publication_id: number;
  publication_title: string;
  chunk_id: number;
  chunk_index: number;
  similarity: number;
}

export type AnswerOrigin = "internal" | "external" | "catalog";

export interface AssistantAnswerBlock {
  text: string;
  source_ids: string[];
}

export interface AssistantCatalogItem {
  publication_id: number;
  title: string;
  year: number | null;
  authors: string[];
  publication_type: string | null;
  publication_url: string;
  description: string | null;
}

export interface AssistantCatalog {
  total: number;
  returned_count: number;
  truncated: boolean;
  items: AssistantCatalogItem[];
}

export interface AssistantAskResponse {
  question: string;
  answer: string;
  sources: AssistantSource[];
  answer_blocks: AssistantAnswerBlock[];
  answer_origin: AnswerOrigin;
  catalog: AssistantCatalog | null;
}

export interface ChatMessage {
  id: number;
  chat_id: number;
  role: "user" | "assistant";
  content: string;
  sources: AssistantSource[];
  answer_blocks: AssistantAnswerBlock[];
  answer_origin: AnswerOrigin | null;
  catalog: AssistantCatalog | null;
  created_at: string;
}

export interface ChatSummary {
  id: number;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface ChatDetail extends ChatSummary {
  messages: ChatMessage[];
}

export interface ChatReply {
  chat: ChatSummary;
  user_message: ChatMessage;
  assistant_message: ChatMessage;
}

export const assistantApi = {
  getChats: () => rootApiClient.get<ChatSummary[]>("/assistant/chats"),
  getChat: (chatId: number) =>
    rootApiClient.get<ChatDetail>(`/assistant/chats/${chatId}`),
  createChat: () =>
    rootApiClient.post<ChatDetail>("/assistant/chats", {}),
  sendMessage: (chatId: number, content: string) =>
    rootApiClient.post<ChatReply>(`/assistant/chats/${chatId}/messages`, {
      content,
      limit: 6,
      min_similarity: 0.55,
      detail_percent: 100,
    }),
  deleteChat: (chatId: number) =>
    rootApiClient.delete<void>(`/assistant/chats/${chatId}`),
};
