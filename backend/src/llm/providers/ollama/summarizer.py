import os
from dotenv import load_dotenv
from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage

load_dotenv()


class TableSummarizer:
    """Ollama-based QA engine. Default model: gemma4:26b-a4b-it-qat."""

    def __init__(self, model_name: str | None = None):
        model_name = model_name or os.getenv(
            "OLLAMA_LLM_MODEL", "gemma4:26b-a4b-it-qat"
        )
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        num_ctx = int(os.getenv("OLLAMA_NUM_CTX", "32768"))

        self.model = ChatOllama(
            model=model_name,
            base_url=base_url,
            num_ctx=num_ctx,
            temperature=1.0,
            top_p=0.95,
            top_k=64,
        )

    def answer_query(self, query: str, context_table: str) -> str:
        """Answer a user question using table chunk(s) as grounding context."""
        prompt_template = os.getenv("QA_SYSTEM_PROMPT", "").replace("\\n", "\n")
        if not prompt_template:
            raise ValueError(
                "QA_SYSTEM_PROMPT not found in environment variables."
            )

        prompt = prompt_template.format(
            context_table=context_table,
            query=query,
        )

        response = self.model.invoke([HumanMessage(content=prompt)])
        return response.content.strip()
