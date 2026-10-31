import {
  CaseSummary,
  DiagnosisCause,
  DiagnosisResult,
  DiagnosisSource,
  DiagnosisStep,
  Machine,
  casePhotoUrl,
  diagnoseProblem,
  documentPageUrl,
  errorMessage,
  getCase,
  getCases,
  updateCase
} from "./api";
import { WorkerProfile, askWhoYouAre, getProfile, levelExplanation, onProfileChange } from "./profile";

// @ts-ignore
const lucide = window.lucide;

const $ = <T extends HTMLElement>(selector: string) => document.querySelector<T>(selector);

const photoZone = $("#photo-zone");
const photoInput = $("#photo-input") as HTMLInputElement | null;
const photoPreview = $("#photo-preview") as HTMLImageElement | null;
const photoEmpty = $("#photo-empty");
const photoName = $("#photo-name");
const photoRemove = $("#photo-remove");
const problemText = $("#problem-text") as HTMLTextAreaElement | null;
const diagnoseButton = $("#diagnose-button") as HTMLButtonElement | null;
const diagnoseError = $("#diagnose-error");
const diagnosisPanel = $("#diagnosis-panel");
const caseList = $("#case-list");
const diagnoseMachine = $("#diagnose-machine");

const state: {
  photo: File | null;
  photoUrl: string | null;
  busy: boolean;
  cases: CaseSummary[];
  activeCaseId: string | null;
} = { photo: null, photoUrl: null, busy: false, cases: [], activeCaseId: null };

let getProvider: () => string | undefined = () => undefined;

function escapeHtml(value: string) {
  return value.replace(/[&<>"']/g, (char) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" } as Record<string, string>
  )[char]);
}

function icons() {
  if (lucide) lucide.createIcons();
}

function showError(message = "") {
  if (!diagnoseError) return;
  diagnoseError.textContent = message;
  diagnoseError.classList.toggle("hidden", !message);
}

function setPhoto(file: File | null) {
  if (state.photoUrl) URL.revokeObjectURL(state.photoUrl);
  state.photo = file;
  state.photoUrl = file ? URL.createObjectURL(file) : null;
  if (photoPreview) {
    photoPreview.src = state.photoUrl ?? "";
    photoPreview.classList.toggle("hidden", !file);
  }
  photoEmpty?.classList.toggle("hidden", !!file);
  photoRemove?.classList.toggle("hidden", !file);
  if (photoName) photoName.textContent = file ? file.name : "No photo added";
  if (photoInput && !file) photoInput.value = "";
}

function stagePhoto(file: File) {
  showError();
  if (!file.type.startsWith("image/")) {
    showError("Please choose a photo (JPG, PNG or HEIC).");
    return;
  }
  setPhoto(file);
}

export function renderMachine(machine: Machine | null) {
  if (!diagnoseMachine) return;
  if (!machine) {
    diagnoseMachine.innerHTML = `
      <div class="flex items-start gap-2 text-yellow-400">
        <i data-lucide="alert-triangle" class="h-4 w-4 mt-0.5 flex-shrink-0"></i>
        <span>The machine is not set up yet. The owner can add it under <b>Machine &amp; documents</b>. You can still report a problem.</span>
      </div>`;
  } else {
    const detail = [machine.maker, machine.model].filter(Boolean).join(" ");
    diagnoseMachine.innerHTML = `
      <div class="flex items-center gap-3">
        <div class="flex h-9 w-9 items-center justify-center rounded-lg bg-wiz-primary/15 text-wiz-primary flex-shrink-0"><i data-lucide="factory" class="h-4 w-4"></i></div>
        <div class="min-w-0">
          <div class="font-semibold truncate">${escapeHtml(machine.name)}</div>
          <div class="text-xs text-wiz-muted truncate">${escapeHtml([detail, machine.controller].filter(Boolean).join(" · ") || "CNC machine")}</div>
        </div>
      </div>
      ${machine.notes ? `<p class="text-xs text-wiz-muted mt-2">${escapeHtml(machine.notes)}</p>` : ""}`;
  }
  icons();
}

function sourceChips(ids: string[], sources: DiagnosisSource[]) {
  return ids.map((id) => {
    const source = sources.find((s) => s.id === id);
    if (!source) return "";
    if (source.kind === "document" && source.document_id) {
      const label = source.page ? `p. ${source.page}` : id;
      return `<a href="${documentPageUrl(source.document_id, source.page)}" target="_blank" rel="noopener"
        title="${escapeHtml(source.label)}"
        class="inline-flex items-center gap-1 rounded-md border border-wiz-primary/30 bg-wiz-primary/10 px-1.5 py-0.5 text-[11px] text-blue-300 hover:bg-wiz-primary/20 no-underline">
        <i data-lucide="book-open" class="h-3 w-3"></i>${escapeHtml(label)}</a>`;
    }
    return `<a href="#source-${id}" title="${escapeHtml(source.label)}"
      class="inline-flex items-center gap-1 rounded-md border border-emerald-500/30 bg-emerald-500/10 px-1.5 py-0.5 text-[11px] text-emerald-300">
      <i data-lucide="history" class="h-3 w-3"></i>Past fix</a>`;
  }).join(" ");
}

