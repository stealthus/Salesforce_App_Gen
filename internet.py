import os
import openai
from docx import Document
from PyPDF2 import PdfReader
from fpdf import FPDF
import requests
import faiss
import numpy as np
import logging
from azure.storage.blob import BlobServiceClient
import io

# === Logging ===
logging.basicConfig(level=logging.INFO)

# === Environment ===
openai.api_key = os.environ["OPENAI_API_KEY"]
SERP_API_KEY = os.environ["SERP_API_KEY"]
AZURE_STORAGE_CONNECTION_STRING = os.environ["AZURE_STORAGE_CONNECTION_STRING"]
BLOB_CONTAINER = "vector-db"
BLOB_NAME = "faiss_index.idx"

# === Embedding Model ===
MODEL = "gpt-3.5-turbo"

# === File Readers ===
def read_docx(file_path):
    doc = Document(file_path)
    return "\n".join([p.text for p in doc.paragraphs if p.text.strip()])

def read_pdf(file_path):
    reader = PdfReader(file_path)
    return "\n".join([page.extract_text() for page in reader.pages if page.extract_text()])

# === Summarizer ===
def summarize_text(text, max_tokens=800):
    try:
        logging.info("[OpenAI] Summarizing text...")
        response = openai.ChatCompletion.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "Summarize technical content concisely."},
                {"role": "user", "content": f"Summarize this in {max_tokens} tokens:\n{text[:8000]}"}
            ],
            max_tokens=max_tokens,
            temperature=0.5
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logging.error(f"[OpenAI ERROR] {e}")
        return "Summary not available due to an error."

# === Search ===
def serpapi_search(query, max_results=3):
    try:
        logging.info("[SERPAPI] Searching...")
        params = {
            "engine": "google",
            "q": query,
            "api_key": SERP_API_KEY
        }
        response = requests.get("https://serpapi.com/search.json", params=params).json()
        return response.get("organic_results", [])[:max_results]
    except Exception as e:
        logging.error(f"[SERPAPI ERROR] {e}")
        return []

# === Azure Blob Helpers ===
def upload_faiss_index_to_azure(index):
    blob_service = BlobServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)
    container_client = blob_service.get_container_client(BLOB_CONTAINER)
    container_client.create_container(exist_ok=True)

    index_bytes = faiss.serialize_index(index)
    container_client.upload_blob(name=BLOB_NAME, data=index_bytes, overwrite=True)
    logging.info(f"[Azure] Uploaded FAISS index to blob '{BLOB_NAME}'")

def download_faiss_index_from_azure():
    try:
        blob_service = BlobServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)
        blob_client = blob_service.get_blob_client(container=BLOB_CONTAINER, blob=BLOB_NAME)

        stream = io.BytesIO()
        download_stream = blob_client.download_blob()
        stream.write(download_stream.readall())
        stream.seek(0)

        index = faiss.deserialize_index(stream.read())
        logging.info("[Azure] FAISS index downloaded successfully.")
        return index
    except Exception as e:
        logging.warning(f"[Azure] Could not load existing index. ({e}) Returning None.")
        return None

# === Create + Store Index ===
def create_vector_db_and_upload(docs_info):
    if not docs_info:
        return None

    texts = [doc["summary"] for doc in docs_info]
    embeddings = [openai.Embedding.create(input=t, model="text-embedding-ada-002")["data"][0]["embedding"] for t in texts]
    array = np.array(embeddings).astype("float32")

    index = faiss.IndexFlatL2(array.shape[1])
    index.add(array)

    upload_faiss_index_to_azure(index)
    return index

# === Proposal Generator ===
def generate_comprehensive_proposal(requirements_text, docs_info, user_prompt, use_internet):
    summarized_requirements = summarize_text(requirements_text, 800)

    internet_data = ""
    if use_internet:
        serp_results = serpapi_search(summarized_requirements)
        for i, result in enumerate(serp_results):
            snippet_summary = summarize_text(f"{result['title']} - {result['snippet']} (Source: {result['link']})", 150)
            docs_info.append({"filename": f"SERP_{i+1}", "summary": snippet_summary})
        internet_data = "\n".join([f"Source: {r['link']}\nTitle: {r['title']}\nSnippet: {r['snippet']}\n" for r in serp_results])

    create_vector_db_and_upload(docs_info)

    final_prompt = user_prompt.replace("{{requirements}}", summarized_requirements)\
                              .replace("{{internet_data}}", internet_data)

    try:
        logging.info("[OpenAI] Generating proposal...")
        response = openai.ChatCompletion.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "You are a Salesforce integration expert."},
                {"role": "user", "content": final_prompt}
            ],
            max_tokens=3500,
            temperature=0.7
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logging.error(f"[OpenAI Generation ERROR] {e}")
        return "Proposal generation failed."
