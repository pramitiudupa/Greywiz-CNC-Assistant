import axios from "axios";
import type { WorkerProfile } from "./profile";

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
  progress?: string | null;
  source?: LibrarySource | null;
}

export interface LibrarySource {
  catalog_id: string;
  publisher: string;
  url: string;
  pages: string;
  edition_note: string;
  consented_by: string;
  consented_at: string;
}

export interface ChatResponse {
  answer: string;
  table_context: string;
  results: Array<{
    content: string;
    metadata: Record<string, unknown>;
  }>;
  latency?: number;
}

export async function getDocuments() {
  const { data } = await api.get<{ documents: DocumentSummary[] }>("/api/documents");
  return data.documents;
}

export async function uploadPdf(files: File[], provider?: string, title = "") {
  const formData = new FormData();
  files.forEach((file) => formData.append("file", file));
  formData.append("process", "true");
  formData.append("storage_format", "json");
  if (title) formData.append("title", title);
  if (provider) formData.append("provider", provider);

  const { data } = await api.post<{ document: DocumentSummary; processing: boolean }>(
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

export async function askDocument(documentId: string, message: string, retrievalK = 1, provider?: string, enableReranking = true) {
  const { data } = await api.post<ChatResponse>("/api/chat", {
    document_id: documentId,
    message,
    retrieval_k: retrievalK,
    provider,
    enable_reranking: enableReranking
  });
  return data;
}

export const apiBaseURL = baseURL;

export interface Machine {
  name: string;
  maker: string;
  model: string;
  controller: string;
  location: string;
  notes: string;
}

export interface DiagnosisCause {
  title: string;
  explanation: string;
  confidence: "high" | "medium" | "low";
  source_ids: string[];
}

export interface DiagnosisStep {
  instruction: string;
  source_ids: string[];
  needs_technician: boolean;
  checks_cause: number;
  from_documents?: boolean;
}

export interface DiagnosisSource {
  id: string;
  kind: "document" | "past_case";
  label: string;
  section: string;
  text: string;
  cited: boolean;
  document_id?: string;
  page?: number | null;
  case_id?: string;
}

export interface PhotoReading {
  is_machine_photo: boolean;
  part_shown: string;
  visible_text: string[];
  condition: string;
  search_phrases: string[];
  photo_quality_note: string;
}

export interface DiagnosisResult {
  case_id?: string;
  created_at?: string;
  summary: string;
  likely_cause: DiagnosisCause;
  other_causes: DiagnosisCause[];
  steps: DiagnosisStep[];
  general_advice: DiagnosisStep[];
  guided_steps?: DiagnosisStep[];
  profile?: WorkerProfile | null;
  safety_warnings: DiagnosisStep[];
  call_technician_if: string[];
  manual_covers_this: boolean;
  needs_more_detail?: boolean;
  question_for_worker: string;
  sources: DiagnosisSource[];
  where_we_looked?: { keywords: string[]; documents: Array<{ document_id: string; keywords: Record<string, number[]> }> };
  photo_reading: PhotoReading | null;
  machine: Machine | null;
  warnings: string[];
  timings: Record<string, number | string>;
}

export interface CaseSummary {
  id: string;
  created_at: string;
  description: string;
  has_photo: boolean;
  status: "open" | "fixed";
  fix_note: string;
  summary: string;
}

export interface CaseDetail {
  id: string;
  created_at: string;
  description: string;
  photo: string | null;
  status: "open" | "fixed";
  fix_note: string;
  result: DiagnosisResult;
}

export function errorMessage(err: unknown, fallback: string) {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof detail === "string" && detail ? detail : fallback;
}

export async function getMachine() {
  const { data } = await api.get<{ machine: Machine | null }>("/api/machine");
  return data.machine;
}

export async function saveMachine(machine: Machine) {
  const { data } = await api.put<{ machine: Machine }>("/api/machine", machine);
  return data.machine;
}

export async function diagnoseProblem(description: string, photo: File | null, provider?: string, profile?: WorkerProfile | null) {
  const formData = new FormData();
  formData.append("description", description);
  if (profile) formData.append("profile", JSON.stringify(profile));
  if (photo) formData.append("photo", photo);
  if (provider) formData.append("provider", provider);
  const { data } = await api.post<DiagnosisResult>("/api/diagnose", formData, {
    headers: { "Content-Type": "multipart/form-data" },
    timeout: 0
  });
  return data;
}

export async function getCases() {
  const { data } = await api.get<{ cases: CaseSummary[] }>("/api/cases");
  return data.cases;
}

export async function getCase(caseId: string) {
  const { data } = await api.get<CaseDetail>(`/api/cases/${caseId}`);
  return data;
}

export async function updateCase(caseId: string, status: "open" | "fixed", fixNote: string) {
  const { data } = await api.patch<CaseDetail>(`/api/cases/${caseId}`, { status, fix_note: fixNote });
  return data;
}

export async function deleteDocument(documentId: string) {
  await api.delete(`/api/documents/${encodeURIComponent(documentId)}`);
}

export function documentPageUrl(documentId: string, page?: number | null) {
  const url = `${baseURL}/api/documents/${encodeURIComponent(documentId)}/pdf/origin`;
  return page ? `${url}#page=${page}` : url;
}

export function casePhotoUrl(caseId: string) {
  return `${baseURL}/api/cases/${caseId}/photo`;
}

export interface LibrarySuggestion {
  id: string;
  title: string;
  publisher: string;
  url: string;
  domain: string;
  pages: string;
  edition_note: string;
  est_minutes: number;
}

export interface LibraryReport {
  machine_maker: string | null;
  documents: Array<{ id: string; covers: string[] }>;
  covered: Array<{ kind: string; label: string; documents: string[] }>;
  missing: Array<{ kind: string; label: string; why: string; suggestions: LibrarySuggestion[] }>;
  also_available: LibrarySuggestion[];
  references: Array<{ name: string; count: number }>;
  has_trusted_sources: boolean;
  processing: string[];
}

export async function checkLibrary() {
  const { data } = await api.get<LibraryReport>("/api/library/check");
  return data;
}

export async function addLibraryDocument(catalogId: string, consentedBy: string) {
  const { data } = await api.post<{ document: DocumentSummary }>(
    "/api/library/add",
    { catalog_id: catalogId, consent: true, consented_by: consentedBy },
    { timeout: 0 }
  );
  return data;
}

export async function makeCaseModel(caseId: string) {
  const { data } = await api.post<{ url: string; space: string }>(`/api/cases/${caseId}/model3d`, {}, { timeout: 0 });
  return `${baseURL}${data.url}`;
}

export function caseModelUrl(caseId: string) {
  return `${baseURL}/api/cases/${caseId}/model3d`;
}

export interface HealthItemBase { source_ids: string[]; from_documents: boolean }
export interface HealthOutlook {
  summary: string;
  upcoming_checks: Array<HealthItemBase & { item: string; when: string; why: string }>;
  risks: Array<HealthItemBase & { component: string; why: string; likelihood: "high" | "medium" | "low" }>;
  data_gaps: string[];
  sources: DiagnosisSource[];
  history: { total: number; open: number; repeats: Array<{ cause: string; count: number }> };
  usage: { hours_per_day: number; days_per_week: number; weekly_hours: number };
  model: string;
}

export async function machineHealth(hoursPerDay: number, daysPerWeek: number, provider?: string) {
  const { data } = await api.post<HealthOutlook>(
    "/api/machine/health",
    { hours_per_day: hoursPerDay, days_per_week: daysPerWeek, provider },
    { timeout: 0 }
  );
  return data;
}
