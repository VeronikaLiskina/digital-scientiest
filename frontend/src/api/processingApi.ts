import { apiClient } from "./client";
import type { DocumentChunk, ProcessingLog } from "../types/entities";

export const processingApi = {
  getAllLogs: () => apiClient.get<ProcessingLog[]>("/processing-logs"),

  getLogsBySourceFile: (sourceFileId: number) =>
    apiClient.get<ProcessingLog[]>(
      `/processing-logs?source_file_id=${sourceFileId}`,
    ),

  getChunksByPublication: (publicationId: number) =>
    apiClient.get<DocumentChunk[]>(
      `/document-chunks?publication_id=${publicationId}`,
    ),
};
