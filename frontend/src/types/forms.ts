export interface AuthorFormData {
  full_name: string;
  organization: string;
}

export interface TopicFormData {
  name: string;
  description: string;
}

export interface KeywordFormData {
  name: string;
}

export interface PublicationFormData {
  title: string;
  year: string;
  language: string;
  publication_type: string;
  doi: string;
  status: string;
  source_file_id: string;
  author_ids: number[];
  topic_ids: number[];
  keyword_ids: number[];
}