const CONFIDENCE_STYLE: Record<string, string> = {
  high: "text-wiz-success bg-wiz-success/10 border-wiz-success/30",
  medium: "text-yellow-400 bg-yellow-500/10 border-yellow-500/30",
  low: "text-wiz-muted bg-wiz-panel border-wiz-border"
};

function confidencePill(cause: DiagnosisCause) {
  const label = { high: "Very likely", medium: "Possible", low: "Less certain" }[cause.confidence];
  return `<span class="rounded-full border px-2 py-0.5 text-[11px] font-medium ${CONFIDENCE_STYLE[cause.confidence]}">${label}</span>`;
}

function stepList(steps: DiagnosisStep[], sources: DiagnosisSource[]) {
  return steps.map((step, i) => `
    <li class="flex gap-3">
      <span class="flex h-6 w-6 items-center justify-center rounded-full bg-wiz-primary/20 text-xs font-semibold text-wiz-primary flex-shrink-0">${i + 1}</span>
      <div class="flex-1 min-w-0">
        <p class="leading-relaxed">${escapeHtml(step.instruction)}</p>
        <div class="mt-1 flex flex-wrap items-center gap-1.5">
          ${step.needs_technician ? `<span class="inline-flex items-center gap-1 rounded-md border border-orange-500/40 bg-orange-500/10 px-1.5 py-0.5 text-[11px] text-orange-300"><i data-lucide="hard-hat" class="h-3 w-3"></i>Technician only</span>` : ""}
          ${step.from_documents === false ? `<span class="inline-flex items-center gap-1 rounded-md border border-yellow-500/40 bg-yellow-500/10 px-1.5 py-0.5 text-[11px] text-yellow-300"><i data-lucide="info" class="h-3 w-3"></i>Not in your documents</span>` : ""}
          ${sourceChips(step.source_ids, sources)}
        </div>
      </div>
    </li>`).join("");
}

function card(title: string, icon: string, body: string, extraClass = "") {
  return `
    <div class="glass-panel rounded-2xl p-5 ${extraClass}">
      <h3 class="text-sm font-semibold mb-3 flex items-center gap-2"><i data-lucide="${icon}" class="h-4 w-4 text-wiz-primary"></i>${title}</h3>
      ${body}
    </div>`;
}

function renderEmpty() {
  if (!diagnosisPanel) return;
  diagnosisPanel.innerHTML = `
    <div class="glass-panel rounded-2xl p-10 h-full min-h-[420px] flex flex-col items-center justify-center text-center">
      <div class="flex h-16 w-16 items-center justify-center rounded-2xl bg-wiz-panel border border-wiz-border mb-5">
        <i data-lucide="scan-search" class="h-8 w-8 text-wiz-primary"></i>
      </div>
      <h3 class="text-xl font-bold mb-2">The answer will appear here</h3>
      <p class="text-sm text-wiz-muted max-w-md mb-8">Greywiz looks at your photo, searches this machine's documents and past repairs, and checks that every step points to a real page.</p>
      <div class="grid grid-cols-2 lg:grid-cols-4 gap-3 w-full max-w-3xl text-left">
        ${[
          ["camera", "Reads the photo", "Finds the part and any alarm text"],
          ["book-open", "Searches your documents", "Manuals and past fixes for this machine"],
          ["list-checks", "Explains what to do", "Simple steps, safest first"],
          ["shield-check", "Checks every source", "Steps without a page are flagged"]
        ].map(([icon, title, text]) => `
          <div class="rounded-xl border border-wiz-border bg-wiz-panel/50 p-3">
            <i data-lucide="${icon}" class="h-4 w-4 text-wiz-primary mb-2"></i>
            <div class="text-sm font-medium">${title}</div>
            <div class="text-xs text-wiz-muted">${text}</div>
          </div>`).join("")}
      </div>
    </div>`;
  icons();
}

