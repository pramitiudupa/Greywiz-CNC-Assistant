import os
from google import genai
from dotenv import load_dotenv

from src.llm import gemini_hub

load_dotenv()


class TableSummarizer:
    def __init__(self, model_name: str = "gemini-2.5-flash"):
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY not found in environment variables.")
        self.client = genai.Client(api_key=api_key)
        self.model_name = model_name

    def answer_query(self, query: str, context_table: str) -> str:
        prompt_template = os.getenv("QA_SYSTEM_PROMPT", "").replace("\\n", "\n")
        if not prompt_template:
            raise ValueError("QA_SYSTEM_PROMPT not found in environment variables.")

        prompt = prompt_template.format(context_table=context_table, query=query)

        response, _ = gemini_hub.generate(prompt, gemini=self.client)
        return response.text.strip()
