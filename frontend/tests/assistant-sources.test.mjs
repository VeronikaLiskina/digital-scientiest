import assert from "node:assert/strict";
import test from "node:test";

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import {
  AssistantSources,
  uniqueAssistantSources,
} from "../src/pages/reader/AssistantSources.ts";

const firstSource = {
  source_id: "chunk-10",
  publication_id: 1,
  publication_title: "Первая публикация",
  chunk_id: 10,
  chunk_index: 2,
  similarity: 0.91,
};

test("does not render the sources block without used sources", () => {
  const html = renderToStaticMarkup(
    createElement(AssistantSources, { sources: [] }),
  );

  assert.equal(html, "");
});

test("renders a separate deduplicated sources block", () => {
  const duplicateSource = { ...firstSource };
  const secondSource = {
    ...firstSource,
    source_id: "chunk-20",
    publication_id: 2,
    publication_title: "Вторая публикация",
    chunk_id: 20,
    chunk_index: 4,
  };
  const sources = [firstSource, duplicateSource, secondSource];

  assert.deepEqual(
    uniqueAssistantSources(sources).map((source) => source.source_id),
    ["chunk-10", "chunk-20"],
  );

  const html = renderToStaticMarkup(
    createElement(AssistantSources, { sources }),
  );

  assert.match(html, /aria-label="Источники"/);
  assert.match(html, />Источники</);
  assert.equal(html.match(/Первая публикация/g)?.length, 1);
  assert.equal(html.match(/Вторая публикация/g)?.length, 1);
  assert.match(html, /href="\/publications\/1\?chunk=10"/);
});
