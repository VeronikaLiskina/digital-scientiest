import { apiRequest } from './client';
import type { DocumentChunk, ProcessingLog } from './types';

export const processingApi = {
  getAllLogs: () => apiRequest<ProcessingLog[]>('/processing-logs'),

  getLogsBySourceFile: (sourceFileId: number) =>
    apiRequest<ProcessingLog[]>('/processing-logs', {
      query: { source_file_id: sourceFileId },
    }),

  getChunksByPublication: (publicationId: number) =>
    apiRequest<DocumentChunk[]>('/document-chunks', {
      query: { publication_id: publicationId },
    }),
};