function renderLoading(hasPhoto: boolean) {
  if (!diagnosisPanel) return;
  const stages = [
    ...(hasPhoto ? ["Looking at your photo"] : []),
    "Searching this machine's documents",
    "Working out the most likely cause",
    "Checking every step has a source"
  ];
  diagnosisPanel.innerHTML = `
    <div class="glass-panel rounded-2xl p-10 min-h-[420px] flex flex-col items-center justify-center text-center">
      <i data-lucide="loader-2" class="h-10 w-10 text-wiz-primary animate-spin mb-5"></i>
      <h3 class="text-lg font-bold mb-4">Finding the cause…</h3>
      <ul class="text-sm text-wiz-muted space-y-2 text-left">
        ${stages.map((s) => `<li class="flex items-center gap-2"><i data-lucide="circle-dot" class="h-3.5 w-3.5 text-wiz-primary"></i>${s}</li>`).join("")}
      </ul>
      <p class="text-xs text-wiz-muted mt-6">This usually takes 15–40 seconds.</p>
    </div>`;
  icons();
}

function renderResult(result: DiagnosisResult, photoUrl: string | null, description: string, status = "open", fixNote = "") {
  if (!diagnosisPanel) return;
  const sources = result.sources || [];
  const reading = result.photo_reading;
  const machineNotes = result.machine?.notes;

  const safety = `
    <div class="rounded-2xl border border-red-500/40 bg-red-500/10 p-4 text-sm">
      <div class="flex items-center gap-2 font-semibold text-red-300 mb-2"><i data-lucide="octagon-alert" class="h-4 w-4"></i>Safety first</div>
      <ul class="space-y-1.5 text-red-100/90">
        ${result.safety_warnings.map((w) => `<li>• ${escapeHtml(w.instruction)} ${sourceChips(w.source_ids, sources)}</li>`).join("")}
        <li class="text-red-200/70">• If anything is smoking, sparking, leaking or moving unexpectedly, press <b>EMERGENCY STOP</b> and tell your supervisor${machineNotes ? ` (${escapeHtml(machineNotes)})` : ""}. <span class="text-[11px]">(standard shop rule)</span></li>
      </ul>
    </div>`;

  const photoCard = reading ? card("What we see in your photo", "eye", `
    <div class="flex gap-4">
      ${photoUrl ? `<img src="${photoUrl}" alt="Reported problem" class="h-28 w-28 rounded-lg object-cover border border-wiz-border flex-shrink-0" />` : ""}
      <div class="text-sm space-y-1.5 min-w-0">
        <p><span class="text-wiz-muted">Part:</span> ${escapeHtml(reading.part_shown)}</p>
        <p><span class="text-wiz-muted">Condition:</span> ${escapeHtml(reading.condition)}</p>
        ${reading.visible_text.length ? `<p class="flex flex-wrap gap-1.5 items-center"><span class="text-wiz-muted">Text on the machine:</span> ${reading.visible_text.map((t) => `<code class="rounded bg-wiz-panel px-1.5 py-0.5 text-xs">${escapeHtml(t)}</code>`).join("")}</p>` : ""}
        ${!reading.is_machine_photo ? `<p class="text-yellow-400 text-xs">This does not look like part of a CNC machine. Try another photo for a better answer.</p>` : ""}
        ${reading.photo_quality_note ? `<p class="text-yellow-400 text-xs">Photo tip: ${escapeHtml(reading.photo_quality_note)}</p>` : ""}
      </div>
    </div>`) : "";

  const guided = guidedStepsOf(result);
  const faults = [result.likely_cause, ...result.other_causes];
  const stepsFor = (rank: number) =>
    guided.map((s, i) => (s.checks_cause === rank ? i + 1 : 0)).filter(Boolean);
  const [top, ...rest] = faults;
  const topSteps = stepsFor(0);
  const causeCard = `
    <div class="rounded-2xl border border-wiz-primary/40 bg-wiz-primary/10 p-5">
      <div class="flex items-center justify-between gap-3 mb-3">
        <p class="text-xs font-semibold tracking-wider text-blue-300">POSSIBLE FAULTS, MOST LIKELY FIRST</p>
        <span class="text-xs text-wiz-muted">${faults.length} found</span>
      </div>
      <div class="flex gap-4">
        <span class="flex h-10 w-10 items-center justify-center rounded-xl bg-wiz-primary text-lg font-bold text-white flex-shrink-0">1</span>
        <div class="min-w-0 flex-1">
          <div class="flex flex-wrap items-center gap-2 mb-1"><h3 class="text-xl font-bold">${escapeHtml(top.title)}</h3>${confidencePill(top)}</div>
          <p class="text-sm leading-relaxed text-wiz-text/90">${escapeHtml(top.explanation)}</p>
          <div class="mt-2 flex flex-wrap items-center gap-1.5">
            ${sourceChips(top.source_ids, sources) || `<span class="text-xs text-wiz-muted">No page in your documents supports this directly.</span>`}
            ${topSteps.length ? `<span class="text-[11px] text-wiz-muted">· checked in step ${topSteps.join(", ")}</span>` : ""}
          </div>
        </div>
      </div>
      ${rest.length ? `<ol class="mt-4 space-y-3 border-t border-wiz-primary/20 pt-4">
        ${rest.map((c, i) => {
          const checked = stepsFor(i + 1);
          return `
          <li class="flex gap-4">
            <span class="flex h-7 w-7 items-center justify-center rounded-lg border border-wiz-border bg-wiz-panel text-sm font-semibold flex-shrink-0 ml-1.5">${i + 2}</span>
            <div class="min-w-0 flex-1 text-sm">
              <div class="flex flex-wrap items-center gap-2"><span class="font-semibold">${escapeHtml(c.title)}</span>${confidencePill(c)}</div>
              <p class="text-wiz-muted mt-0.5">${escapeHtml(c.explanation)}</p>
              <div class="mt-1 flex flex-wrap items-center gap-1.5">${sourceChips(c.source_ids, sources)}
                ${checked.length ? `<span class="text-[11px] text-wiz-muted">· checked in step ${checked.join(", ")}</span>` : ""}</div>
            </div>
          </li>`;
        }).join("")}
      </ol>` : ""}
    </div>`;

  const needsDetail = result.needs_more_detail ? `
    <div class="rounded-2xl border border-yellow-500/40 bg-yellow-500/10 p-4 text-sm text-yellow-100 flex gap-2">
      <i data-lucide="scan-eye" class="h-4 w-4 mt-0.5 flex-shrink-0 text-yellow-400"></i>
      <span><b>We could not see a problem in this photo.</b> The causes below are only guesses. Describe what the machine is doing wrong, or photograph the alarm on the screen, and try again.</span>
    </div>` : "";

  const notCovered = !result.manual_covers_this ? `
    <div class="rounded-2xl border border-yellow-500/40 bg-yellow-500/10 p-4 text-sm text-yellow-100 flex gap-2">
      <i data-lucide="file-question" class="h-4 w-4 mt-0.5 flex-shrink-0 text-yellow-400"></i>
      <span>Your uploaded documents do not clearly cover this problem. Treat the answer as a starting point, and ask the owner to upload the machine's alarm list or service manual.</span>
    </div>` : "";

  const guideCard = guided.length ? `<div id="guided-steps"></div>` : "";

  const allStepsCard = guided.length ? `
    <details class="source-dropdown glass-panel rounded-2xl p-5">
      <summary class="!mt-0">See all ${guided.length} steps at once</summary>
      <ol class="mt-4 space-y-3 text-sm">${stepList(guided, sources)}</ol>
      ${result.general_advice.length ? `<p class="mt-3 text-xs text-wiz-muted">Steps marked “Not in your documents” are common practice, but no page in your documents backs them up. Check with your supervisor first.</p>` : ""}
    </details>` : "";

  const technicianCard = result.call_technician_if.length ? card("Stop and call a technician if", "phone-call", `
    <ul class="space-y-1.5 text-sm">${result.call_technician_if.map((t) => `<li>• ${escapeHtml(t)}</li>`).join("")}</ul>`) : "";

  const question = result.question_for_worker ? `
    <div class="rounded-2xl border border-wiz-border bg-wiz-panel/60 p-4 text-sm flex gap-2">
      <i data-lucide="message-circle-question" class="h-4 w-4 mt-0.5 text-wiz-primary flex-shrink-0"></i>
      <span><b>To narrow it down:</b> ${escapeHtml(result.question_for_worker)} Add the answer to your description and run it again.</span>
    </div>` : "";

  const sourcesCard = sources.length ? `
    <details class="source-dropdown glass-panel rounded-2xl p-5">
      <summary class="!mt-0">Where this answer comes from (${sources.filter((s) => s.cited).length} of ${sources.length} excerpts used)</summary>
      <div class="mt-3 space-y-3">
        ${sources.map((s) => `
          <div id="source-${s.id}" class="rounded-lg border ${s.cited ? "border-wiz-primary/40" : "border-wiz-border/50 opacity-70"} p-3">
            <div class="flex items-center justify-between gap-2 text-xs mb-1.5">
              <span class="font-semibold">${s.id} · ${escapeHtml(s.label)}${s.section ? ` — ${escapeHtml(s.section)}` : ""}</span>
              ${s.kind === "document" && s.document_id ? `<a href="${documentPageUrl(s.document_id, s.page)}" target="_blank" rel="noopener" class="text-blue-300 hover:underline flex-shrink-0">Open page</a>` : ""}
            </div>
            <pre class="whitespace-pre-wrap text-[11px] text-wiz-muted max-h-40 overflow-y-auto scrollbar font-mono">${escapeHtml(s.text.slice(0, 1500))}</pre>
          </div>`).join("")}
      </div>
    </details>` : "";

  const fixCard = result.case_id ? `
    <div class="glass-panel rounded-2xl p-5">
      <h3 class="text-sm font-semibold mb-1 flex items-center gap-2"><i data-lucide="badge-check" class="h-4 w-4 text-wiz-success"></i>After the repair</h3>
      <p class="text-xs text-wiz-muted mb-3">Write down what actually fixed it. Greywiz will use it the next time someone reports a similar problem.</p>
      <textarea id="fix-note" rows="2" class="w-full rounded-lg border border-wiz-border bg-wiz-panel px-3 py-2 text-sm outline-none focus:border-wiz-primary resize-none" placeholder="e.g. Door switch was loose. Tightened the bracket and it works.">${escapeHtml(fixNote)}</textarea>
      <div class="flex items-center justify-between mt-2">
        <span id="fix-status" class="text-xs ${status === "fixed" ? "text-wiz-success" : "text-wiz-muted"}">${status === "fixed" ? "Marked as fixed" : "Still open"}</span>
        <button id="mark-fixed" class="rounded-lg bg-wiz-success/90 px-3 py-1.5 text-xs font-semibold text-white hover:opacity-90">Mark as fixed</button>
      </div>
    </div>` : "";

  const footer = `<p class="text-[11px] text-wiz-muted text-center">
    ${description ? `Reported: “${escapeHtml(description)}” · ` : ""}Greywiz assists; it does not replace the machine's manual or a qualified technician.
    ${result.timings?.total ? ` · Answered in ${result.timings.total.toFixed(1)} s` : ""}
  </p>
  ${result.warnings?.length ? `<p class="text-[11px] text-yellow-400 text-center">${result.warnings.map(escapeHtml).join("<br>")}</p>` : ""}`;

  diagnosisPanel.innerHTML = `
    <div class="flex flex-col gap-4 max-w-4xl">
      <div>
        <p class="text-xs font-semibold tracking-wider text-wiz-muted mb-1">Diagnosis</p>
        <h2 class="text-2xl font-bold leading-snug">${escapeHtml(result.summary)}</h2>
      </div>
      ${safety}
      ${photoCard}
      ${needsDetail}
      ${causeCard}
      ${notCovered}
      ${question}
      ${guideCard}
      ${allStepsCard}
      ${technicianCard}
      ${sourcesCard}
      ${fixCard}
      ${footer}
    </div>`;
  icons();
  if (guided.length) startGuide(result, guided, sources, status);

  const markFixed = $("#mark-fixed");
  markFixed?.addEventListener("click", async () => {
    const note = ($("#fix-note") as HTMLTextAreaElement | null)?.value.trim() ?? "";
    const statusEl = $("#fix-status");
    if (!note) {
      if (statusEl) { statusEl.textContent = "Write what fixed it first."; statusEl.className = "text-xs text-yellow-400"; }
      return;
    }
    try {
      await updateCase(result.case_id!, "fixed", note);
      if (statusEl) { statusEl.textContent = "Marked as fixed. Saved to this machine's history."; statusEl.className = "text-xs text-wiz-success"; }
      await refreshCases();
    } catch (err) {
      if (statusEl) { statusEl.textContent = errorMessage(err, "Could not save."); statusEl.className = "text-xs text-wiz-danger"; }
    }
  });
}

