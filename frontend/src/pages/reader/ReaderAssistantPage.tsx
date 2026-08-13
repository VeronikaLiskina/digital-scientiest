import { FormEvent, KeyboardEvent, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import {
  assistantApi,
  type AssistantAnswerBlock,
  type ChatDetail,
  type ChatMessage,
  type ChatSummary,
} from "../../api/assistantApi";
import { ApiError } from "../../api/client";
import { AssistantSources, sourceLink } from "./AssistantSources";

function answerBlocks(message: ChatMessage): AssistantAnswerBlock[] {
  if (message.answer_blocks.length > 0) return message.answer_blocks;
  return [{ text: message.content, source_ids: [] }];
}

function sourceById(message: ChatMessage, sourceId: string) {
  return message.sources.find((source) => source.source_id === sourceId);
}

function renderAnswerBlock(
  message: ChatMessage,
  block: AssistantAnswerBlock,
  blockIndex: number,
) {
  return (
    <p className="chat-message__answer-block" key={`${message.id}-${blockIndex}`}>
      <span>{block.text}</span>
      {block.source_ids.map((sourceId) => {
        const source = sourceById(message, sourceId);
        if (!source) return null;

        const sourceNumber = message.sources.findIndex(
          (item) => item.source_id === sourceId,
        ) + 1;

        return (
          <Link
            className="chat-message__inline-source"
            to={sourceLink(source)}
            target="_blank"
            rel="noopener noreferrer"
            title={`${source.publication_title}, фрагмент ${source.chunk_index}`}
            aria-label={`Источник ${sourceNumber}: ${source.publication_title}, фрагмент ${source.chunk_index}`}
            key={sourceId}
          >
            [{sourceNumber}]
          </Link>
        );
      })}
    </p>
  );
}

interface ChatError {
  title: string;
  message: string;
  retryable: boolean;
}

function errorDetails(error: unknown): ChatError {
  if (error instanceof ApiError) {
    return {
      title: error.title ?? "Не удалось выполнить запрос",
      message: error.message,
      retryable: error.retryable,
    };
  }

  if (error instanceof TypeError) {
    return {
      title: "Нет связи с сервером",
      message: "Проверьте подключение и повторите запрос через несколько секунд.",
      retryable: true,
    };
  }

  return {
    title: "Что-то пошло не так",
    message:
      error instanceof Error && error.message
        ? error.message
        : "Не удалось выполнить запрос. Попробуйте ещё раз.",
    retryable: true,
  };
}

export function ReaderAssistantPage() {
  const [chats, setChats] = useState<ChatSummary[]>([]);
  const [activeChat, setActiveChat] = useState<ChatDetail | null>(null);
  const [query, setQuery] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<ChatError | null>(null);
  const [failedQuery, setFailedQuery] = useState<string | null>(null);
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
      setFailedQuery(null);
      setError(errorDetails(err));
    }
  }

  async function openChat(chatId: number) {
    setError(null);
    try {
      setActiveChat(await assistantApi.getChat(chatId));
    } catch (err) {
      setFailedQuery(null);
      setError(errorDetails(err));
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
      setFailedQuery(null);
      setError(errorDetails(err));
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
      setFailedQuery(null);
      setError(errorDetails(err));
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const content = query.trim();
    if (content.length < 2 || isLoading) return;

    await submitMessage(content);
  }

  async function submitMessage(content: string) {
    let submittedChatId = activeChat?.id ?? null;

    setIsLoading(true);
    setError(null);
    setFailedQuery(null);
    setQuery("");

    try {
      let chat = activeChat;
      if (!chat) {
        chat = await assistantApi.createChat();
        setActiveChat(chat);
      }
      submittedChatId = chat.id;

      const temporaryMessage: ChatMessage = {
        id: -Date.now(),
        chat_id: chat.id,
        role: "user",
        content,
        sources: [],
        answer_blocks: [],
        answer_origin: null,
        catalog: null,
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
      setError(errorDetails(err));
      setFailedQuery(content);

      if (submittedChatId !== null) {
        try {
          setActiveChat(await assistantApi.getChat(submittedChatId));
        } catch {
          // Keep the actionable generation error visible.
        }
      }
    } finally {
      setIsLoading(false);
    }
  }

  async function retryFailedQuery() {
    if (failedQuery && !isLoading) {
      await submitMessage(failedQuery);
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
                  {message.role === "assistant"
                    ? answerBlocks(message).map((block, blockIndex) =>
                        renderAnswerBlock(message, block, blockIndex),
                      )
                    : <p>{message.content}</p>}
                  {message.role === "assistant" && (
                    <AssistantSources sources={message.sources} />
                  )}
                  {message.catalog && message.catalog.items.length > 0 && (
                    <div className="chat-message__catalog">
                      {message.catalog.items.map((item) => (
                        <Link to={item.publication_url} key={item.publication_id}>
                          <strong>{item.title}</strong>
                          <span>
                            {[item.year, item.authors.join(", ")]
                              .filter(Boolean)
                              .join(" · ")}
                          </span>
                          {item.description && <span>{item.description}</span>}
                        </Link>
                      ))}
                    </div>
                  )}
                  {message.role === "assistant" && message.answer_origin === "external" && (
                    <div className="chat-message__notice chat-message__notice--external" role="alert">
                      <span aria-hidden="true">!</span>
                      <div>
                        <strong>Информация из внешнего источника</strong>
                        <p>Ответ основан на общих знаниях, а не на материалах архива.</p>
                      </div>
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

          {error && (
            <div className="chat-error" role="alert">
              <span className="chat-error__icon" aria-hidden="true">!</span>
              <div className="chat-error__content">
                <strong>{error.title}</strong>
                <p>{error.message}</p>
              </div>
              {error.retryable && failedQuery && (
                <button
                  className="button button_secondary chat-error__retry"
                  type="button"
                  disabled={isLoading}
                  onClick={retryFailedQuery}
                >
                  Повторить
                </button>
              )}
              <button
                className="chat-error__close"
                type="button"
                aria-label="Закрыть сообщение"
                onClick={() => setError(null)}
              >
                ×
              </button>
            </div>
          )}

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
