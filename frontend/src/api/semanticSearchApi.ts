import { apiClient } from "./client";

export interface SemanticSearchResult {
  chunk_id: number;
  publication_id: number;
  chunk_index: number;
  text: string;
  publication_title: string;
  distance: number;
  similarity: number;
}

export interface SemanticSearchResponse {
  query: string;
  limit: number;
  min_similarity?: number;
  count?: number;
  results: SemanticSearchResult[];
}

export interface SemanticSearchParams {
  query: string;
  limit?: number;
  minSimilarity?: number;
}

export const semanticSearchApi = {
  search: ({ query, limit = 10, minSimilarity = 0.55 }: SemanticSearchParams) => {
    const params = new URLSearchParams({
      query,
      limit: String(limit),
      min_similarity: String(minSimilarity),
    });

    return apiClient.get<SemanticSearchResponse>(
      `/v1/search/semantic?${params.toString()}`,
    );
  },
};
