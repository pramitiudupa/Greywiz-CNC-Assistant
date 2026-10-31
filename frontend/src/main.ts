import {
  askDocument,
  deleteDocument,
  DocumentSummary,
  errorMessage,
  getDocuments,
  getMachine,
  Machine,
  saveMachine,
  uploadPdf
} from "./api";
import { initDiagnose, renderMachine } from "./diagnose";
import { initHealth } from "./health";
import { initLibrary, refreshLibrary } from "./library";

// @ts-ignore
const lucide = window.lucide;

type ViewMode = "home" | "chat" | "diagnose" | "health";

const state: {
  activeDocumentId: string | null;
  busy: boolean;
  documents: DocumentSummary[];
  selectedFiles: File[];
  view: ViewMode;
  machine: Machine | null;
} = {
  activeDocumentId: null,
  busy: false,
  documents: [],
  selectedFiles: [],
  view: "diagnose",
  machine: null
};

const $ = <T extends HTMLElement>(selector: string) => document.querySelector<T>(selector);
const $$ = <T extends HTMLElement>(selector: string) => document.querySelectorAll<T>(selector);

// Navigation
const navHome = $("#nav-home");
const navChat = $("#nav-chat");
const navDiagnose = $("#nav-diagnose");
const navHealth = $("#nav-health");
const healthView = $("#health-view");
const homeView = $("#home-view");
const chatView = $("#chat-view");
const diagnoseView = $("#diagnose-view");

// Machine
const machineForm = $("#machine-form") as HTMLFormElement | null;
const machineSaved = $("#machine-saved");
const sidebarMachine = $("#sidebar-machine");

// Settings
const providerSelect = $("#provider-select") as HTMLSelectElement | null;
const retrievalK = $("#retrieval-k") as HTMLInputElement | null;
const retrievalKValue = $("#retrieval-k-value");

// Upload
const uploadZone = $("#upload-zone");
const fileInput = $("#file-input") as HTMLInputElement | null;
const selectedFileName = $("#selected-file-name");
const processButton = $("#process-button") as HTMLButtonElement | null;
const uploadError = $("#upload-error");

// Dashboard
const sidebarDocList = $("#sidebar-doc-list");
const dashboardDocList = $("#dashboard-doc-list");
const processedCount = $("#processed-count");
const totalCount = $("#total-count");

// Chat
const chatDocumentTitle = $("#chat-document-title");
const chatMessages = $("#chat-messages");
const chatEmptyState = $("#chat-empty-state");
const chatInput = $("#chat-input") as HTMLTextAreaElement | null;
const sendButton = $("#send-button") as HTMLButtonElement | null;
const chatSuggestions = $$(".chat-suggestion");

function escapeHtml(value: string) {
  return value.replace(/[&<>"']/g, (char) => {
    const entities: Record<string, string> = {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#039;"
    };
    return entities[char];
  });
}

function provider() {
  return providerSelect?.value || undefined;
}

function kValue() {
  return Number(retrievalK?.value || 1);
}

function setBusy(busy: boolean, message = "") {
  state.busy = busy;
  if (processButton) {
    processButton.disabled = busy || !state.selectedFiles.length;
    processButton.textContent = busy ? (message || "Processing...") : "Start processing";
  }
  if (sendButton) sendButton.disabled = busy || !state.activeDocumentId;
  if (chatInput) chatInput.disabled = busy || !state.activeDocumentId;
}

function showUploadError(message = "") {
  if (!uploadError) return;
  uploadError.textContent = message;
  uploadError.classList.toggle("hidden", !message);
}

