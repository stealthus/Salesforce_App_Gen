import os
import openai
import logging
import requests
from docx import Document
from PyPDF2 import PdfReader
import faiss
import numpy as np
import io
from azure.storage.blob import BlobServiceClient

# === Logging ===
logging.basicConfig(level=logging.INFO)

# === Environment Variables ===
openai.api_key = os.environ.get("OPENAI_API_KEY")
SERP_API_KEY = os.environ.get("SERP_API_KEY")
AZURE_STORAGE_CONNECTION_STRING = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
AZURE_BLOB_CONTAINER_NAME = os.environ.get("AZURE_BLOB_CONTAINER_NAME")

# === Azure Blob Setup ===
blob_service_client = BlobServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)
container_client = blob_service_client.get_container_client(AZURE_BLOB_CONTAINER_NAME)

# === Config ===
MODEL = "gpt-3.5-turbo"

# === Utilities ===

def read_docx(file_path):
    try:
        doc = Document(file_path)
        return "\\n".join([p.text for p in doc.paragraphs if p.text.strip()])
    except Exception as e:
        logging.error(f"[DOCX READ ERROR] {e}")
        return ""

def read_pdf(file_path):
    try:
        reader = PdfReader(file_path)
        return "\\n".join([page.extract_text() for page in reader.pages if page.extract_text()])
    except Exception as e:
        logging.error(f"[PDF READ ERROR] {e}")
        return ""

def chunk_text(text, max_words=1200):
    words = text.split()
    return [' '.join(words[i:i + max_words]) for i in range(0, len(words), max_words)]

def summarize_text(text, max_tokens=800):
    try:
        response = openai.ChatCompletion.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "Summarize technical content concisely."},
                {"role": "user", "content": f"Summarize this in {max_tokens} tokens:\\n{text[:8000]}"}
            ],
            max_tokens=max_tokens,
            temperature=0.5
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logging.error(f"[OpenAI SUMMARY ERROR] {e}")
        return "Summary failed."

def serpapi_search(query, max_results=3):
    try:
        params = {
            "engine": "google",
            "q": query,
            "api_key": SERP_API_KEY
        }
        response = requests.get("https://serpapi.com/search.json", params=params, timeout=10)
        return response.json().get("organic_results", [])[:max_results]
    except Exception as e:
        logging.error(f"[SERPAPI ERROR] {e}")
        return []

def fetch_all_documents_from_blob():
    docs_info = []
    for blob in container_client.list_blobs():
        if blob.name.endswith(".pdf") or blob.name.endswith(".docx"):
            blob_client = container_client.get_blob_client(blob.name)
            stream = blob_client.download_blob().readall()
            try:
                if blob.name.endswith(".pdf"):
                    reader = PdfReader(io.BytesIO(stream))
                    text = "\\n".join([page.extract_text() for page in reader.pages if page.extract_text()])
                else:
                    doc = Document(io.BytesIO(stream))
                    text = "\\n".join([p.text for p in doc.paragraphs if p.text.strip()])
                docs_info.append({"filename": blob.name, "text": text})
            except Exception as e:
                logging.error(f"[READ ERROR: {blob.name}] {e}")
    return docs_info

def summarize_uploaded_requirements(requirements_docs):
    combined_text = "\\n".join([doc.get("text", "") for doc in requirements_docs if doc.get("text")])
    return summarize_text(combined_text, max_tokens=800)

def embed_and_index_documents(docs_info):
    embeddings = []
    texts = []
    for doc in docs_info:
        chunks = chunk_text(doc.get("text", ""))
        for chunk in chunks:
            try:
                embedding = openai.Embedding.create(
                    model="text-embedding-ada-002",
                    input=chunk
                )['data'][0]['embedding']
                embeddings.append(embedding)
                texts.append(chunk)
            except Exception as e:
                logging.error(f"[EMBED ERROR] {e}")
    if not embeddings:
        return None, []
    dim = len(embeddings[0])
    index = faiss.IndexFlatL2(dim)
    index.add(np.array(embeddings).astype("float32"))
    return index, texts

def get_relevant_chunks_from_index(query, index, texts, k=3):
    try:
        query_embedding = openai.Embedding.create(
            model="text-embedding-ada-002",
            input=query
        )['data'][0]['embedding']
        D, I = index.search(np.array([query_embedding]).astype("float32"), k)
        return [texts[i] for i in I[0]]
    except Exception as e:
        logging.error(f"[QUERY ERROR] {e}")
        return []

def generate_comprehensive_proposal(requirements_docs, user_prompt, use_internet):
    try:
        summarized_requirements = summarize_uploaded_requirements(requirements_docs)

        docs_info = fetch_all_documents_from_blob()
        full_doc = "\\n".join([doc.get("text", "") for doc in docs_info if doc.get("text")])
        index, texts = embed_and_index_documents(docs_info)

        if not use_internet:
            logging.info("[MODE] Internet OFF: Using Azure documents only.")
            relevant_chunks = get_relevant_chunks_from_index(user_prompt, index, texts)
            document_context = "\\n".join(relevant_chunks)
        else:
            logging.info("[MODE] Internet ON: Adding internet-based context.")
            serp_results = serpapi_search(summarized_requirements)
            internet_data = ""
            for r in serp_results:
                summary = summarize_text(f"{r.get('title', '')} - {r.get('snippet', '')} (Source: {r.get('link', '')})")
                internet_data += f"Source: {r.get('link', '')}\\nTitle: {r.get('title', '')}\\nSummary: {summary}\\n\\n"
            document_context = "\\n".join(get_relevant_chunks_from_index(user_prompt, index, texts))
            user_prompt = user_prompt.replace("{{internet_data}}", internet_data)

        user_prompt = user_prompt.replace("{{requirements}}", summarized_requirements)
        user_prompt = user_prompt.replace("{{document_content}}", document_context[:8000])

        response = openai.ChatCompletion.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "You are a technical expert integrating Salesforce solutions."},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=3500,
            temperature=0.7
        )
        return response.choices[0].message.content.strip()

    except Exception as e:
        logging.error(f"[generate_comprehensive_proposal ERROR] {e}")
        return "Unable to generate a response due to an internal error."