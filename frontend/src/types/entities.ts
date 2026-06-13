export type EntityId = number;

export interface Author {
  id: EntityId;
  full_name: string;
  organization?: string | null;
}

export interface Topic {
  id: EntityId;
  name: string;
  description?: string | null;
}

export interface Keyword {
  id: EntityId;
  name: string;
}

export interface SourceFile {
  id: EntityId;
  file_name: string;
  file_path: string;
  file_type: string;
  pdf_quality?: string | null;
  has_figures: boolean;
  has_tables: boolean;
  processing_status: string;
  comment?: string | null;
}

export interface Publication {
  id: EntityId;
  title: string;
  year?: number | null;
  language?: string | null;
  publication_type?: string | null;
  doi?: string | null;
  status: string;
  source_file_id?: number | null;
  authors: Author[];
  topics: Topic[];
  keywords: Keyword[];
}

export interface ProcessingLog {
  id: EntityId;
  source_file_id: number;
  step?: string | null;
  step_name?: string | null;
  status: string;
  message?: string | null;
  error_message?: string | null;
  created_at: string;
}

export interface DocumentChunk {
  id: EntityId;
  publication_id: number;
  text?: string | null;
  chunk_text?: string | null;
  page_number?: number | null;
  chunk_index: number;
  embedding?: number[] | null;
}