function renderProfileCard(profile: WorkerProfile | null) {
  const host = $("#sidebar-profile");
  if (!host) return;
  host.innerHTML = profile
    ? `<div class="flex items-center justify-between mb-1">
         <span class="text-[10px] tracking-wider text-wiz-muted">YOU</span>
         <button id="change-profile" class="text-[11px] text-blue-300 hover:underline">Change</button>
       </div>
       <div class="font-semibold text-sm text-wiz-text truncate">${escapeHtml(profile.name || profile.role)}</div>
       <div class="text-wiz-muted truncate">${escapeHtml(profile.role)}</div>
       <div class="mt-2 inline-flex rounded-full border border-wiz-primary/30 bg-wiz-primary/10 px-2 py-0.5 text-[11px] text-blue-300" title="${escapeHtml(levelExplanation(profile.level))}">${escapeHtml(profile.level_label)}</div>`
    : `<div class="text-wiz-muted">We don't know who you are yet.</div>
       <button id="change-profile" class="mt-1 text-[11px] text-blue-300 hover:underline">Answer 5 questions</button>`;
  host.querySelector("#change-profile")?.addEventListener("click", () => void askWhoYouAre(true));
}

/** Steps in the order to try them; older saved reports have no guided_steps. */
function guidedStepsOf(result: DiagnosisResult): DiagnosisStep[] {
  if (result.guided_steps?.length) return result.guided_steps;
  return [
    ...result.steps.map((s) => ({ ...s, checks_cause: s.checks_cause ?? 0, from_documents: true })),
    ...result.general_advice.map((s) => ({ ...s, checks_cause: s.checks_cause ?? 0, from_documents: false }))
  ];
}

