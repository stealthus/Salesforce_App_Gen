import os
import sys
import openai
import logging
import requests
from docx import Document
from azure.storage.filedatalake import DataLakeServiceClient, DataLakeFileClient
from azure.ai.formrecognizer import DocumentAnalysisClient
from azure.core.credentials import AzureKeyCredential
import tempfile
import io

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
                file_contents = file_client.download_file().readall()

                with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(filename)[1]) as tmp:
                    tmp.write(file_contents)
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

        azure_context = ""
        if docs_info:
            relevant_azure_texts = []
            for doc in docs_info:
                full_text = doc.get("text", "")
                filename = doc.get("filename", "Unknown")
                if not full_text.strip():
                    continue
                if any(term.lower() in full_text.lower() for term in summarized_requirements.split()[:30]):
                    relevant_azure_texts.append((filename, full_text))
                    logging.info(f"[MATCH] {filename} matched summarized requirements.")
            if relevant_azure_texts:
                azure_context = "\n\n".join([text for _, text in relevant_azure_texts])[:8000]
            else:
                logging.warning("[AZURE] No relevant Azure documents found.")
                azure_context = "No relevant documents found in the Azure repository."

        internet_data = ""
        if use_internet:
            logging.info("[MODE] Internet ON – Retrieving external context.")
            serp_results = serpapi_search(summarized_requirements)
            for result in serp_results:
                title = result.get("title", "")
                snippet = result.get("snippet", "")
                link = result.get("link", "")
                summary = summarize_text(f"{title} - {snippet}", 150)
                internet_data += (
                    f"Source: {link}\n"
                    f"Title: {title}\n"
                    f"Snippet: {snippet}\n"
                    f"Summary: {summary}\n\n"
                )

        prompt_sections = [
            f"# User Prompt\n{user_prompt.strip()}",
            f"# Requirements Summary\n{summarized_requirements.strip()}"
        ]

        if azure_context:
            prompt_sections.append(f"# Azure Repository Insights\n{azure_context.strip()}")
        if internet_data.strip():
            prompt_sections.append(f"# Internet Findings\n{internet_data.strip()}")

        full_prompt = "\n\n".join(prompt_sections)

        response = openai.ChatCompletion.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "You are a technical expert in Salesforce and enterprise software integrations."},
                {"role": "user", "content": full_prompt}
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

# === Question Answering from Document ===
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
