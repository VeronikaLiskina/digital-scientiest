import { FormEvent, KeyboardEvent, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import {
  assistantApi,
  type AssistantSource,
  type ChatDetail,
  type ChatMessage,
  type ChatSummary,
} from "../../api/assistantApi";

function sourceLink(source: AssistantSource) {
  return `/publications/${source.publication_id}`;
}

function rankedPublicationSources(sources: AssistantSource[]) {
  const bestByPublication = new Map<number, AssistantSource>();

  sources.forEach((source) => {
    const current = bestByPublication.get(source.publication_id);
    if (!current || source.similarity > current.similarity) {
      bestByPublication.set(source.publication_id, source);
    }
  });

  return Array.from(bestByPublication.values()).sort(
    (left, right) => right.similarity - left.similarity,
  );
}

function similarityPercent(similarity: number) {
  return similarity.toLocaleString("ru-RU", {
    style: "percent",
    maximumFractionDigits: 1,
  });
}

function errorText(error: unknown) {
  return error instanceof Error && error.message
    ? error.message
    : "Не удалось выполнить запрос. Попробуйте ещё раз.";
}

export function ReaderAssistantPage() {
  const [chats, setChats] = useState<ChatSummary[]>([]);
  const [activeChat, setActiveChat] = useState<ChatDetail | null>(null);
  const [query, setQuery] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    void loadChats();
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [activeChat?.messages, isLoading]);

  async function loadChats() {
    try {
      const items = await assistantApi.getChats();
      setChats(items);
      if (items.length > 0) {
        await openChat(items[0].id);
      }
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function openChat(chatId: number) {
    setError(null);
    try {
      setActiveChat(await assistantApi.getChat(chatId));
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function createChat() {
    setError(null);
    try {
      const chat = await assistantApi.createChat();
      setChats((current) => [chat, ...current]);
      setActiveChat(chat);
      setQuery("");
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function removeChat(chatId: number) {
    try {
      await assistantApi.deleteChat(chatId);
      const remaining = chats.filter((chat) => chat.id !== chatId);
      setChats(remaining);
      if (activeChat?.id === chatId) {
        if (remaining.length > 0) {
          await openChat(remaining[0].id);
        } else {
          setActiveChat(null);
        }
      }
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const content = query.trim();
    if (content.length < 2 || isLoading) return;

    setIsLoading(true);
    setError(null);
    setQuery("");

    try {
      let chat = activeChat;
      if (!chat) {
        chat = await assistantApi.createChat();
        setActiveChat(chat);
      }

      const temporaryMessage: ChatMessage = {
        id: -Date.now(),
        chat_id: chat.id,
        role: "user",
        content,
        sources: [],
        created_at: new Date().toISOString(),
      };
      setActiveChat({ ...chat, messages: [...chat.messages, temporaryMessage] });

      const reply = await assistantApi.sendMessage(chat.id, content);
      const updated: ChatDetail = {
        ...reply.chat,
        messages: [
          ...chat.messages,
          reply.user_message,
          reply.assistant_message,
        ],
      };
      setActiveChat(updated);
      setChats((current) => [
        reply.chat,
        ...current.filter((item) => item.id !== reply.chat.id),
      ]);
    } catch (err) {
      setError(errorText(err));
      if (activeChat) await openChat(activeChat.id);
    } finally {
      setIsLoading(false);
    }
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
    }
  }

  return (
    <section className="reader-assistant-page chat-page">
      <div className="page-header">
        <div>
          <h1>ИИ-ассистент</h1>
          <p>Задавайте уточняющие вопросы и возвращайтесь к прошлым диалогам.</p>
        </div>
      </div>

      <div className="chat-layout">
        <aside className="card chat-sidebar">
          <button className="button chat-sidebar__new" type="button" onClick={createChat}>
            + Новый чат
          </button>
          <div className="chat-sidebar__list">
            {chats.map((chat) => (
              <div
                className={`chat-sidebar__item ${activeChat?.id === chat.id ? "is-active" : ""}`}
                key={chat.id}
              >
                <button type="button" onClick={() => openChat(chat.id)}>
                  <strong>{chat.title}</strong>
                  <span>{new Date(chat.updated_at).toLocaleDateString("ru-RU")}</span>
                </button>
                <button
                  className="chat-sidebar__delete"
                  type="button"
                  aria-label="Удалить чат"
                  onClick={() => removeChat(chat.id)}
                >
                  ×
                </button>
              </div>
            ))}
            {chats.length === 0 && <p className="empty">История пока пуста</p>}
          </div>
        </aside>

        <div className="card chat-window">
          <div className="chat-messages" aria-live="polite">
            {!activeChat || activeChat.messages.length === 0 ? (
              <div className="chat-welcome">
                <strong>Начните новый диалог</strong>
                <p>Например: «Какие публикации есть по магматизму?»</p>
              </div>
            ) : (
              activeChat.messages.map((message) => (
                <article className={`chat-message chat-message--${message.role}`} key={message.id}>
                  <span className="chat-message__role">
                    {message.role === "user" ? "Вы" : "Ассистент"}
                  </span>
                  <p>{message.content}</p>
                  {message.sources.length > 0 && (
                    <div className="chat-message__sources">
                      {rankedPublicationSources(message.sources).map((source) => (
                        <Link
                          to={sourceLink(source)}
                          target="_blank"
                          rel="noopener noreferrer"
                          key={source.publication_id}
                        >
                          {source.publication_title || `Публикация #${source.publication_id}`}
                          <span className="chat-message__similarity">
                            {similarityPercent(source.similarity)}
                          </span>
                        </Link>
                      ))}
                    </div>
                  )}
                </article>
              ))
            )}
            {isLoading && (
              <div className="chat-message chat-message--assistant chat-message--loading">
                <span className="reader-assistant__spinner" aria-hidden="true" />
                <span>Ассистент готовит ответ…</span>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          {error && <div className="message message--error chat-error">{error}</div>}

          <form className="chat-composer" onSubmit={handleSubmit}>
            <textarea
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Введите сообщение…"
              rows={2}
              disabled={isLoading}
            />
            <button className="button" type="submit" disabled={query.trim().length < 2 || isLoading}>
              Отправить
            </button>
          </form>
        </div>
      </div>
    </section>
  );
}
