import os
from typing import List, Dict
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_community.vectorstores import FAISS
from langchain.docstore.document import Document
from dotenv import load_dotenv

load_dotenv()

class VectorStoreManager:
    def __init__(self, model_name: str = "gemini-embedding-2"):
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY not found in environment variables.")
        
        self.embeddings = GoogleGenerativeAIEmbeddings(model=model_name, google_api_key=api_key)
        self.vector_store = None

    def create_index(self, summaries: List[str], metadatas: List[Dict]):
        documents = [
            Document(page_content=summary, metadata=metadata)
            for summary, metadata in zip(summaries, metadatas)
        ]
        self.vector_store = FAISS.from_documents(documents, self.embeddings)

    def search(self, query: str, k: int = 1) -> List[Document]:
        if not self.vector_store:
            raise ValueError("Vector store not initialized. Call create_index first.")
        return self.vector_store.similarity_search(query, k=k)

    def save_local(self, folder_path: str):
        if self.vector_store:
            self.vector_store.save_local(folder_path)

    def load_local(self, folder_path: str):
        self.vector_store = FAISS.load_local(folder_path, self.embeddings, allow_dangerous_deserialization=True)
