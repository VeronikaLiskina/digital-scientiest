import { createElement, type ReactElement } from "react";

import type { AssistantSource } from "../../api/assistantApi";

interface AssistantSourcesProps {
  sources: AssistantSource[];
}

export function sourceLink(source: AssistantSource) {
  return `/publications/${source.publication_id}?chunk=${source.chunk_id}`;
}

export function uniqueAssistantSources(sources: AssistantSource[]) {
  const uniqueSources = new Map<string, AssistantSource>();

  sources.forEach((source) => {
    if (!uniqueSources.has(source.source_id)) {
      uniqueSources.set(source.source_id, source);
    }
  });

  return Array.from(uniqueSources.values());
}

export function AssistantSources({
  sources,
}: AssistantSourcesProps): ReactElement | null {
  const uniqueSources = uniqueAssistantSources(sources);

  if (uniqueSources.length === 0) {
    return null;
  }

  return createElement(
    "section",
    {
      className: "chat-message__sources",
      "aria-label": "Источники",
    },
    createElement("strong", null, "Источники"),
    createElement(
      "ol",
      null,
      uniqueSources.map((source) =>
        createElement(
          "li",
          { key: source.source_id },
          createElement(
            "a",
            {
              href: sourceLink(source),
              target: "_blank",
              rel: "noopener noreferrer",
            },
            source.publication_title || `Публикация #${source.publication_id}`,
          ),
          createElement("span", null, `Фрагмент ${source.chunk_index}`),
        ),
      ),
    ),
  );
}
