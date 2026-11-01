# Greywiz demo script — one CNC machine, one fault

**Story:** a company has one Haas VF-2 CNC mill ("VMC 1"). The owner loaded the
documents they have. The machine stops with **Alarm 120 – Low Air Pressure**.
Anyone on the floor reports it with a photo and/or one sentence, and Greywiz
finds the cause in *that machine's own documents* and guides them step by
step — in simple words for a trainee, in technical terms for a technician.

About 10 minutes.

---

## What is loaded

| | |
|---|---|
| Machine | VMC 1 · Haas VF-2 · Haas Next Generation Control (NGC) · Peenya, Bengaluru |
| Document 1 | Haas VF Mill Manual – Safety, Pendant, Operation (51 pages of the official Haas NGC operator's manual) |
| Document 2 | Haas VF Series Service Manual – Troubleshooting, Alarms & Maintenance (official Haas archive, pages 2–41 and 200–203), added through "Is anything missing?" with the owner's consent |
| Demo photo | `demo/glitch-alarm-120-low-air-pressure-SIMULATED.jpg` — a real Haas control panel photo with a simulated alarm on the screen |

## The one sentence to type (same for every person)

> Machine stopped and the screen shows alarm 120 low air pressure. What should I do?

Type it exactly. Greywiz has a saved, checked answer for this sentence with
and without the photo, for all three kinds of person, so the demo answers
instantly and the same way every time (the screen says "showing the saved
answer"). Any other wording is answered live by the AI.

---

## Before you present

1. Start: `npm run start:win` in the project folder → open http://127.0.0.1:8000
2. Open it in a **fresh browser tab** so it starts with "Who are you?".
3. Search runs on the laptop (no internet needed for it). Live answers and the
   3D model need internet and Gemini quota; the saved demo answers do not.

## The script

### 1. The owner's side (2 min) — Machine & documents
- Show the machine card and the two documents. Point at *"From Haas Automation
  (official), added with Kiran (owner)'s consent"* on the service manual.
- **Is anything missing?** — all five document types ticked. Click **Add…** on
  the optional Haas maintenance manual to show the consent card, then **Not now**:
  *"Nothing is downloaded without consent, and only from the maker's official site."*

### 2. A trainee (4 min)
- **Who are you?** → *Helper or trainee · Less than 6 months · No* → "New to CNC".
- **Report a problem** → add the photo → type the sentence → **Find the cause**.
- Show: *What we see in your photo* (reads "120 LOW AIR PRESSURE") → ranked faults
  (1 low incoming air pressure, 2 low lubrication oil, 3 full oil drain bucket) →
  **Where we looked** → **Guide me step by step**:
  1. Check the air gauge at the back reads 85 psi
  2. Check the clear oil tank level
  3. Empty the old-oil bucket if full
  4. Press the orange [RESET] button
  → *"Stop here and call a technician"* with a hand-over list if nothing worked.

### 3. A maintenance technician (3 min)
- Click **Change** under "You" → *Maintenance technician · More than 5 years · Yes*
  → "Maintenance professional".
- Same photo + same sentence → **Find the cause**.
- Show the difference: technical steps (regulator at 85 psi, water trap, way lube
  pump, pressure switch), lockout steps unlocked, page references to the alarm
  table (service manual p. 25) and maintenance schedule (p. 42).
- Optional: **Make a 3D model** of the photo (~1 min, needs internet).

### 4. Close (1 min)
- In the guide click **That fixed it** — the fix is saved to the machine's history
  and used the next time someone reports the same problem.
- Optional: **Machine health** → Forecast (needs Gemini quota).

---

## Lines for the questions

- **"Is this your own AI model?"** No. We use hosted models through APIs (Google
  Gemini for reading photos and writing answers) and open models from the
  Hugging Face hub (BGE for searching the manuals on this laptop, Hunyuan3D-2 for
  3D). We don't train an LLM.
- **"Why not ChatGPT?"** It answers only from this machine's own documents, cites
  the page for every step, adapts to who is asking, and locks technician work for
  trainees.
- **"Is the alarm photo real?"** The panel photo is real (Wikimedia Commons,
  CC BY-SA); the alarm on the screen is simulated. Alarm 120 and its causes come
  from the real Haas service manual.

## If something goes wrong
- Type the sentence exactly; a different sentence needs a live AI call.
- *"The Google AI key has used up its free limit for today"* → only live answers
  are affected; the saved demo answers still work. Enable billing for live use.
- 3D model fails → it depends on a free public service; skip it.
