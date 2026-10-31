// "Missing documents" panel: shows which kinds of CNC document the shop has,
// which are missing, and official documents that could fill the gap. Nothing
// is downloaded until the person clicks "Yes, add it" on a consent card.

import { LibraryReport, LibrarySuggestion, addLibraryDocument, checkLibrary, errorMessage } from "./api";
import { getProfile } from "./profile";

// @ts-ignore
const lucide = window.lucide;

function escapeHtml(value: string) {
  return value.replace(/[&<>"']/g, (char) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" } as Record<string, string>
  )[char]);
}

let onAdded: () => void = () => undefined;
let pendingConsent: LibrarySuggestion | null = null;
let lastReport: LibraryReport | null = null;
let message = "";

function suggestionCard(s: LibrarySuggestion) {
  return `
    <div class="mt-2 rounded-lg border border-wiz-border bg-wiz-bg/40 p-3">
      <div class="flex items-start justify-between gap-3">
        <div class="min-w-0">
          <p class="text-sm font-medium">${escapeHtml(s.title)}</p>
          <p class="text-[11px] text-wiz-muted mt-0.5"><i data-lucide="badge-check" class="inline h-3 w-3 text-wiz-success"></i> ${escapeHtml(s.publisher)} · ${escapeHtml(s.domain)} · pages ${escapeHtml(s.pages)}</p>
          <p class="text-[11px] text-yellow-300/80 mt-0.5">${escapeHtml(s.edition_note)}</p>
        </div>
        <button data-suggest="${escapeHtml(s.id)}" class="flex-shrink-0 rounded-lg border border-wiz-primary/40 bg-wiz-primary/10 px-3 py-1.5 text-xs font-semibold text-blue-300 hover:bg-wiz-primary/20">Add…</button>
      </div>
    </div>`;
}

function consentCard(s: LibrarySuggestion) {
  return `
    <div class="mt-3 rounded-xl border-2 border-wiz-primary/50 bg-wiz-primary/10 p-4">
      <p class="text-sm font-semibold mb-1">Add this document to your machine's library?</p>
      <p class="text-xs text-wiz-text/80 mb-2">Greywiz will download <b>${escapeHtml(s.title)}</b> (pages ${escapeHtml(s.pages)}) from <b>${escapeHtml(s.domain)}</b>, the machine maker's official site, and read it so workers get answers from it. Takes about ${s.est_minutes} minutes.</p>
      <p class="text-[11px] text-wiz-muted mb-3">${escapeHtml(s.edition_note)} Your consent, your name and the source link are saved with the document.</p>
      <div class="flex gap-2">
        <button data-consent="yes" class="rounded-lg bg-wiz-primary px-4 py-2 text-xs font-semibold text-white hover:opacity-90">Yes, add it</button>
        <button data-consent="no" class="rounded-lg border border-wiz-border px-4 py-2 text-xs text-wiz-muted hover:text-wiz-text">Not now</button>
      </div>
    </div>`;
}