type Outcome = "fixed" | "not_fixed" | "cannot" | "skipped_technician";
const OUTCOME_LABEL: Record<Outcome, string> = {
  fixed: "Fixed it",
  not_fixed: "Done, still not working",
  cannot: "Could not do it",
  skipped_technician: "Needs a technician"
};

/**
 * Walks the worker through the steps one at a time. Each answer is recorded;
 * "That fixed it" marks the report fixed with the step that worked, and running
 * out of steps produces a hand-over note for the technician.
 */
function startGuide(result: DiagnosisResult, steps: DiagnosisStep[], sources: DiagnosisSource[], status: string) {
  const host = $("#guided-steps");
  if (!host) return;
  const faults = [result.likely_cause, ...result.other_causes];
  const worker = getProfile();
  const mayDoTechnicianWork = worker?.can_do_technician_work ?? false;
  const log: Array<{ step: number; outcome: Outcome }> = [];
  let index = 0;
  let started = false;

  const summaryLines = () => log.map(({ step, outcome }) =>
    `Step ${step + 1} (${OUTCOME_LABEL[outcome]}): ${steps[step].instruction}`);

  const save = async (state: "open" | "fixed", note: string, statusEl: HTMLElement | null) => {
    if (!result.case_id) return;
    try {
      await updateCase(result.case_id, state, note);
      if (statusEl) statusEl.textContent = state === "fixed"
        ? "Saved to this machine's history. Greywiz will use it next time."
        : "Saved to the report so the technician can see what was tried.";
      await refreshCases();
    } catch (err) {
      if (statusEl) statusEl.textContent = errorMessage(err, "Could not save.");
    }
  };

  const shell = (inner: string) => `
    <div class="rounded-2xl border-2 border-wiz-primary/50 bg-wiz-panel/80 p-6">
      <div class="flex items-center gap-2 mb-4">
        <i data-lucide="footprints" class="h-4 w-4 text-wiz-primary"></i>
        <h3 class="text-sm font-semibold">Let's fix it together, one step at a time</h3>
      </div>
      ${inner}
    </div>`;

  const render = () => {
    if (!started) {
      host.innerHTML = shell(`
        <p class="text-sm text-wiz-muted mb-4">${steps.length} steps, starting with fault #1. After each one, tell Greywiz what happened and it will give you the next step.${status === "fixed" ? " This report is already marked fixed." : ""}</p>
        <button data-guide-start class="w-full rounded-xl bg-wiz-primary px-5 py-3 text-sm font-semibold text-white hover:opacity-90 flex items-center justify-center gap-2">
          <i data-lucide="play" class="h-4 w-4"></i> Guide me step by step
        </button>`);
    } else if (index >= steps.length) {
      const fixedEntry = log.find((l) => l.outcome === "fixed");
      if (fixedEntry) {
        host.innerHTML = shell(`
          <div class="flex items-start gap-3 mb-3">
            <i data-lucide="party-popper" class="h-6 w-6 text-wiz-success flex-shrink-0"></i>
            <div><p class="text-lg font-bold">Fixed at step ${fixedEntry.step + 1}.</p>
            <p class="text-sm text-wiz-muted">${escapeHtml(steps[fixedEntry.step].instruction)}</p></div>
          </div>
          <p id="guide-save" class="text-xs text-wiz-success">Saving…</p>`);
        icons();
        const note = `Fixed by step ${fixedEntry.step + 1}: ${steps[fixedEntry.step].instruction}` +
          (log.length > 1 ? `\nTried before: ${summaryLines().slice(0, -1).join(" | ")}` : "");
        const fixNote = $("#fix-note") as HTMLTextAreaElement | null;
        if (fixNote) fixNote.value = note;
        void save("fixed", note, $("#guide-save"));
        return;
      }
      const handover = [
        `Problem: ${result.summary}`,
        `Reported by: ${worker?.name || "worker"} (${worker?.level_label || "unknown level"})`,
        ...summaryLines()
      ].join("\n");
      host.innerHTML = shell(`
        <div class="flex items-start gap-3 mb-3">
          <i data-lucide="phone-call" class="h-6 w-6 text-orange-400 flex-shrink-0"></i>
          <div><p class="text-lg font-bold">Stop here and call a technician.</p>
          <p class="text-sm text-wiz-muted">You have tried every step that is safe for you. Show the technician this list so they do not repeat it.</p></div>
        </div>
        <pre class="whitespace-pre-wrap rounded-lg border border-wiz-border bg-wiz-bg/60 p-3 text-xs text-wiz-text/90 mb-3">${escapeHtml(handover)}</pre>
        <div class="flex items-center justify-between gap-2">
          <p id="guide-save" class="text-xs text-wiz-muted"></p>
          <button data-guide-restart class="text-xs text-wiz-muted hover:text-wiz-text">Start the steps again</button>
        </div>`);
      void save("open", handover, $("#guide-save"));
    } else {
      const step = steps[index];
      const fault = faults[step.checks_cause] ?? faults[0];
      const locked = step.needs_technician && !mayDoTechnicianWork;
      host.innerHTML = shell(`
        <div class="flex items-center justify-between text-xs text-wiz-muted mb-2">
          <span>Step ${index + 1} of ${steps.length}</span>
          <span>Checking fault #${step.checks_cause + 1}: ${escapeHtml(fault.title)}</span>
        </div>
        <div class="h-1.5 w-full rounded-full bg-wiz-border mb-5"><div class="h-1.5 rounded-full bg-wiz-primary transition-all" style="width:${(index / steps.length) * 100}%"></div></div>
        ${locked ? `
          <div class="rounded-xl border border-orange-500/40 bg-orange-500/10 p-4 mb-4">
            <p class="flex items-center gap-2 font-semibold text-orange-200 mb-1"><i data-lucide="hard-hat" class="h-4 w-4"></i>This step needs a trained technician</p>
            <p class="text-sm text-orange-100/80">${escapeHtml(step.instruction)}</p>
            <p class="text-xs text-orange-200/70 mt-2">Do not do this yourself. Call a technician, or skip it and continue with the next safe step.</p>
          </div>
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
            <button data-outcome="skipped_technician" class="rounded-xl border border-wiz-border px-4 py-3 text-sm hover:bg-wiz-panel_hover">Skip, show the next step</button>
            <button data-call-tech class="rounded-xl bg-orange-500/90 px-4 py-3 text-sm font-semibold text-white hover:opacity-90">Stop and call a technician</button>
          </div>` : `
          <p class="text-lg font-semibold leading-relaxed mb-2">${escapeHtml(step.instruction)}</p>
          <div class="flex flex-wrap items-center gap-1.5 mb-5">
            ${step.needs_technician ? `<span class="inline-flex items-center gap-1 rounded-md border border-orange-500/40 bg-orange-500/10 px-1.5 py-0.5 text-[11px] text-orange-300"><i data-lucide="hard-hat" class="h-3 w-3"></i>Technician step: lock out first</span>` : ""}
            ${step.from_documents === false ? `<span class="inline-flex items-center gap-1 rounded-md border border-yellow-500/40 bg-yellow-500/10 px-1.5 py-0.5 text-[11px] text-yellow-300"><i data-lucide="info" class="h-3 w-3"></i>Not in your documents: check with your supervisor</span>` : ""}
            ${sourceChips(step.source_ids, sources)}
          </div>
          <p class="text-xs text-wiz-muted mb-2">Did you do it? What happened?</p>
          <div class="grid grid-cols-1 sm:grid-cols-3 gap-2">
            <button data-outcome="fixed" class="rounded-xl bg-wiz-success/90 px-4 py-3 text-sm font-semibold text-white hover:opacity-90">✓ That fixed it</button>
            <button data-outcome="not_fixed" class="rounded-xl bg-wiz-primary px-4 py-3 text-sm font-semibold text-white hover:opacity-90">Done, still not working</button>
            <button data-outcome="cannot" class="rounded-xl border border-wiz-border px-4 py-3 text-sm text-wiz-muted hover:text-wiz-text hover:bg-wiz-panel_hover">I can't do this step</button>
          </div>`}
        ${index > 0 ? `<button data-guide-back class="mt-3 text-xs text-wiz-muted hover:text-wiz-text">← Previous step</button>` : ""}`);
    }
    icons();

    host.querySelector("[data-guide-start]")?.addEventListener("click", () => { started = true; render(); });
    host.querySelector("[data-guide-restart]")?.addEventListener("click", () => { index = 0; log.length = 0; render(); });
    host.querySelector("[data-guide-back]")?.addEventListener("click", () => { log.pop(); index -= 1; render(); });
    host.querySelector("[data-call-tech]")?.addEventListener("click", () => {
      log.push({ step: index, outcome: "skipped_technician" });
      index = steps.length;
      render();
    });
    host.querySelectorAll<HTMLElement>("[data-outcome]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const outcome = btn.dataset.outcome as Outcome;
        log.push({ step: index, outcome });
        index = outcome === "fixed" ? steps.length : index + 1;
        render();
        host.scrollIntoView({ behavior: "smooth", block: "nearest" });
      });
    });
  };

  render();
}

