import os
from dotenv import load_dotenv
load_dotenv()

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

if not AZURE_STORAGE_CONNECTION_STRING:
    raise ValueError("AZURE_STORAGE_CONNECTION_STRING environment variable not set.")

# === Azure Blob Setup ===
blob_service_client = BlobServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)
container_client = blob_service_client.get_container_client(AZURE_BLOB_CONTAINER_NAME)

# === Config ===
MODEL = "gpt-3.5-turbo"

# === Utilities ===
def read_docx(file_path):
    try:
        doc = Document(file_path)
        return "\n".join([p.text for p in doc.paragraphs if p.text.strip()])
    except Exception as e:
        logging.error(f"[DOCX READ ERROR] {e}")
        return ""

def read_pdf(file_path):
    try:
        reader = PdfReader(file_path)
        return "\n".join([page.extract_text() for page in reader.pages if page.extract_text()])
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
                {"role": "user", "content": f"Summarize this in {max_tokens} tokens:\n{text[:8000]}"}
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

# === FAISS Vector Functions ===
def save_faiss_to_blob(index, blob_name="vector_index/faiss.index"):
    try:
        buffer = faiss.serialize_index(index)
        blob_client = container_client.get_blob_client(blob_name)
        blob_client.upload_blob(buffer, overwrite=True)
        logging.info("✅ FAISS index uploaded to Azure Blob.")
    except Exception as e:
        logging.error(f"[FAISS UPLOAD ERROR] {e}")

def load_faiss_from_blob(blob_name="vector_index/faiss.index"):
    try:
        blob_client = container_client.get_blob_client(blob_name)
        if not blob_client.exists():
            logging.info("ℹ️ FAISS index not found in blob storage.")
            return None
        buffer = blob_client.download_blob().readall()
        index = faiss.deserialize_index(buffer)
        logging.info("✅ FAISS index loaded from Azure Blob.")
        return index
    except Exception as e:
        logging.error(f"[FAISS LOAD ERROR] {e}")
        return None

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

# === Proposal Logic ===
def generate_solution_from_prompt(document_text, user_prompt):
    try:
        chunks = chunk_text(document_text)
        context = "\n".join(chunks[:3])
        final_prompt = user_prompt.replace("{{document_content}}", context)
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
        logging.error(f"[OpenAI PROPOSAL ERROR] {e}")
        return "Proposal generation failed."

# === QA Logic ===
def answer_question_from_doc(document_text, user_question):
    chunks = chunk_text(document_text)
    for i, chunk in enumerate(chunks):
        try:
            logging.info(f"[QA Chunk {i+1}/{len(chunks)}] Searching for answer...")

            prompt = f"""
You are a helpful assistant. Answer the question strictly using the document content below.

Document:
\"\"\"
{chunk}
\"\"\"

Question:
{user_question}

If the answer is not found, say: "The answer is not available in the document."
"""

            response = openai.ChatCompletion.create(
                model=MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=400,
                temperature=0.2
            )

            answer = response.choices[0].message.content.strip()
            if "not available" not in answer.lower() and "not found" not in answer.lower():
                return answer  # Return first valid answer found

        except Exception as e:
            logging.error(f"[OpenAI QA ERROR Chunk {i+1}] {e}")

    return "The answer is not available in the document."


# === Main Entry Point
def generate_comprehensive_proposal(requirements_text, docs_info, user_prompt, use_internet):
    try:
        full_doc = "\n".join([doc.get("text", "") for doc in docs_info if doc.get("text")])

        if not use_internet:
            logging.info("[MODE] Internet OFF: answering strictly from document.")
            return answer_question_from_doc(full_doc, user_prompt)

        else:
            logging.info("[MODE] Internet ON: referencing document + requirements + internet.")

            summarized_requirements = summarize_text(requirements_text, 800)
            serp_results = serpapi_search(summarized_requirements)

            internet_data = ""
            for i, result in enumerate(serp_results):
                snippet_summary = summarize_text(
                    f"{result.get('title', '')} - {result.get('snippet', '')} (Source: {result.get('link', '')})",
                    150
                )
                internet_data += f"Source: {result.get('link', '')}\nTitle: {result.get('title', '')}\nSnippet: {result.get('snippet', '')}\nSummary: {snippet_summary}\n\n"

            final_prompt = user_prompt

            if "{{requirements}}" in final_prompt:
                final_prompt = final_prompt.replace("{{requirements}}", summarized_requirements)
            else:
                final_prompt += f"\n\n# Requirements Summary:\n{summarized_requirements}"

            if "{{internet_data}}" in final_prompt:
                final_prompt = final_prompt.replace("{{internet_data}}", internet_data)
            else:
                final_prompt += f"\n\n# Internet Findings:\n{internet_data}"

            if "{{document_content}}" in final_prompt:
                final_prompt = final_prompt.replace("{{document_content}}", full_doc[:8000])
            else:
                final_prompt += f"\n\n# Document Reference:\n{full_doc[:8000]}"

            response = openai.ChatCompletion.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": "You are a technical expert integrating Salesforce solutions."},
                    {"role": "user", "content": final_prompt}
                ],
                max_tokens=3500,
                temperature=0.7
            )
            return response.choices[0].message.content.strip()

    except Exception as e:
        logging.error(f"[generate_comprehensive_proposal ERROR] {e}")
        return "Unable to generate a response due to an internal error."


