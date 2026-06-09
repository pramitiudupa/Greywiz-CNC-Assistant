# How TableRAG Works (In Plain English)

Imagine you have a massive PDF manual for an industrial machine. Inside this manual are dozens of tables full of numbers (like gear combinations, twist rates, and sizes). 

If you try to put this entire PDF into a standard AI chatbot like ChatGPT, it usually gets confused by the tables. It might read the rows and columns out of order, or it might not realize that a table on page 5 applies to the "18.5mm wharve" mentioned back on page 4.

**TableRAG** is a system built to solve exactly this problem. It extracts tables, gives them "memory" of the text around them, and lets you chat with them accurately. 

Here is an in-depth, step-by-step explanation of how the whole system works.

---

## Step 1: Extracting Tables and their "Context" (The Parser)
*Code file: `table_processor.py`*

First, the original PDF is converted into a Markdown (`.md`) file using an external tool (like MinerU). This `.md` file contains the text of the manual, with the tables formatted as HTML code.

Our system reads this `.md` file from top to bottom. When it finds a table, it doesn't just rip the table out in isolation. It performs **"intelligent bundling."**

**How intelligent bundling works:**
Think of reading a textbook. If you see a table, you usually read the paragraph right above it to understand what the table is about. Our system does the same thing. 
1. **Sticky Headings:** It keeps track of the section headings (e.g., "## 5.3 Twist Change Table"). 
2. **Context Carry-forward:** It grabs the text immediately preceding the table (e.g., "- Front bottom roller diameter 27 mm"). 
3. If there are three tables back-to-back, it's smart enough to know that the introductory text applies to *all three* of those tables, not just the first one. 

The result is a "bundle": The raw table data + the surrounding text that explains what the table is for.

## Step 2: Generating a "Smart" Description (The Agent)
*Code file: `summarizer.py`*

Now we have a bundle (Table + Context), but it's still just raw data. We need to make it easily searchable. 

We send this bundle to an AI (Google's Gemini) and ask it to act as an "expert industrial data analyst." We give the AI strict rules:
1. **Find Machine Specs:** Look at the context text and explicitly write down any machine specifications (like "19mm wharve diameter").
2. **Expand Abbreviations:** Turn confusing shorthand into plain English (e.g., change "T/m" to "Twists per meter").
3. **Write a Summary:** Write a comprehensive paragraph explaining exactly what this table shows, including the ranges of the variables.

**Why do we do this?** Because if a technician searches for *"What's the twist per inch for a 19mm wharve?"*, those exact words might not exist inside the raw table itself. But by having the AI write a rich summary that *combines* the table data and the context, we create a highly searchable description.

## Step 3: Creating a Memory (Vectorization & Storage)
*Code files: `vector_store.py` and `storage.py`*

Computers don't read text the way we do; they prefer math. 

We take the rich AI-generated summaries from Step 2 and run them through an "Embedding Model." This turns the paragraph of text into a long list of numbers (a vector). You can think of this as placing the summary at a specific coordinate on a giant 3D map of concepts. 

We then save two things:
1. **The Vector Database (FAISS):** A searchable map of all our summaries.
2. **The Cache:** We save the raw tables and their summaries to your hard drive. If you run the program again tomorrow on the same file, it recognizes that nothing has changed and skips Step 2, saving you time and API costs.

## Step 4: Asking a Question (The Search)
*Code file: `vector_store.py`*

Now the system is ready for you to use. You open the chat interface (`app.py`) and type a question:
*"What gear combination gives me 35.64 twists per inch on the 18.5 mm wharve?"*

The system takes your question and turns it into a vector (a coordinate on that same mathematical map). It then asks the Vector Database (FAISS): *"Which of our table summaries is located closest to this question?"*

Because our AI summaries in Step 2 explicitly included terms like "twists per inch" and "18.5 mm wharve", the database easily finds the exact right table.

## Step 5: Generating the Final Answer
*Code file: `summarizer.py` and `main.py`*

Now we have found the correct table, but we still need to answer your specific question. 

We go back to the AI (Gemini) one last time. We give it:
1. The raw table data we just found.
2. The smart summary we generated in Step 2 (so the AI knows the context, like wharve sizes and units).
3. Your specific question.

We tell the AI: *"You are a helpful assistant. Look at this table and its description, and answer the user's question. Do the math if you have to."*

The AI reads the table, finds the exact row and column for 35.64 twists per inch, notes the gear combination, and types out a friendly, accurate response for you in the chat interface.

---

## Summary of Recent Fixes

Initially, there were a few "broken links" in this chain, which have now been fixed:
1. **Context was getting dropped:** If tables were back-to-back, the parser forgot the machine specs. We fixed the parser to remember "sticky" headings and context.
2. **Summaries were ignoring specs:** The AI was being lazy and sometimes leaving out the wharve size. We updated the prompt to **force** the AI to state machine specs in the very first sentence.
3. **The final answer was "blind":** In Step 5, the AI was only being handed the raw numbers, not the summary. If you asked about an "18.5mm wharve", it would say "I don't see that in the table." We fixed this by passing the smart summary alongside the table in the final step, so the AI has the full picture.