function timeAgo(iso: string) {
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  return new Date(iso).toLocaleDateString();
}

function renderCases() {
  if (!caseList) return;
  if (!state.cases.length) {
    caseList.innerHTML = `<p class="text-xs text-wiz-muted">No problems reported yet.</p>`;
    return;
  }
  caseList.innerHTML = state.cases.slice(0, 8).map((c) => `
    <button data-case="${c.id}" class="w-full text-left rounded-lg border ${c.id === state.activeCaseId ? "border-wiz-primary/50 bg-wiz-primary/10" : "border-wiz-border hover:bg-wiz-panel_hover"} p-2.5 transition">
      <div class="flex items-center justify-between gap-2 text-xs">
        <span class="flex items-center gap-1.5 text-wiz-muted">${c.has_photo ? `<i data-lucide="image" class="h-3 w-3"></i>` : ""}${timeAgo(c.created_at)}</span>
        <span class="rounded-full px-2 py-0.5 text-[10px] ${c.status === "fixed" ? "bg-wiz-success/15 text-wiz-success" : "bg-yellow-500/15 text-yellow-400"}">${c.status === "fixed" ? "Fixed" : "Open"}</span>
      </div>
      <div class="mt-1 text-sm line-clamp-2">${escapeHtml(c.summary || c.description || "Photo report")}</div>
    </button>`).join("");
  caseList.querySelectorAll<HTMLElement>("[data-case]").forEach((btn) => {
    btn.addEventListener("click", () => void openCase(btn.dataset.case!));
  });
  icons();
}

