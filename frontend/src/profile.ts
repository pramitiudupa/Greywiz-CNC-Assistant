// "Who are you?" — a short set of questions that decides how Greywiz talks to
// the person in front of the machine: a new helper gets simple words and is
// stopped before technician-only steps; a maintenance professional gets
// technical detail. Kept per device in localStorage (each worker's phone).

export type Level = "beginner" | "operator" | "professional";

export interface WorkerProfile {
  name: string;
  role: string;
  experience: string;
  training: string;
  alarms: string;
  electrical: string;
  level: Level;
  level_label: string;
  can_do_technician_work: boolean;
}

interface Option { label: string; points: number; key?: string }
interface Question { id: keyof WorkerProfile; title: string; hint?: string; options: Option[] }

const QUESTIONS: Question[] = [
  {
    id: "role",
    title: "What is your job at the workshop?",
    options: [
      { label: "Helper or trainee", points: 0, key: "helper" },
      { label: "Machine operator", points: 1, key: "operator" },
      { label: "Maintenance technician", points: 3, key: "technician" },
      { label: "Engineer or supervisor", points: 3, key: "engineer" },
      { label: "Owner", points: 1, key: "owner" }
    ]
  },
  {
    id: "experience",
    title: "How long have you worked with CNC machines?",
    options: [
      { label: "Less than 6 months", points: 0 },
      { label: "6 months to 2 years", points: 1 },
      { label: "2 to 5 years", points: 2 },
      { label: "More than 5 years", points: 3 }
    ]
  },
  {
    id: "training",
    title: "What training have you had?",
    options: [
      { label: "None yet", points: 0 },
      { label: "Learned on the job", points: 1 },
      { label: "ITI or diploma", points: 2, key: "formal" },
      { label: "Engineering degree", points: 2, key: "formal" },
      { label: "Machine maker's (OEM) service course", points: 3, key: "formal" }
    ]
  },
  {
    id: "alarms",
    title: "Have you cleared an alarm on a CNC control yourself?",
    hint: "For example pressing RESET after reading the alarm message.",
    options: [
      { label: "Never", points: 0 },
      { label: "A few times", points: 1 },
      { label: "Often", points: 2 }
    ]
  },
  {
    id: "electrical",
    title: "Are you trained and allowed to open electrical cabinets or covers?",
    hint: "This means you have done lockout/tagout training and your supervisor allows it.",
    options: [
      { label: "No", points: 0, key: "no" },
      { label: "Yes", points: 2, key: "yes" }
    ]
  }
];

const LEVELS: Record<Level, { label: string; explain: string }> = {
  beginner: {
    label: "New to CNC",
    explain: "Greywiz will use simple words, show you where each button is, and stop you before any step that needs a technician."
  },
  operator: {
    label: "Skilled operator",
    explain: "Greywiz will use control panel terms and plain steps, and stop you before anything that needs tools or electrical work."
  },
  professional: {
    label: "Maintenance professional",
    explain: "Greywiz will be brief and technical, with alarm numbers, diagnostic screens and deeper checks."
  }
};

const STORAGE_KEY = "greywiz.profile.v1";

function escapeHtml(value: string) {
  return value.replace(/[&<>"']/g, (char) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" } as Record<string, string>
  )[char]);
}

export function loadProfile(): WorkerProfile | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as WorkerProfile) : null;
  } catch {
    return null;
  }
}

function saveProfile(profile: WorkerProfile) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(profile));
  } catch {
    // Private windows can block storage; the profile still applies this session.
  }
}

function buildProfile(name: string, picks: Record<string, Option>): WorkerProfile {
  const score = Object.values(picks).reduce((sum, o) => sum + o.points, 0);
  const level: Level = score >= 8 ? "professional" : score >= 4 ? "operator" : "beginner";
  const technicalRole = ["technician", "engineer"].includes(picks.role.key ?? "");
  return {
    name: name.trim(),
    role: picks.role.label,
    experience: picks.experience.label,
    training: picks.training.label,
    alarms: picks.alarms.label,
    electrical: picks.electrical.label,
    level,
    level_label: LEVELS[level].label,
    can_do_technician_work: picks.electrical.key === "yes" && (technicalRole || picks.training.key === "formal")
  };
}

let current: WorkerProfile | null = loadProfile();
const listeners: Array<(p: WorkerProfile) => void> = [];

export function getProfile() {
  return current;
}

export function onProfileChange(listener: (p: WorkerProfile) => void) {
  listeners.push(listener);
}

export function levelExplanation(level: Level) {
  return LEVELS[level].explain;
}

