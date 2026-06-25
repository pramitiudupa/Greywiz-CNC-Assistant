import {
  api,
  askDocument,
  DocumentSummary,
  getDocuments,
  processDocument,
  SourceTable,
  uploadPdf
} from "./api";

// @ts-ignore
const lucide = window.lucide;

type ViewMode = "home" | "chat";

const state: {
  activeDocumentId: string | null;
  busy: boolean;
  documents: DocumentSummary[];
  selectedFile: File | null;
  view: ViewMode;
} = {
  activeDocumentId: null,
  busy: false,
  documents: [],
  selectedFile: null,
  view: "home"
};

const $ = <T extends HTMLElement>(selector: string) => document.querySelector<T>(selector);
const $$ = <T extends HTMLElement>(selector: string) => document.querySelectorAll<T>(selector);

// Navigation
const navHome = $("#nav-home");
const navChat = $("#nav-chat");
const homeView = $("#home-view");
const chatView = $("#chat-view");

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
    processButton.disabled = busy || !state.selectedFile;
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

function switchView(view: ViewMode) {
  state.view = view;
  
  // Toggle nav styling
  if (view === "home") {
    navHome?.classList.add("bg-wiz-primary/10", "text-wiz-primary", "border", "border-wiz-primary/20");
    navHome?.classList.remove("text-wiz-muted", "hover:bg-wiz-panel_hover", "hover:text-wiz-text");
    navChat?.classList.remove("bg-wiz-primary/10", "text-wiz-primary", "border", "border-wiz-primary/20");
    navChat?.classList.add("text-wiz-muted", "hover:bg-wiz-panel_hover", "hover:text-wiz-text");
    
    homeView?.classList.remove("hidden");
    chatView?.classList.add("hidden");
  } else {
    navChat?.classList.add("bg-wiz-primary/10", "text-wiz-primary", "border", "border-wiz-primary/20");
    navChat?.classList.remove("text-wiz-muted", "hover:bg-wiz-panel_hover", "hover:text-wiz-text");
    navHome?.classList.remove("bg-wiz-primary/10", "text-wiz-primary", "border", "border-wiz-primary/20");
    navHome?.classList.add("text-wiz-muted", "hover:bg-wiz-panel_hover", "hover:text-wiz-text");
    
    homeView?.classList.add("hidden");
    chatView?.classList.remove("hidden");
  }
}

function selectDocumentAndChat(documentId: string) {
  state.activeDocumentId = documentId;
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
        const statusText = doc.status.charAt(0).toUpperCase() + doc.status.slice(1);
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
              </div>
            </div>
            
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

async function refreshDocuments() {
  try {
    state.documents = await getDocuments();
    renderDocuments();
    renderChatHeader();
  } catch (e) {
    console.error("Could not fetch documents", e);
  }
}

function stageFile(file: File) {
  showUploadError();
  if (file.type !== "application/pdf" && !file.name.toLowerCase().endsWith(".pdf")) {
    showUploadError("Please choose a valid PDF file.");
    return;
  }

  state.selectedFile = file;
  if (selectedFileName) selectedFileName.textContent = `${file.name}`;
  if (processButton) {
    processButton.disabled = false;
  }
}

async function processSelectedFile() {
  if (!state.selectedFile || state.busy) return;

  setBusy(true, `Uploading...`);

  try {
    const result = await uploadPdf(state.selectedFile, provider());
    state.activeDocumentId = result.document.id;
    state.selectedFile = null;
    
    if (selectedFileName) selectedFileName.textContent = "Drag and drop your PDF";
    if (fileInput) fileInput.value = "";
    
    await refreshDocuments();
    selectDocumentAndChat(result.document.id);
  } catch {
    showUploadError("Processing failed. Please check the terminal logs.");
  } finally {
    setBusy(false);
  }
}

function appendMessage(role: "user" | "assistant", content: string, loading = false, sourceTables = "") {
  if (!chatMessages) return;
  
  if (chatEmptyState && !chatEmptyState.classList.contains("hidden")) {
    chatEmptyState.classList.add("hidden");
  }

  const isUser = role === "user";
  const alignClass = isUser ? "ml-auto" : "mr-auto";
  const bgClass = isUser ? "bg-wiz-primary/20 border-wiz-primary/30" : "bg-wiz-panel border-wiz-border";
  const textClass = isUser ? "text-wiz-text" : "text-wiz-text";
  const icon = isUser ? "user" : "sparkles";
  const name = isUser ? "You" : "TableWIZ AI";
  const body = loading ? `<div class="flex items-center gap-2 text-wiz-muted"><i data-lucide="loader-2" class="h-4 w-4 animate-spin"></i> ${escapeHtml(content)}</div>` : escapeHtml(content);

  let sourceDropdownHtml = "";
  if (!loading && !isUser && sourceTables) {
    sourceDropdownHtml = `
      <details class="source-dropdown">
        <summary>
          <svg class="chevron-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"></polyline></svg>
          View Source Tables
        </summary>
        <div class="source-content scrollbar">${escapeHtml(sourceTables)}</div>
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
        <div class="rounded-xl p-4 text-sm leading-relaxed border backdrop-blur-sm ${bgClass} ${textClass}">
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
  appendMessage("assistant", "Analyzing source tables to generate grounded answer...", true);

  setBusy(true);
  try {
    const response = await askDocument(state.activeDocumentId, message, kValue(), provider());
    const sourceContext = response.table_context || "";
    replaceLastAssistantMessage(
      response.answer || "No relevant data found in tables to answer this question.",
      sourceContext
    );
  } catch {
    replaceLastAssistantMessage("Query failed. Please check backend logs or try a different question.");
  } finally {
    setBusy(false);
    if (chatInput) chatInput.focus();
  }
}

function bindEvents() {
  // Navigation
  navHome?.addEventListener("click", () => switchView("home"));
  navChat?.addEventListener("click", () => {
    if (state.activeDocumentId) switchView("chat");
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
    const file = event.dataTransfer?.files[0];
    if (file) stageFile(file);
  });
  fileInput?.addEventListener("change", () => {
    const file = fileInput.files?.[0];
    if (file) stageFile(file);
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
switchView("home");
bindEvents();
void refreshDocuments();
