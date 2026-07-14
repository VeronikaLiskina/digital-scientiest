import { rootApiClient } from "./client";

export interface AssistantSource {
  publication_id: number;
  publication_title: string;
  chunk_id: number;
  chunk_index: number;
  similarity: number;
}

export interface ChatMessage {
  id: number;
  chat_id: number;
  role: "user" | "assistant";
  content: string;
  sources: AssistantSource[];
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
      limit: 10,
      min_similarity: 0.55,
    }),
  deleteChat: (chatId: number) =>
    rootApiClient.delete<void>(`/assistant/chats/${chatId}`),
};
