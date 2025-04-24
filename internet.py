import os
import sys
import openai
import logging
import requests
from docx import Document
from azure.storage.filedatalake import DataLakeServiceClient
from azure.ai.formrecognizer import DocumentAnalysisClient
from azure.core.credentials import AzureKeyCredential
import tempfile
import io
import re

# === Logging Setup ===
logging.basicConfig(
    level=logging.INFO,
    stream=sys.stdout,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logging.getLogger().addHandler(logging.StreamHandler(sys.stdout))

# === Environment Variables ===
openai.api_key = os.environ.get("OPENAI_API_KEY")
SERP_API_KEY = os.environ.get("SERP_API_KEY")
MODEL = "gpt-3.5-turbo"

# === File Readers ===
def read_docx(file_path):
    try:
        doc = Document(file_path)
        return "\n".join([p.text for p in doc.paragraphs if p.text.strip()])
    except Exception as e:
        logging.error(f"[DOCX READ ERROR] {e}")
        return ""

def analyze_pdf_with_ai(pdf_bytes, filename="unknown.pdf"):
    try:
        endpoint = os.getenv("AZURE_FORM_RECOGNIZER_ENDPOINT")
        key = os.getenv("AZURE_FORM_RECOGNIZER_KEY")
        client = DocumentAnalysisClient(endpoint, AzureKeyCredential(key))
        poller = client.begin_analyze_document("prebuilt-document", document=pdf_bytes)
        result = poller.result()

        extracted_text = []
        for page in result.pages:
            for line in page.lines:
                extracted_text.append(line.content)

        for table in result.tables:
            extracted_text.append("\n--- Table ---")
            for cell in table.cells:
                extracted_text.append(f"Cell[{cell.row_index},{cell.column_index}]: {cell.content}")

        logging.info(f"[FORM RECOGNIZER] Extracted {len(extracted_text)} lines from {filename}")
        return "\n".join(extracted_text)
    except Exception as e:
        logging.error(f"[FORM RECOGNIZER ERROR] {filename} => {e}")
        return ""

def read_pdf(filename):
    try:
        filesystem = os.environ.get("AZURE_DATA_LAKE_FILESYSTEM")
        service_client = get_datalake_service_client()
        file_client = service_client.get_file_system_client(filesystem).get_file_client(filename)
        logging.info(f"[ACCESSING PDF FROM DATALAKE] Reading: {filename}")
        pdf_bytes = file_client.download_file().readall()
        return analyze_pdf_with_ai(pdf_bytes, filename)
    except Exception as e:
        logging.error(f"[READ FAILURE] {filename} => {e}")
        return ""

# === Helpers ===
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
        summary = response.choices[0].message.content.strip()
        logging.info(f"[SUMMARY OK] {summary[:200]}...")
        return summary
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

# === Azure Data Lake Integration ===
def get_datalake_service_client():
    account_name = os.environ.get("AZURE_STORAGE_ACCOUNT_NAME")
    account_key = os.environ.get("AZURE_STORAGE_ACCOUNT_KEY")
    return DataLakeServiceClient(
        account_url=f"https://{account_name}.dfs.core.windows.net",
        credential=account_key
    )

def read_files_from_datalake():
    try:
        filesystem = os.environ.get("AZURE_DATA_LAKE_FILESYSTEM")
        service_client = get_datalake_service_client()
        file_system_client = service_client.get_file_system_client(filesystem)
        paths = file_system_client.get_paths()

        documents = []

        for path in paths:
            if path.is_directory:
                continue

            filename = path.name.split("/")[-1]
            if not filename.lower().endswith((".pdf", ".docx")):
                logging.info(f"[SKIP] Unsupported file type: {filename}")
                continue

            try:
                file_client = file_system_client.get_file_client(path.name)
                stream = file_client.download_file()
                downloaded_bytes = b"".join([chunk for chunk in stream.chunks()])

                with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(filename)[1]) as tmp:
                    tmp.write(downloaded_bytes)
                    tmp.flush()
                    text = read_pdf(path.name) if filename.endswith(".pdf") else read_docx(tmp.name)

                if text.strip():
                    documents.append({"filename": filename, "text": text})
                    logging.info(f"[READ OK] {filename} => {len(text)} characters")
                else:
                    logging.warning(f"[SKIP] {filename} => No readable content")
            except Exception as e:
                logging.error(f"[FAIL READ] {filename} => {e}")

        if not documents:
            logging.warning("[DATA LAKE] No valid documents found.")
        return documents

    except Exception as e:
        logging.error(f"[DATA LAKE READ ERROR] {e}")
        return []

