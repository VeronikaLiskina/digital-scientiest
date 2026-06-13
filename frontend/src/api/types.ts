export type Id = number;

export type Author = {
  id: Id;
  full_name: string;
  organization?: string | null;
};

export type Topic = {
  id: Id;
  name: string;
  description?: string | null;
};

export type Keyword = {
  id: Id;
  name: string;
};

export type SourceFile = {
  id: Id;
  file_name: string;
  file_path: string;
  file_type: string;
  pdf_quality?: string | null;
  has_figures: boolean;
  has_tables: boolean;
  processing_status: string;
  comment?: string | null;
};

export type Publication = {
  id: Id;
  title: string;
  year?: number | null;
  language?: string | null;
  publication_type?: string | null;
  doi?: string | null;
  status?: string | null;
  source_file_id?: Id | null;
  authors: Author[];
  topics: Topic[];
  keywords: Keyword[];
};

export type PublicationCreate = {
  title: string;
  year?: number | null;
  language?: string | null;
  publication_type?: string | null;
  doi?: string | null;
  status?: string | null;
  source_file_id?: Id | null;
  author_ids: Id[];
  topic_ids: Id[];
  keyword_ids: Id[];
};

export type PublicationFilters = {
  title?: string;
  year?: string;
  author_id?: string;
  topic_id?: string;
  keyword_id?: string;
};

export type DocumentChunk = {
  id: Id;
  publication_id: Id;
  chunk_index?: number | null;
  text: string;
  embedding?: unknown | null;
};

export type ProcessingLog = {
  id: Id;
  source_file_id: Id;
  step?: string | null;
  status?: string | null;
  message?: string | null;
  created_at?: string | null;
};