function formatSize(bytes: number | null) {
  if (!bytes) return "unknown size";
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function formatTitle(text: string): string {
  if (!text) return text;
  
  let ext = "";
  let name = text;
  const dotIndex = text.lastIndexOf(".");
  if (dotIndex > 0) {
    name = text.substring(0, dotIndex);
    ext = text.substring(dotIndex);
  }

  const hasUppercase = /[A-Z]/.test(name);
  const hasLowercase = /[a-z]/.test(name);
  
  if (hasUppercase && !hasLowercase) {
    let words = name.replace(/[_-]/g, " ").split(/\s+/);
    let titleCased = words.map(word => {
      if (!word) return "";
      return word.charAt(0).toUpperCase() + word.slice(1).toLowerCase();
    }).join(" ");
    return titleCased + ext;
  }
  
  return text;
}

function updatePdfPanelReferences(documentId: string) {
  const baseURL = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";
  
  const originUrl = `${baseURL}/api/documents/${encodeURIComponent(documentId)}/pdf/origin`;
  const layoutUrl = `${baseURL}/api/documents/${encodeURIComponent(documentId)}/pdf/layout`;
  
  const originIframe = $("#origin-pdf-iframe") as HTMLIFrameElement | null;
  const layoutIframe = $("#layout-pdf-iframe") as HTMLIFrameElement | null;
  const originDownload = $("#download-origin-pdf") as HTMLAnchorElement | null;
  const layoutDownload = $("#download-layout-pdf") as HTMLAnchorElement | null;
  
  if (originIframe) originIframe.src = originUrl;
  if (layoutIframe) layoutIframe.src = layoutUrl;
  if (originDownload) originDownload.href = originUrl;
  if (layoutDownload) layoutDownload.href = layoutUrl;
}

function formatSourceTables(results: Array<{ content: string; metadata: Record<string, any> }>): string {
  if (!results || !results.length) return "";
  
  const htmlParts: string[] = [];
  results.forEach((res, i) => {
    const tableId = res.metadata.table_id || `table_${i}`;
    const pageIdx = res.metadata.page_idx;
    let title = `Table ${i + 1}: ${tableId}`;
    if (pageIdx !== undefined && pageIdx !== null) {
      title += ` (Page ${Number(pageIdx) + 1})`;
    }
    
    const content = res.content || "";
    if (content.includes("TEXT:\n")) {
      const [head, body] = content.split("TEXT:\n");
      const section = head.replace("<context>\nSECTION:", "").trim();
      const pageLabel = pageIdx !== undefined && pageIdx !== null ? `Page ${Number(pageIdx) + 1}` : "Text";
      htmlParts.push(
        `<h4 class="font-bold mt-3 text-wiz-text text-xs border-b border-wiz-border pb-1 mb-2">${escapeHtml(`${pageLabel}: ${section}`)}</h4>` +
        `<pre class="source-content !bg-wiz-bg/50 !mt-1 text-[11px] font-mono leading-normal p-2 max-h-[250px] overflow-y-auto rounded border border-wiz-border/20">${escapeHtml(body.replace("</context>", "").trim())}</pre>`
      );
      return;
    }
    let contextPart = "";
    let tablePart = content;
    
    if (content.includes("TABLE (JSON):\n")) {
      const parts = content.split("TABLE (JSON):\n");
      contextPart = parts[0].replace("<context>\nCONTEXT:\n", "").trim();
      tablePart = parts[1].replace("</context>", "").trim();
    }
    
    let partHtml = `<h4 class="font-bold mt-3 text-wiz-text text-xs border-b border-wiz-border pb-1 mb-2">${escapeHtml(title)}</h4>`;
    if (contextPart) {
      partHtml += `
        <details class="source-dropdown mb-2">
          <summary class="flex justify-between items-center w-full !mt-1 !py-1.5 text-[11px] bg-wiz-panel/20 border border-wiz-border/30 rounded-md">
             <span>View Surrounding Context</span>
             <svg class="chevron-icon" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"></polyline></svg>
          </summary>
          <pre class="source-content !bg-wiz-bg/40 !mt-1 text-[11px] font-mono leading-normal p-2 max-h-[150px] overflow-y-auto rounded border border-wiz-border/20">${escapeHtml(contextPart)}</pre>
        </details>
      `;
    }
    
    let tableHtml = "";
    try {
      const trimmedTable = tablePart.trim();
      const grid = JSON.parse(trimmedTable);
      if (Array.isArray(grid)) {
        tableHtml = `<div class="overflow-x-auto my-2 border border-wiz-border rounded-lg"><table class="min-w-full divide-y divide-wiz-border text-xs text-left">`;
        grid.forEach((row, rowIndex) => {
          if (Array.isArray(row)) {
            if (rowIndex === 0) {
              tableHtml += `<thead class="bg-wiz-panel"><tr>`;
              row.forEach(cell => {
                tableHtml += `<th class="px-4 py-2 font-semibold text-wiz-text border-b border-wiz-border">${escapeHtml(String(cell))}</th>`;
              });
              tableHtml += `</tr></thead><tbody class="divide-y divide-wiz-border bg-wiz-bg/25">`;
            } else {
              tableHtml += `<tr class="hover:bg-wiz-panel/20">`;
              row.forEach(cell => {
                tableHtml += `<td class="px-4 py-2 text-wiz-muted whitespace-nowrap border-b border-wiz-border/50">${escapeHtml(String(cell))}</td>`;
              });
              tableHtml += `</tr>`;
            }
          }
        });
        if (grid.length > 0) {
          tableHtml += `</tbody>`;
        }
        tableHtml += `</table></div>`;
      } else {
        tableHtml = `<pre class="source-content !bg-wiz-bg/50 !mt-1 text-[11px] font-mono leading-normal p-2 max-h-[250px] overflow-y-auto rounded border border-wiz-border/20">${escapeHtml(tablePart)}</pre>`;
      }
    } catch (e) {
      tableHtml = `<pre class="source-content !bg-wiz-bg/50 !mt-1 text-[11px] font-mono leading-normal p-2 max-h-[250px] overflow-y-auto rounded border border-wiz-border/20">${escapeHtml(tablePart)}</pre>`;
    }
    
    partHtml += tableHtml;
    htmlParts.push(partHtml);
  });
  
  return htmlParts.join('<hr class="border-wiz-border/40 my-4">');
}

const ACTIVE_NAV = ["bg-wiz-primary/10", "text-wiz-primary", "border", "border-wiz-primary/20"];
const IDLE_NAV = ["text-wiz-muted", "hover:bg-wiz-panel_hover", "hover:text-wiz-text"];

function switchView(view: ViewMode) {
  state.view = view;
  const views: Array<[ViewMode, HTMLElement | null, HTMLElement | null]> = [
    ["home", navHome, homeView],
    ["chat", navChat, chatView],
    ["diagnose", navDiagnose, diagnoseView],
    ["health", navHealth, healthView]
  ];
  for (const [name, nav, panel] of views) {
    const active = name === view;
    nav?.classList.add(...(active ? ACTIVE_NAV : IDLE_NAV));
    nav?.classList.remove(...(active ? IDLE_NAV : ACTIVE_NAV));
    panel?.classList.toggle("hidden", !active);
  }
}

function renderSidebarMachine() {
  if (!sidebarMachine) return;
  const machine = state.machine;
  const ready = state.documents.filter((d) => d.status === "completed").length;
  sidebarMachine.innerHTML = machine
    ? `<div class="text-[10px] tracking-wider text-wiz-muted mb-1">MACHINE</div>
       <div class="font-semibold text-sm text-wiz-text truncate">${escapeHtml(machine.name)}</div>
       <div class="text-wiz-muted truncate">${escapeHtml([machine.maker, machine.model].filter(Boolean).join(" ") || "CNC machine")}</div>
       <div class="mt-2 text-wiz-muted">${ready} document${ready === 1 ? "" : "s"} ready</div>`
    : `<div class="text-yellow-400">No machine set up yet.</div>
       <div class="text-wiz-muted mt-1">Owner: add it under Machine &amp; documents.</div>`;
}

function fillMachineForm() {
  if (!machineForm || !state.machine) return;
  for (const [key, value] of Object.entries(state.machine)) {
    const input = machineForm.elements.namedItem(key) as HTMLInputElement | null;
    if (input) input.value = value;
  }
}

async function loadMachine() {
  try {
    state.machine = await getMachine();
  } catch (e) {
    console.error("Could not load machine", e);
  }
  fillMachineForm();
  renderSidebarMachine();
  renderMachine(state.machine);
}

function selectDocumentAndChat(documentId: string) {
  state.activeDocumentId = documentId;
  updatePdfPanelReferences(documentId);
  renderDocuments();
  renderChatHeader();
  switchView("chat");
  if (chatMessages) chatMessages.innerHTML = "";
  if (chatEmptyState) chatEmptyState.classList.remove("hidden");
  if (chatInput) {
    chatInput.disabled = false;
    chatInput.focus();
  }
  if (sendButton) sendButton.disabled = false;
}

function renderDocuments() {
  const processedDocs = state.documents.filter(d => d.status === "completed" || d.status === "partial");
  
  if (processedCount) processedCount.textContent = String(processedDocs.length);
  if (totalCount) totalCount.textContent = String(state.documents.length);
  renderSidebarMachine();

  // Render Sidebar List
  if (sidebarDocList) {
    sidebarDocList.innerHTML = state.documents.map(doc => {
      const isSelected = doc.id === state.activeDocumentId;
      const dotColor = doc.status === "completed" ? "bg-wiz-success" : (doc.status === "error" ? "bg-wiz-danger" : "bg-yellow-500");
      const activeClasses = isSelected ? "bg-wiz-panel_hover text-wiz-text" : "text-wiz-muted hover:bg-wiz-panel_hover/50 hover:text-wiz-text";
      
      return `
        <button data-sidebar-doc="${escapeHtml(doc.id)}" class="w-full flex items-center justify-between px-3 py-2 rounded-lg text-sm transition-colors ${activeClasses}">
          <div class="flex items-center gap-2 truncate pr-2">
            <i data-lucide="file-text" class="h-3.5 w-3.5 flex-shrink-0"></i>
            <span class="truncate">${escapeHtml(formatTitle(doc.name))}</span>
          </div>
          <div class="h-1.5 w-1.5 rounded-full ${dotColor} flex-shrink-0"></div>
        </button>
      `;
    }).join("");
    
    // Add event listeners
    sidebarDocList.querySelectorAll("[data-sidebar-doc]").forEach(btn => {
      btn.addEventListener("click", () => selectDocumentAndChat((btn as HTMLElement).dataset.sidebarDoc!));
    });
  }

  // Render Dashboard List
  if (dashboardDocList) {
    if (!state.documents.length) {
      dashboardDocList.innerHTML = `<div class="p-8 text-center text-sm text-wiz-muted border border-dashed border-wiz-border rounded-xl">No documents uploaded yet.</div>`;
    } else {
      dashboardDocList.innerHTML = state.documents.map(doc => {
        const isProcessed = doc.status === "completed" || doc.status === "partial";
        const statusColor = doc.status === "completed" ? "text-wiz-success bg-wiz-success/10 border-wiz-success/20" : (doc.status === "error" ? "text-wiz-danger bg-wiz-danger/10 border-wiz-danger/20" : "text-yellow-500 bg-yellow-500/10 border-yellow-500/20");
        const statusText = doc.status === "processing" ? (doc.progress || "Processing") : doc.status === "error" ? "Failed" : doc.status.charAt(0).toUpperCase() + doc.status.slice(1);
        const statusIcon = doc.status === "completed" ? "check-circle-2" : (doc.status === "error" ? "alert-circle" : "loader-2");

        return `
          <div class="glass-panel rounded-xl p-4 flex items-center justify-between gap-4 transition hover:border-wiz-primary/30">
            <div class="flex gap-4 items-center min-w-0 flex-1">
              <div class="flex h-10 w-10 items-center justify-center rounded-lg bg-wiz-panel border border-wiz-border text-wiz-primary flex-shrink-0">
                <i data-lucide="file-text" class="h-5 w-5"></i>
              </div>
              <div class="min-w-0">
                <h4 class="font-bold text-wiz-text mb-1 truncate">${escapeHtml(formatTitle(doc.name))}</h4>
                <div class="flex items-center gap-3 text-xs">
                  <span class="flex items-center gap-1.5 px-2 py-0.5 rounded-md border ${statusColor}">
                    <i data-lucide="${statusIcon}" class="h-3 w-3 ${doc.status === 'processing' ? 'animate-spin' : ''}"></i>
                    ${statusText}
                  </span>
                  <span class="text-wiz-muted">${formatSize(doc.size_bytes)}</span>
                  ${doc.table_count > 0 ? `<span class="text-wiz-muted">· ${doc.table_count} tables</span>` : ''}
                </div>
                ${doc.status === "error" && doc.progress ? `<p class="text-[11px] text-wiz-danger mt-1">${escapeHtml(doc.progress)}</p>` : ""}
                ${doc.source ? `<p class="text-[11px] text-wiz-muted mt-1" title="${escapeHtml(doc.source.url)}"><i data-lucide="badge-check" class="inline h-3 w-3 text-wiz-success"></i> From ${escapeHtml(doc.source.publisher)}, added with ${escapeHtml(doc.source.consented_by)}'s consent on ${escapeHtml(doc.source.consented_at.slice(0, 10))}</p>` : ""}
              </div>
            </div>
            
            <button data-delete-doc="${escapeHtml(doc.id)}" title="Remove this document" class="flex h-9 w-9 items-center justify-center rounded-lg border border-wiz-border text-wiz-muted hover:text-wiz-danger hover:border-wiz-danger/40 transition flex-shrink-0">
              <i data-lucide="trash-2" class="h-4 w-4"></i>
            </button>
            <button data-dashboard-doc="${escapeHtml(doc.id)}" class="${!isProcessed ? 'opacity-50 cursor-not-allowed' : 'hover:bg-wiz-panel_hover'} w-36 justify-center flex items-center gap-2 rounded-lg border border-wiz-border py-2 text-sm text-wiz-muted transition flex-shrink-0 whitespace-nowrap" ${!isProcessed ? 'disabled' : ''}>
              <i data-lucide="message-square" class="h-4 w-4"></i>
              Open chat
            </button>
          </div>
        `;
      }).join("");

      dashboardDocList.querySelectorAll("[data-dashboard-doc]").forEach(btn => {
        btn.addEventListener("click", () => selectDocumentAndChat((btn as HTMLElement).dataset.dashboardDoc!));
      });
      dashboardDocList.querySelectorAll("[data-delete-doc]").forEach(btn => {
        btn.addEventListener("click", () => void removeDocument((btn as HTMLElement).dataset.deleteDoc!));
      });
    }
  }

  // Re-init lucide icons for newly injected HTML
  if (lucide) lucide.createIcons();
}

function renderChatHeader() {
  if (!chatDocumentTitle) return;
  const doc = state.documents.find(d => d.id === state.activeDocumentId);
  chatDocumentTitle.textContent = doc ? formatTitle(doc.name) : "No document selected";
}

let pollTimer: number | undefined;
let wasProcessing = false;

async function refreshDocuments() {
  try {
    state.documents = await getDocuments();
    renderDocuments();
    renderChatHeader();
  } catch (e) {
    console.error("Could not fetch documents", e);
  }
  // While anything is being read, check again every few seconds so the status
  // and the "missing documents" panel update on their own.
  const processing = state.documents.some((d) => d.status === "processing");
  if (wasProcessing && !processing) void refreshLibrary();
  wasProcessing = processing;
  window.clearTimeout(pollTimer);
  if (processing) pollTimer = window.setTimeout(() => void refreshDocuments(), 5000);
}

async function removeDocument(documentId: string) {
  if (!window.confirm(`Remove "${documentId}" and its search index? Workers will no longer get answers from it.`)) return;
  try {
    await deleteDocument(documentId);
    if (state.activeDocumentId === documentId) state.activeDocumentId = null;
    await refreshDocuments();
  } catch (err) {
    window.alert(errorMessage(err, "Could not remove the document."));
  }
}

const IMAGE_FILE = /\.(jpe?g|png|webp|bmp|tiff?)$/i;

function stageFiles(files: File[]) {
  showUploadError();
  const isPdf = files.length === 1 && (files[0].type === "application/pdf" || files[0].name.toLowerCase().endsWith(".pdf"));
  const allImages = files.length > 0 && files.every((f) => f.type.startsWith("image/") || IMAGE_FILE.test(f.name));
  if (!isPdf && !allImages) {
    showUploadError("Choose one PDF, or one or more photos of manual pages.");
    return;
  }
  state.selectedFiles = files;
  if (selectedFileName) {
    selectedFileName.textContent = isPdf ? files[0].name : `${files.length} photo${files.length === 1 ? "" : "s"} of manual pages`;
  }
  if (processButton) processButton.disabled = false;
}

async function processSelectedFile() {
  if (!state.selectedFiles.length || state.busy) return;
  setBusy(true, "Uploading...");
  const titleInput = $("#doc-title") as HTMLInputElement | null;
  try {
    await uploadPdf(state.selectedFiles, provider(), titleInput?.value.trim() ?? "");
    state.selectedFiles = [];
    if (selectedFileName) selectedFileName.textContent = "Drag and drop a PDF or photos";
    if (fileInput) fileInput.value = "";
    if (titleInput) titleInput.value = "";
    showUploadError();
    await refreshDocuments();
  } catch (err) {
    showUploadError(errorMessage(err, "Upload failed. Please check the backend terminal."));
  } finally {
    setBusy(false);
  }
}

function appendMessage(role: "user" | "assistant", content: string, loading = false, sourceTablesHtml = "") {
  if (!chatMessages) return;
  
  if (chatEmptyState && !chatEmptyState.classList.contains("hidden")) {
    chatEmptyState.classList.add("hidden");
  }

  const isUser = role === "user";
  const alignClass = isUser ? "ml-auto" : "mr-auto";
  const bgClass = isUser ? "bg-wiz-primary/20 border-wiz-primary/30" : "bg-wiz-panel border-wiz-border";
  const textClass = isUser ? "text-wiz-text" : "text-wiz-text";
  const icon = isUser ? "user" : "sparkles";
  const name = isUser ? "You" : "Greywiz";
  const body = loading ? `<div class="flex items-center gap-2 text-wiz-muted"><i data-lucide="loader-2" class="h-4 w-4 animate-spin"></i> ${escapeHtml(content)}</div>` : escapeHtml(content);

  let sourceDropdownHtml = "";
  if (!loading && !isUser && sourceTablesHtml) {
    sourceDropdownHtml = `
      <details class="source-dropdown">
        <summary>
          <svg class="chevron-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"></polyline></svg>
          View sources
        </summary>
        <div class="source-content scrollbar">${sourceTablesHtml}</div>
      </details>
    `;
  }

  chatMessages.insertAdjacentHTML(
    "beforeend",
    `
      <div class="flex flex-col gap-1.5 w-full max-w-[85%] ${alignClass}">
        <div class="flex items-center gap-2 text-xs text-wiz-muted ${isUser ? 'flex-row-reverse' : ''}">
           <i data-lucide="${icon}" class="h-3.5 w-3.5"></i>
           <span class="font-semibold">${name}</span>
        </div>
        <div class="rounded-xl p-4 text-sm leading-relaxed border backdrop-blur-sm ${bgClass} ${textClass}" style="white-space: pre-wrap;">
           ${body}
           ${sourceDropdownHtml}
        </div>
      </div>
    `
  );
  if (lucide) lucide.createIcons();
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

function replaceLastAssistantMessage(content: string, sourceTables = "") {
  if (!chatMessages) return;
  const messages = chatMessages.children;
  // Remove last message if it's an assistant message
  if (messages.length > 0) {
     const lastMsg = messages[messages.length - 1];
     lastMsg.remove();
  }
  appendMessage("assistant", content, false, sourceTables);
}

async function sendQuery(query?: string) {
  const message = query || chatInput?.value.trim();
  if (!message || !state.activeDocumentId || state.busy) return;

  if (chatInput) chatInput.value = "";
  appendMessage("user", message);
  appendMessage("assistant", "Searching the document...", true);

  setBusy(true);
  try {
    const enableReranker = ($("#enable-reranker") as HTMLInputElement | null)?.checked ?? true;
    const response = await askDocument(state.activeDocumentId, message, kValue(), provider(), enableReranker);
    const sourceContextHtml = formatSourceTables(response.results || []);
    const answer = response.answer || "No relevant data found in tables to answer this question.";
    const latencyMsg = response.latency !== undefined ? `\n\n*Answer generated in ${response.latency.toFixed(2)} seconds.*` : "";
    replaceLastAssistantMessage(
      answer + latencyMsg,
      sourceContextHtml
    );
  } catch (err) {
    console.error("Query execution failed:", err);
    replaceLastAssistantMessage(errorMessage(err, "Query failed. Please check backend logs or try a different question."));
  } finally {
    setBusy(false);
    if (chatInput) chatInput.focus();
  }
}

function bindEvents() {
  // Navigation
  navHome?.addEventListener("click", () => switchView("home"));
  navChat?.addEventListener("click", () => {
    if (state.activeDocumentId) {
      switchView("chat");
      return;
    }
    const firstReady = state.documents.find((d) => d.status === "completed");
    if (firstReady) selectDocumentAndChat(firstReady.id);
    else switchView("home");
  });
  navDiagnose?.addEventListener("click", () => switchView("diagnose"));
  navHealth?.addEventListener("click", () => switchView("health"));
  navHome?.addEventListener("click", () => void refreshLibrary());

  machineForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(machineForm).entries()) as unknown as Machine;
    try {
      state.machine = await saveMachine(data);
      renderSidebarMachine();
      renderMachine(state.machine);
      void refreshLibrary();
      machineSaved?.classList.remove("hidden");
      window.setTimeout(() => machineSaved?.classList.add("hidden"), 2500);
    } catch (err) {
      window.alert(errorMessage(err, "Could not save the machine."));
    }
  });

  // PDF Panel Collapsible handlers
  const pdfPanel = $("#pdf-reference-panel");
  const togglePdfBtn = $("#toggle-pdf-panel-btn");
  const showPdfBtn = $("#show-pdf-panel-btn");
  
  togglePdfBtn?.addEventListener("click", () => {
    pdfPanel?.classList.add("hidden");
    showPdfBtn?.classList.remove("hidden");
  });
  
  showPdfBtn?.addEventListener("click", () => {
    pdfPanel?.classList.remove("hidden");
    showPdfBtn?.classList.add("hidden");
  });

  // Settings
  retrievalK?.addEventListener("input", () => {
    if (retrievalKValue && retrievalK) retrievalKValue.textContent = retrievalK.value;
  });

  // Upload
  uploadZone?.addEventListener("click", () => fileInput?.click());
  uploadZone?.addEventListener("dragover", (event) => {
    event.preventDefault();
    uploadZone.classList.add("border-wiz-primary", "bg-wiz-primary_glow");
  });
  uploadZone?.addEventListener("dragleave", () => uploadZone.classList.remove("border-wiz-primary", "bg-wiz-primary_glow"));
  uploadZone?.addEventListener("drop", (event) => {
    event.preventDefault();
    uploadZone.classList.remove("border-wiz-primary", "bg-wiz-primary_glow");
    const files = Array.from(event.dataTransfer?.files ?? []);
    if (files.length) stageFiles(files);
  });
  fileInput?.addEventListener("change", () => {
    const files = Array.from(fileInput.files ?? []);
    if (files.length) stageFiles(files);
  });
  processButton?.addEventListener("click", () => void processSelectedFile());

  // Chat
  sendButton?.addEventListener("click", () => void sendQuery());
  chatInput?.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void sendQuery();
    }
  });

  // Suggestions
  chatSuggestions.forEach(btn => {
    btn.addEventListener("click", () => {
      const text = btn.querySelector("span")?.textContent;
      if (text) {
        if (chatInput) chatInput.value = text + " ";
        chatInput?.focus();
      }
    });
  });
}

// Init
switchView("diagnose");
bindEvents();
initDiagnose(provider);
void refreshDocuments();
void loadMachine();
initLibrary(() => void refreshDocuments());
initHealth(provider);
