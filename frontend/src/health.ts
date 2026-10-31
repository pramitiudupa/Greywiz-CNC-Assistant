// Machine health screen: a forecast of upcoming checks and parts at risk,
// built from the problem history, the machine's documents and planned hours.

import { DiagnosisSource, HealthOutlook, documentPageUrl, errorMessage, machineHealth } from "./api";

// @ts-ignore
const lucide = window.lucide;

function escapeHtml(value: string) {
  return value.replace(/[&<>"']/g, (char) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" } as Record<string, string>
  )[char]);
}

function chips(ids: string[], sources: DiagnosisSource[]) {
  return ids.map((id) => {
    const s = sources.find((x) => x.id === id);
    if (!s) return "";
    if (s.kind === "document" && s.document_id) {
      return `<a href="${documentPageUrl(s.document_id, s.page)}" target="_blank" rel="noopener" title="${escapeHtml(s.label)}" class="inline-flex items-center gap-1 rounded-md border border-wiz-primary/30 bg-wiz-primary/10 px-1.5 py-0.5 text-[11px] text-blue-300"><i data-lucide="book-open" class="h-3 w-3"></i>${s.page ? `p. ${s.page}` : id}</a>`;
    }
    return `<span title="${escapeHtml(s.text)}" class="inline-flex items-center gap-1 rounded-md border border-emerald-500/30 bg-emerald-500/10 px-1.5 py-0.5 text-[11px] text-emerald-300"><i data-lucide="history" class="h-3 w-3"></i>Past problem</span>`;
  }).join(" ");
}

const LIKELIHOOD = {
  high: "text-red-300 bg-red-500/10 border-red-500/30",
  medium: "text-yellow-300 bg-yellow-500/10 border-yellow-500/30",
  low: "text-wiz-muted bg-wiz-panel border-wiz-border"
};

function notInDocs(fromDocuments: boolean) {
  return fromDocuments ? "" : `<span class="text-[11px] text-yellow-300">Not in your documents</span>`;
}

function render(o: HealthOutlook) {
  const host = document.querySelector<HTMLElement>("#health-result");
  if (!host) return;
  host.innerHTML = `
    <div class="flex flex-col gap-4">
      <div class="rounded-2xl border border-wiz-primary/40 bg-wiz-primary/10 p-5">
        <p class="text-xs font-semibold tracking-wider text-blue-300 mb-1">OUTLOOK · ${o.usage.weekly_hours} RUNNING HOURS A WEEK</p>
        <p class="text-lg font-semibold leading-relaxed">${escapeHtml(o.summary)}</p>
        <p class="text-xs text-wiz-muted mt-2">Based on ${o.history.total} reported problem${o.history.total === 1 ? "" : "s"} (${o.history.open} open)${o.history.repeats.length ? `; repeats: ${o.history.repeats.map((r) => `${escapeHtml(r.cause)} ×${r.count}`).join(", ")}` : ""}. Estimate for planning, not a guarantee.</p>
      </div>
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div class="glass-panel rounded-2xl p-5">
          <h3 class="text-sm font-semibold mb-3 flex items-center gap-2"><i data-lucide="calendar-check" class="h-4 w-4 text-wiz-primary"></i>Checks coming up</h3>
          <ol class="space-y-3 text-sm">
            ${o.upcoming_checks.map((c, i) => `
              <li class="flex gap-3">
                <span class="flex h-6 w-6 items-center justify-center rounded-full bg-wiz-primary/20 text-xs font-semibold text-wiz-primary flex-shrink-0">${i + 1}</span>
                <div class="min-w-0">
                  <p class="font-medium">${escapeHtml(c.item)}</p>
                  <p class="text-xs text-blue-200/90">${escapeHtml(c.when)}</p>
                  <p class="text-xs text-wiz-muted mt-0.5">${escapeHtml(c.why)}</p>
                  <div class="mt-1 flex flex-wrap items-center gap-1.5">${chips(c.source_ids, o.sources)} ${notInDocs(c.from_documents)}</div>
                </div>
              </li>`).join("")}
          </ol>
        </div>
        <div class="glass-panel rounded-2xl p-5">
          <h3 class="text-sm font-semibold mb-3 flex items-center gap-2"><i data-lucide="triangle-alert" class="h-4 w-4 text-yellow-400"></i>Parts most likely to cause the next stop</h3>
          <ul class="space-y-3 text-sm">
            ${o.risks.map((r) => `
              <li>
                <div class="flex flex-wrap items-center gap-2"><span class="font-medium">${escapeHtml(r.component)}</span>
                  <span class="rounded-full border px-2 py-0.5 text-[11px] ${LIKELIHOOD[r.likelihood]}">${r.likelihood} risk</span></div>
                <p class="text-xs text-wiz-muted mt-0.5">${escapeHtml(r.why)}</p>
                <div class="mt-1 flex flex-wrap items-center gap-1.5">${chips(r.source_ids, o.sources)} ${notInDocs(r.from_documents)}</div>
              </li>`).join("")}
          </ul>
        </div>
      </div>
      ${o.data_gaps.length ? `
      <div class="rounded-2xl border border-wiz-border bg-wiz-panel/60 p-4 text-sm">
        <p class="font-semibold mb-1 flex items-center gap-2"><i data-lucide="clipboard-list" class="h-4 w-4 text-wiz-primary"></i>Record these to make the forecast better</p>
        <ul class="text-wiz-muted space-y-0.5">${o.data_gaps.map((g) => `<li>• ${escapeHtml(g)}</li>`).join("")}</ul>
      </div>` : ""}
      <p class="text-[11px] text-wiz-muted text-center">Forecast by ${escapeHtml(o.model)} via the Gemini API from your documents and history.</p>
    </div>`;
  if (lucide) lucide.createIcons();
}

export function initHealth(getProvider: () => string | undefined) {
  const run = document.querySelector<HTMLButtonElement>("#health-run");
  const error = document.querySelector<HTMLElement>("#health-error");
  run?.addEventListener("click", async () => {
    const hours = Number(document.querySelector<HTMLInputElement>("#health-hours")?.value || 8);
    const days = Number(document.querySelector<HTMLInputElement>("#health-days")?.value || 6);
    const host = document.querySelector<HTMLElement>("#health-result");
    if (error) error.classList.add("hidden");
    run.disabled = true;
    if (host) host.innerHTML = `<div class="glass-panel rounded-2xl p-8 text-center text-sm text-wiz-muted"><i data-lucide="loader-2" class="h-6 w-6 animate-spin mx-auto mb-3 text-wiz-primary"></i>Reading the maintenance intervals and problem history…</div>`;
    if (lucide) lucide.createIcons();
    try {
      render(await machineHealth(hours, days, getProvider()));
    } catch (err) {
      if (host) host.innerHTML = "";
      if (error) {
        error.textContent = errorMessage(err, "Forecast failed. Check that the backend is running.");
        error.classList.remove("hidden");
      }
    } finally {
      run.disabled = false;
    }
  });
}