/** Opens the questions. Resolves when the person finishes (it cannot be skipped on first use). */
export function askWhoYouAre(allowClose = current !== null): Promise<WorkerProfile> {
  const root = document.querySelector<HTMLElement>("#profile-modal");
  if (!root) return Promise.reject(new Error("profile modal missing"));

  return new Promise((resolve) => {
    const picks: Record<string, Option> = {};
    let step = -1; // -1 = welcome / name
    let name = current?.name ?? "";

    const close = (profile: WorkerProfile) => {
      root.classList.add("hidden");
      root.innerHTML = "";
      resolve(profile);
    };

    const render = () => {
      const total = QUESTIONS.length;
      let body = "";
      if (step === -1) {
        body = `
          <p class="text-xs font-semibold tracking-wider text-wiz-primary mb-2">BEFORE WE START</p>
          <h2 class="text-2xl font-bold mb-2">Who are you?</h2>
          <p class="text-sm text-wiz-muted mb-6">Five quick questions so Greywiz can talk to you the right way. A new helper and a maintenance engineer need different answers.</p>
          <label class="block text-xs text-wiz-muted mb-1.5" for="profile-name">Your name (optional)</label>
          <input id="profile-name" value="${escapeHtml(name)}" placeholder="e.g. Ravi" class="w-full rounded-lg border border-wiz-border bg-wiz-panel px-3 py-2.5 text-sm outline-none focus:border-wiz-primary mb-6" />
          <button data-next class="w-full rounded-xl bg-wiz-primary px-5 py-3 text-sm font-semibold text-white hover:opacity-90">Start</button>`;
      } else if (step < total) {
        const q = QUESTIONS[step];
        body = `
          <div class="flex items-center justify-between mb-4">
            <p class="text-xs font-semibold tracking-wider text-wiz-muted">QUESTION ${step + 1} OF ${total}</p>
            <button data-back class="text-xs text-wiz-muted hover:text-wiz-text">Back</button>
          </div>
          <div class="h-1 w-full rounded-full bg-wiz-border mb-6"><div class="h-1 rounded-full bg-wiz-primary" style="width:${((step + 1) / total) * 100}%"></div></div>
          <h2 class="text-xl font-bold mb-1">${q.title}</h2>
          ${q.hint ? `<p class="text-sm text-wiz-muted mb-4">${q.hint}</p>` : `<div class="mb-4"></div>`}
          <div class="flex flex-col gap-2">
            ${q.options.map((o, i) => `
              <button data-option="${i}" class="text-left rounded-xl border ${picks[q.id]?.label === o.label ? "border-wiz-primary bg-wiz-primary/15" : "border-wiz-border hover:border-wiz-primary/50 hover:bg-wiz-panel_hover"} px-4 py-3 text-sm transition">${o.label}</button>`).join("")}
          </div>`;
      } else {
        const profile = buildProfile(name, picks);
        body = `
          <p class="text-xs font-semibold tracking-wider text-wiz-primary mb-2">THANKS${profile.name ? `, ${escapeHtml(profile.name.toUpperCase())}` : ""}</p>
          <h2 class="text-2xl font-bold mb-3">We'll talk to you as: ${profile.level_label}</h2>
          <p class="text-sm text-wiz-muted mb-4">${LEVELS[profile.level].explain}</p>
          <div class="rounded-xl border ${profile.can_do_technician_work ? "border-wiz-success/40 bg-wiz-success/10 text-emerald-200" : "border-orange-500/40 bg-orange-500/10 text-orange-200"} p-3 text-sm mb-6">
            ${profile.can_do_technician_work
              ? "You can see technician-only steps (covers, electrics). Always follow lockout/tagout."
              : "Steps that need a technician (opening covers, electrical work) will be shown as “Call a technician”."}
          </div>
          <div class="flex gap-2">
            <button data-back class="flex-1 rounded-xl border border-wiz-border px-4 py-3 text-sm text-wiz-muted hover:text-wiz-text">Change answers</button>
            <button data-finish class="flex-1 rounded-xl bg-wiz-primary px-4 py-3 text-sm font-semibold text-white hover:opacity-90">Continue</button>
          </div>`;
      }
      root.innerHTML = `
        <div class="absolute inset-0 bg-black/70 backdrop-blur-sm"></div>
        <div class="relative w-full max-w-lg glass-panel rounded-2xl p-7 shadow-2xl max-h-[92vh] overflow-y-auto scrollbar">
          ${allowClose ? `<button data-close class="absolute right-4 top-4 text-wiz-muted hover:text-wiz-text text-lg leading-none" aria-label="Close">×</button>` : ""}
          ${body}
        </div>`;

      root.querySelector("[data-next]")?.addEventListener("click", () => {
        name = (root.querySelector<HTMLInputElement>("#profile-name")?.value ?? "").trim();
        step = 0;
        render();
      });
      root.querySelector<HTMLInputElement>("#profile-name")?.addEventListener("keydown", (e) => {
        if (e.key === "Enter") root.querySelector<HTMLButtonElement>("[data-next]")?.click();
      });
      root.querySelectorAll<HTMLElement>("[data-option]").forEach((btn) => {
        btn.addEventListener("click", () => {
          picks[QUESTIONS[step].id] = QUESTIONS[step].options[Number(btn.dataset.option)];
          step += 1;
          render();
        });
      });
      root.querySelector("[data-back]")?.addEventListener("click", () => {
        step = step >= QUESTIONS.length ? QUESTIONS.length - 1 : step - 1;
        render();
      });
      root.querySelector("[data-finish]")?.addEventListener("click", () => {
        const profile = buildProfile(name, picks);
        current = profile;
        saveProfile(profile);
        listeners.forEach((l) => l(profile));
        close(profile);
      });
      root.querySelector("[data-close]")?.addEventListener("click", () => {
        if (current) close(current);
      });
    };

    root.classList.remove("hidden");
    render();
    root.querySelector<HTMLInputElement>("#profile-name")?.focus();
  });
}
