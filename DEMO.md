# Greywiz demo script — one CNC machine at a company

**Story:** a company has one Haas VF-2 CNC mill. The owner loads whatever
documents they have. When the machine stops, anyone on the floor can report it
with a photo and/or a few words, and Greywiz finds the cause in *that machine's
own documents* and guides them step by step. A trainee and a maintenance
technician get different answers to the same fault.

Total time: about 12 minutes.

---

## Before the demo (do this the day before)

1. Start the app: `npm run start:win` in the project folder, then open
   http://127.0.0.1:8000
2. On **Machine & documents**:
   - Machine: *VMC 1 · Haas · VF-2 · Haas Next Generation Control (NGC) · Peenya, Bengaluru*
   - Documents already processed (processing takes 5–20 minutes each on a laptop, so never do it live):
     - **Haas VF Mill Manual – Safety, Pendant, Operation** (51 pages of the official Haas NGC operator's manual)
     - **Haas VF Series Service Manual – Troubleshooting, Alarms & Maintenance** (added through the "Is anything missing?" panel, with consent)
3. Have the demo photo ready: `demo/glitch-alarm-120-low-air-pressure-SIMULATED.jpg`
   (a real Haas control panel photo with a **simulated** alarm drawn on the screen).
4. **Gemini quota:** a free-tier key allows about 20 requests per model per day,
   and each report uses 2. Greywiz switches between 5 Gemini models
   automatically, but for demo day **enable billing on the key** (cost is a few
   rupees) or use a fresh key.
5. Open the app once in a fresh browser tab right before you present, so it
   starts with the "Who are you?" questions.

---

## The script

### 1. The owner's side — "the company puts in whatever it has" (2 min)

Open **Machine & documents**.

- Show the machine card and the two documents. Point at the service manual's
  line: *"From Haas Automation (official), added with Kiran (owner)'s consent."*
- Show **Is anything missing?** Before the service manual was added, it said
  *Missing: Alarm list, Troubleshooting guide, Maintenance schedule, Electrical
  diagrams* and offered official Haas documents for them. Now everything is ticked.
- Click **Add…** on *Haas Mill Maintenance Manual* to show the consent card
  ("Greywiz will download … from haascnc.com, the machine maker's official
  site …"), then click **Not now**. Say: *"Nothing is downloaded without
  consent, and only from validated official sources."*
- Mention the upload box accepts **photos of paper manual pages** too.

### 2. A trainee reports the fault (4 min)

Open a fresh tab → **Who are you?** → answer:
*Helper or trainee · Less than 6 months · No* → "New to CNC".

**Report a problem:**
- Photo: `glitch-alarm-120-low-air-pressure-SIMULATED.jpg`
- Words (type exactly, like a worker would):

  > machine stopped in the middle of the job and the screen is showing red alarm. what do i do

Click **Find the cause** (≈40 s). Then show:
- **What we see in your photo:** it reads *"120 LOW AIR PRESSURE"* off the screen.
- **Possible faults, most likely first:** low shop air supply / closed valve, then an air leak.
- **Where we looked:** both manuals searched; *"120"* found on the service manual's alarm page.
- **Guide me step by step:** one step at a time; click *Done, still not working*
  to move on. The technician step (internal solenoids) is **locked**:
  *"This step needs a trained technician."*
- **Make a 3D model** (optional, ~1 min, needs internet): a 3D model of the
  photographed part from an open model on the Hugging Face hub.

### 3. A maintenance technician reports the same fault (3 min)

Click **Change** under "You" → *Maintenance technician · More than 5 years · Yes*
→ "Maintenance professional".

Same photo, these words:

> VF-2 throwing alarm 120 low air pressure mid-cycle, feed hold. Shop air at the regulator reads around 75 psi. Way lube tank level not checked yet.

Point out the difference: more faults ranked (pressure switch, lube system),
technical steps (*raise supply to 85–90 psi*, *check the Low Air diagnostic
bit*), lockout steps unlocked, page references to the alarm table and
maintenance schedule.

### 4. Machine health — looking ahead (2 min)

**Machine health** → 8 hours/day, 6 days/week → **Forecast**.
Show *Checks coming up* (converted to calendar time, each cited to the
maintenance schedule) and *Parts most likely to cause the next stop* (from the
problem history). Say: *"It's an estimate for planning, and it improves as the
shop records more fixes."*

### 5. Close the loop (1 min)

Back on the report → **That fixed it** in the guide (or **Mark as fixed** with a
note). Next time anyone reports a similar problem, Greywiz cites this fix as a
*Past fix*.

---

## Lines for the questions

- **"Is this your own AI model?"** No. We use hosted models through APIs —
  Google Gemini for reading photos and writing answers, and an open 3D model
  (Tencent Hunyuan3D-2) from the Hugging Face hub. We don't train or host an LLM.
- **"Why not just ChatGPT?"** It's built for one job: *this* machine. It only
  answers from the company's own documents, cites the page for every step,
  refuses steps it can't source, adapts to who is asking, and locks technician
  work for trainees.
- **"Where does the data come from?"** Only what the company uploads, plus
  official documents it agrees to add. We don't feed it a dataset.
- **"Is the alarm photo real?"** The control panel photo is real (Wikimedia
  Commons, CC BY-SA); the alarm on the screen is simulated for the demo. Alarm
  120 and its causes come from the real Haas service manual.

## If something goes wrong

- *"All Gemini models are out of quota"* → switch to a key with billing, restart.
- 3D model fails → say it depends on a free public service; skip it.
- A document stuck on "Processing" → it's still reading pages (CPU); use the ones already processed.