async function refreshCases() {
  try {
    state.cases = await getCases();
    renderCases();
  } catch (e) {
    console.error("Could not load past problems", e);
  }
}

async function openCase(caseId: string) {
  try {
    const detail = await getCase(caseId);
    state.activeCaseId = caseId;
    renderCases();
    renderResult(
      { ...detail.result, case_id: detail.id },
      detail.photo ? casePhotoUrl(detail.id) : null,
      detail.description,
      detail.status,
      detail.fix_note
    );
  } catch (err) {
    showError(errorMessage(err, "Could not open that report."));
  }
}

async function runDiagnosis() {
  if (state.busy) return;
  const description = problemText?.value.trim() ?? "";
  if (!description && !state.photo) {
    showError("Add a photo of the problem or describe it in words.");
    return;
  }
  showError();
  state.busy = true;
  if (diagnoseButton) diagnoseButton.disabled = true;
  renderLoading(!!state.photo);
  const photoUrl = state.photoUrl;
  try {
    const profile = getProfile() ?? await askWhoYouAre(false);
    const result = await diagnoseProblem(description, state.photo, getProvider(), profile);
    state.activeCaseId = result.case_id ?? null;
    renderResult(result, result.case_id && state.photo ? casePhotoUrl(result.case_id) : photoUrl, description);
    await refreshCases();
  } catch (err) {
    renderEmpty();
    showError(errorMessage(err, "Something went wrong. Check that the backend is running."));
  } finally {
    state.busy = false;
    if (diagnoseButton) diagnoseButton.disabled = false;
  }
}

