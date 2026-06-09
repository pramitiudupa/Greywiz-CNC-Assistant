import os
import google.generativeai as genai
from dotenv import load_dotenv
from typing import List
import pandas as pd

load_dotenv()

class TableSummarizer:
    def __init__(self, model_name: str = "gemini-2.5-flash"):
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY not found in environment variables.")
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(model_name)

    def summarize_bundle(self, context: str, grid: List[List[str]]) -> str:
        """
        Generates an intelligent, search-optimized summary of a table and its context.
        Performs unit expansion and metadata inheritance.
        """
        df = pd.DataFrame(grid)
        table_str = df.to_string(index=False, header=False)
        
        prompt = f"""You are an expert industrial data analyst. Analyze the following table and its surrounding context.

CONTEXT FROM DOCUMENT:
{context}

TABLE DATA:
{table_str}

TASK:
Generate a comprehensive, search-optimized summary. You MUST follow ALL of these rules:

1. MACHINE SPECIFICATIONS: If the context mentions ANY machine specs (Wharve diameter, Roller diameter, machine model, retrofit kit, etc.), you MUST explicitly state them in the FIRST sentence of your summary. Example: "This table applies to machines with a 19mm wharve diameter and 27mm front bottom roller diameter, retrofitted with EliTeCompactSet."

2. UNIT EXPANSION: Always include full names alongside shorthand (e.g., T/m = Twists per meter, T/" = Twists per inch, TPM = Twists per minute).

3. KEY VARIABLES: List the independent variables (e.g., gear tooth counts) and the dependent variable (e.g., twist values), including their ranges.

4. SEARCH OPTIMIZATION: Write so that a technician searching for specific specs (e.g., "18.5mm wharve twist per inch") would match this summary.

SUMMARY:
"""

        
        response = self.model.generate_content(prompt)
        return response.text.strip()

    def answer_query(self, query: str, retrieved_contexts: List[dict]) -> str:
        context_str = ""
        for i, ctx in enumerate(retrieved_contexts):
            context_str += f"\n--- TABLE CANDIDATE {i+1} ---\n"
            context_str += f"Source File: {ctx.get('name', 'Unknown')}\n"
            if ctx.get('summary'):
                context_str += f"DESCRIPTION (machine specs, units, and context):\n{ctx['summary']}\n"
            context_str += f"TABLE DATA:\n{ctx['table_data']}\n"

        prompt = f"""You are an expert technical assistant. You have retrieved multiple table candidates that might contain the answer to the user's query.

Carefully read the USER QUERY. Pay close attention to specific constraints (like machine specifications, wharve sizes, or units like T/m vs T/inch).
Then, examine the TABLE CANDIDATES below. Choose the correct table that matches ALL the constraints in the query.
Use the data from the chosen table to answer the query accurately. 
If none of the tables contain the required information, say you don't know.

RETRIEVED TABLE CANDIDATES:
{context_str}

USER QUERY: {query}

Answer:
"""

        response = self.model.generate_content(prompt)
        return response.text.strip()
