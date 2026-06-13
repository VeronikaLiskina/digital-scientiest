import { apiClient } from "./client";
import type { ProcessingLog } from "../types/entities";

export const processingLogsApi = {
  getAll: (sourceFileId?: number) => {
    const query = sourceFileId ? `?source_file_id=${sourceFileId}` : "";
    return apiClient.get<ProcessingLog[]>(`/processing-logs${query}`);
  },
};