export function initDiagnose(providerGetter: () => string | undefined) {
  getProvider = providerGetter;
  photoZone?.addEventListener("click", () => photoInput?.click());
  photoZone?.addEventListener("dragover", (e) => { e.preventDefault(); photoZone.classList.add("border-wiz-primary"); });
  photoZone?.addEventListener("dragleave", () => photoZone.classList.remove("border-wiz-primary"));
  photoZone?.addEventListener("drop", (e) => {
    e.preventDefault();
    photoZone.classList.remove("border-wiz-primary");
    const file = e.dataTransfer?.files[0];
    if (file) stagePhoto(file);
  });
  photoInput?.addEventListener("change", () => {
    const file = photoInput.files?.[0];
    if (file) stagePhoto(file);
  });
  photoRemove?.addEventListener("click", () => setPhoto(null));
  document.querySelectorAll<HTMLElement>(".problem-chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      if (!problemText) return;
      const text = chip.textContent?.trim() ?? "";
      problemText.value = problemText.value.trim() ? `${problemText.value.trim()} ${text}.` : `${text}.`;
      problemText.focus();
    });
  });
  diagnoseButton?.addEventListener("click", () => void runDiagnosis());
  onProfileChange(renderProfileCard);
  renderProfileCard(getProfile());
  if (!getProfile()) void askWhoYouAre(false);
  renderEmpty();
  void refreshCases();
}