# === Proposal Generation ===
def generate_comprehensive_proposal(requirements_text, docs_info, user_prompt, use_internet):
    try:
        summarized_requirements = summarize_text(requirements_text, 800)
        logging.info("[SUMMARY] Requirements summary created.")

        intent_analysis_prompt = f"""
Determine whether the following prompt is asking only about the uploaded document, or also needs additional insights from a repository of documents.
Respond with either:
- document-only
- repository-needed

Prompt:
{user_prompt.strip()}
"""

        intent_response = openai.ChatCompletion.create(
            model=MODEL,
            messages=[{"role": "user", "content": intent_analysis_prompt.strip()}],
            max_tokens=10,
            temperature=0
        )

        intent_mode = intent_response.choices[0].message.content.strip().lower()
        logging.info(f"[INTENT CHECK] Prompt classified as: {intent_mode}")

        azure_context = ""
        if use_internet or intent_mode == "repository-needed":
            logging.info("[AZURE] Accessing repository documents...")
            azure_docs = read_files_from_datalake()
            relevant_texts = []
            for doc in azure_docs:
                full_text = doc.get("text", "").lower()
                if not full_text.strip():
                    continue
                summary_keywords = re.findall(r"\w+", summarized_requirements.lower())[:30]
                if any(keyword in full_text for keyword in summary_keywords):
                    relevant_texts.append(full_text)
                    logging.info(f"[MATCH] {doc.get('filename')} matched requirements.")
            azure_context = "\n\n".join(relevant_texts)[:8000] if relevant_texts else "No relevant documents found in repository."

        internet_data = ""
        if use_internet:
            logging.info("[INTERNET] Fetching results via SERP API.")
            serp_results = serpapi_search(summarized_requirements)
            for result in serp_results:
                summary = summarize_text(f"{result.get('title')} - {result.get('snippet')}", 150)
                internet_data += f"Source: {result.get('link')}\nTitle: {result.get('title')}\nSnippet: {result.get('snippet')}\nSummary: {summary}\n\n"

        prompt_parts = [
            f"# Prompt\n{user_prompt}",
            f"# Requirements Summary\n{summarized_requirements}"
        ]
        if azure_context:
            prompt_parts.append(f"# Azure Repository Insights\n{azure_context.strip()}")
        if internet_data:
            prompt_parts.append(f"# Internet Findings\n{internet_data.strip()}")

        full_prompt = "\n\n".join(prompt_parts)

        response = openai.ChatCompletion.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "You are a technical expert in Salesforce and enterprise integrations."},
                {"role": "user", "content": full_prompt.strip()}
            ],
            max_tokens=3500,
            temperature=0.7
        )

        result = response.choices[0].message.content.strip()
        logging.info(f"[SUCCESS] Proposal generated. Preview: {result[:200]}...")
        return result

    except Exception as e:
        logging.error(f"[ERROR] Failed to generate comprehensive proposal: {e}")
        return "Unable to generate a response due to an internal error."

# === QA Mode ===
def answer_question_from_doc(document_text, user_question):
    chunks = chunk_text(document_text)
    for i, chunk in enumerate(chunks):
        try:
            logging.info(f"[QA] Chunk {i+1}/{len(chunks)}")
            prompt = f"""
You are a helpful assistant. Answer the question strictly using the document content below.

Document:
\"\"\"{chunk}\"\"\"

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
            logging.info(f"[QA OK] Answer from chunk {i+1}: {answer[:150]}...")
            if "not available" not in answer.lower() and "not found" not in answer.lower():
                return answer
        except Exception as e:
            logging.error(f"[QA ERROR Chunk {i+1}] {e}")
    return "The answer is not available in the document."
