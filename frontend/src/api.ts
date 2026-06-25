import axios from "axios";

const baseURL = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

export const api = axios.create({
  baseURL,
  timeout: 120000
});

export type DocumentStatus = "completed" | "partial" | "processing" | "error";

export interface SourceTable {
  id: string;
  name: string;
  format: string;
  size_bytes: number;
}

export interface DocumentSummary {
  id: string;
  name: string;
  status: DocumentStatus;
  size_bytes: number | null;
  has_index: boolean;
  table_count: number;
  tables: SourceTable[];
}

export interface ChatResponse {
  answer: string;
  table_context: string;
  results: Array<{
    content: string;
    metadata: Record<string, unknown>;
  }>;
}

export async function getDocuments() {
  const { data } = await api.get<{ documents: DocumentSummary[] }>("/api/documents");
  return data.documents;
}

export async function uploadPdf(file: File, provider?: string) {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("process", "true");
  formData.append("storage_format", "json");
  if (provider) formData.append("provider", provider);

  const { data } = await api.post<{ document: DocumentSummary; processed: boolean }>(
    "/api/documents/upload",
    formData,
    { headers: { "Content-Type": "multipart/form-data" }, timeout: 0 }
  );
  return data;
}

export async function processDocument(documentId: string, force = false, provider?: string) {
  const { data } = await api.post<{ document: DocumentSummary; processed: boolean }>(
    `/api/documents/${encodeURIComponent(documentId)}/process`,
    { storage_format: "json", force, provider }
  );
  return data;
}

export async function askDocument(documentId: string, message: string, retrievalK = 1, provider?: string) {
  const { data } = await api.post<ChatResponse>("/api/chat", {
    document_id: documentId,
    message,
    retrieval_k: retrievalK,
    provider
  });
  return data;
}
