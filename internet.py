import pdfplumber
import os
import openai
import logging
import requests
from docx import Document
from PyPDF2 import PdfReader
from azure.storage.blob import BlobServiceClient
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import SearchIndex, SimpleField, SearchFieldDataType
from azure.core.credentials import AzureKeyCredential
import io

# === Logging ===
logging.basicConfig(level=logging.INFO)

# === Environment Variables ===
openai.api_key = os.environ.get("OPENAI_API_KEY")
SERP_API_KEY = os.environ.get("SERP_API_KEY")
AZURE_STORAGE_CONNECTION_STRING = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
AZURE_BLOB_CONTAINER_NAME = os.environ.get("AZURE_BLOB_CONTAINER_NAME", "stealthusa")
AZURE_SEARCH_SERVICE_NAME = os.environ.get("AZURE_SEARCH_SERVICE_NAME")
AZURE_SEARCH_API_KEY = os.environ.get("AZURE_SEARCH_API_KEY")

# === Config ===
MODEL = "gpt-3.5-turbo"
INDEX_NAME = "document-embeddings"

# === Azure Blob Setup ===
blob_service_client = BlobServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)
container_client = blob_service_client.get_container_client(AZURE_BLOB_CONTAINER_NAME)

# === Azure Search Setup ===
search_endpoint = f"https://{AZURE_SEARCH_SERVICE_NAME}.search.windows.net"
search_credential = AzureKeyCredential(AZURE_SEARCH_API_KEY)
search_client = SearchClient(endpoint=search_endpoint, index_name=INDEX_NAME, credential=search_credential)
index_client = SearchIndexClient(endpoint=search_endpoint, credential=search_credential)

# === Azure-Based Utilities ===
def list_blob_files():
    try:
        return [blob.name for blob in container_client.list_blobs() if not blob.name.endswith("/")]
    except Exception as e:
        logging.error(f"[AZURE LIST ERROR] {e}")
        return []
    
def read_docx(file_path):
    doc = Document(file_path)
    return "\n".join([p.text for p in doc.paragraphs if p.text.strip()])

def read_pdf(file_path):
    reader = PdfReader(file_path)
    return "\n".join([page.extract_text() for page in reader.pages if page.extract_text()])

def read_blob_file(file_name):
    try:
        blob_client = container_client.get_blob_client(file_name)
        blob_data = blob_client.download_blob().readall()

        if file_name.endswith(".docx"):
            doc = Document(io.BytesIO(blob_data))
            return "\n".join([p.text for p in doc.paragraphs if p.text.strip()])
        elif file_name.endswith(".pdf"):
            reader = PdfReader(io.BytesIO(blob_data))
            return "\n".join([page.extract_text() for page in reader.pages if page.extract_text()])
        else:
            return blob_data.decode("utf-8", errors="ignore")

    except Exception as e:
        logging.error(f"[AZURE READ ERROR] Failed to read {file_name} — {e}")
        return ""

# === Utilities ===
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

# === Embedding and Indexing ===
def ensure_index():
    try:
        index_client.get_index(name=INDEX_NAME)
    except:
        fields = [
            SimpleField(name="id", type=SearchFieldDataType.String, key=True),
            SimpleField(name="filename", type=SearchFieldDataType.String),
            SimpleField(name="content", type=SearchFieldDataType.String),
            SimpleField(name="embedding", type=SearchFieldDataType.Collection(SearchFieldDataType.Single))
        ]
        index = SearchIndex(name=INDEX_NAME, fields=fields)
        index_client.create_index(index)

def embed_and_index_file(file_name):
    ensure_index()
    text = read_blob_file(file_name)
    chunks = chunk_text(text)
    documents = []

    for i, chunk in enumerate(chunks):
        embedding = openai.Embedding.create(input=chunk, model="text-embedding-ada-002")["data"][0]["embedding"]
        documents.append({
            "id": f"{file_name}_{i}",
            "filename": file_name,
            "content": chunk,
            "embedding": embedding
        })

    search_client.upload_documents(documents)
    logging.info(f"Uploaded {len(documents)} chunks for file {file_name}")

# === Proposal Generation ===
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

def answer_question_from_doc(document_text, user_question):
    chunks = chunk_text(document_text)
    for i, chunk in enumerate(chunks):
        try:
            logging.info(f"[QA Chunk {i+1}/{len(chunks)}] Searching for answer...")
            prompt = f"""
You are a helpful assistant. Answer the question strictly using the document content below.

Document:
{chunk}

Question:
{user_question}

If the answer is not found, say: \"The answer is not available in the document.\"
"""
            response = openai.ChatCompletion.create(
                model=MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=400,
                temperature=0.2
            )
            answer = response.choices[0].message.content.strip()
            if "not available" not in answer.lower() and "not found" not in answer.lower():
                return answer
        except Exception as e:
            logging.error(f"[OpenAI QA ERROR Chunk {i+1}] {e}")
    return "The answer is not available in the document."

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
            final_prompt = user_prompt.replace("{{requirements}}", summarized_requirements)\
                                      .replace("{{internet_data}}", internet_data)\
                                      .replace("{{document_content}}", full_doc[:8000])
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