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
        df = pd.DataFrame(grid)
        table_str = df.to_string(index=False, header=False)
        
        prompt_template = os.getenv("SUMMARIZER_SYSTEM_PROMPT", "").replace("\\n", "\n")
        if not prompt_template:
            raise ValueError("SUMMARIZER_SYSTEM_PROMPT not found in environment variables.")
        
        prompt = prompt_template.format(context=context, table_str=table_str)
        
        response = self.model.generate_content(prompt)
        return response.text.strip()

    def answer_query(self, query: str, context_table: str, summary: str = "") -> str:
        summary_section = ""
        if summary:
            summary_section = f"TABLE DESCRIPTION (machine specs, units, and context):\n{summary}\n"

        prompt_template = os.getenv("QA_SYSTEM_PROMPT", "").replace("\\n", "\n")
        if not prompt_template:
            raise ValueError("QA_SYSTEM_PROMPT not found in environment variables.")
            
        prompt = prompt_template.format(summary_section=summary_section, context_table=context_table, query=query)

        response = self.model.generate_content(prompt)
        return response.text.strip()