function render() {
  const host = document.querySelector<HTMLElement>("#library-panel");
  if (!host || !lastReport) return;
  const r = lastReport;
  const missingWithSources = r.missing.filter((m) => m.suggestions.length);
  const missingNoSource = r.missing.filter((m) => !m.suggestions.length);

  host.innerHTML = `
    <div class="rounded-xl border border-wiz-border bg-wiz-panel/50 p-4">
      <div class="flex items-center justify-between mb-3">
        <h3 class="text-sm font-semibold flex items-center gap-2"><i data-lucide="library" class="h-4 w-4 text-wiz-primary"></i>Is anything missing?</h3>
        <button data-recheck class="text-[11px] text-blue-300 hover:underline">Check again</button>
      </div>
      ${r.documents.length === 0 ? `<p class="text-xs text-wiz-muted">Upload a document first; Greywiz then checks what a CNC machine's document set should contain.</p>` : `
      <div class="flex flex-wrap gap-1.5 mb-3">
        ${r.covered.map((c) => `<span class="rounded-full border border-wiz-success/30 bg-wiz-success/10 px-2 py-0.5 text-[11px] text-emerald-300" title="${escapeHtml(c.documents.join(", "))}">✓ ${escapeHtml(c.label)}</span>`).join("")}
        ${r.missing.map((m) => `<span class="rounded-full border border-yellow-500/30 bg-yellow-500/10 px-2 py-0.5 text-[11px] text-yellow-300">Missing: ${escapeHtml(m.label)}</span>`).join("")}
      </div>
      ${r.references.length ? `<p class="text-[11px] text-wiz-muted mb-2">Your documents mention: ${r.references.map((x) => `“${escapeHtml(x.name)}” (${x.count}×)`).join(", ")}</p>` : ""}
      ${missingWithSources.map((m) => `
        <div class="mt-3">
          <p class="text-xs"><b>${escapeHtml(m.label)}</b> <span class="text-wiz-muted">· needed for ${escapeHtml(m.why)}</span></p>
          ${m.suggestions.map(suggestionCard).join("")}
        </div>`).join("")}
      ${r.missing.length === 0 ? `<p class="text-xs text-emerald-300 mt-1">Everything a CNC machine needs is covered.</p>` : ""}
      ${r.also_available.length ? `
        <div class="mt-3">
          <p class="text-xs"><b>Also available from official sources</b> <span class="text-wiz-muted">· optional extra coverage</span></p>
          ${r.also_available.map(suggestionCard).join("")}
        </div>` : ""}
      ${missingNoSource.length ? `<p class="mt-3 text-[11px] text-wiz-muted">No validated source on file for: ${missingNoSource.map((m) => escapeHtml(m.label)).join(", ")}. Ask the machine maker or your dealer for these.</p>` : ""}
      ${!r.has_trusted_sources && r.missing.length ? `<p class="mt-2 text-[11px] text-wiz-muted">Greywiz only suggests documents from official sources it has checked; set the machine maker under “Your CNC machine” to see them.</p>` : ""}
      `}
      ${pendingConsent ? consentCard(pendingConsent) : ""}
      ${message ? `<p class="mt-3 text-xs ${message.startsWith("!") ? "text-wiz-danger" : "text-wiz-success"}">${escapeHtml(message.replace(/^!/, ""))}</p>` : ""}
      ${r.processing.length ? `<p class="mt-2 text-[11px] text-wiz-muted">Processing now: ${r.processing.map(escapeHtml).join(", ")}</p>` : ""}
    </div>`;
  if (lucide) lucide.createIcons();

  host.querySelector("[data-recheck]")?.addEventListener("click", () => void refreshLibrary());
  host.querySelectorAll<HTMLElement>("[data-suggest]").forEach((btn) => {
    btn.addEventListener("click", () => {
      pendingConsent = [...r.missing.flatMap((m) => m.suggestions), ...r.also_available].find((s) => s.id === btn.dataset.suggest) ?? null;
      message = "";
      render();
    });
  });
  host.querySelector("[data-consent='no']")?.addEventListener("click", () => {
    pendingConsent = null;
    message = "Nothing was downloaded.";
    render();
  });
  host.querySelector("[data-consent='yes']")?.addEventListener("click", async () => {
    const chosen = pendingConsent;
    if (!chosen) return;
    pendingConsent = null;
    message = `Downloading from ${chosen.domain}…`;
    render();
    try {
      await addLibraryDocument(chosen.id, getProfile()?.name || getProfile()?.role || "");
      message = `Added. Greywiz is reading “${chosen.title}” now; it appears in your documents when ready.`;
      onAdded();
    } catch (err) {
      message = "!" + errorMessage(err, "Could not download the document.");
    }
    await refreshLibrary();
  });
}

export async function refreshLibrary() {
  try {
    lastReport = await checkLibrary();
    render();
  } catch (e) {
    console.error("Library check failed", e);
  }
}

export function initLibrary(afterAdd: () => void) {
  onAdded = afterAdd;
  void refreshLibrary();
}
