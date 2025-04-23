import os
import sys
import openai
import logging
import requests
from docx import Document
from PyPDF2 import PdfReader
from azure.storage.filedatalake import DataLakeServiceClient
import tempfile


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

def read_pdf(file_path):
    try:
        reader = PdfReader(file_path)

        if reader.is_encrypted:
            try:
                reader.decrypt("")  # provide a password if needed
            except Exception as e:
                logging.warning(f"[PDF ENCRYPTION] Skipped encrypted file: {e}")
                return ""

        text = []
        for i, page in enumerate(reader.pages):
            try:
                page_text = page.extract_text()
                if page_text:
                    text.append(page_text)
            except Exception as e:
                logging.warning(f"[PDF PARSE ERROR] Skipping page {i}: {e}")

        return "\n".join(text)

    except Exception as e:
        logging.error(f"[PDF READ ERROR] Entire file skipped: {e}")
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
                    text = read_pdf(tmp.name) if filename.endswith(".pdf") else read_docx(tmp.name)

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

# === Logic ===
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
        result = response.choices[0].message.content.strip()
        logging.info(f"[PROPOSAL OK] First 200 characters:\n{result[:200]}...")
        return result
    except Exception as e:
        logging.error(f"[OpenAI PROPOSAL ERROR] {e}")
        return "Proposal generation failed."

def generate_comprehensive_proposal(requirements_text, docs_info, user_prompt, use_internet):
    try:
        full_doc = "\n".join([doc.get("text", "") for doc in docs_info if doc.get("text")])

        if not full_doc.strip():
            logging.warning("[EMPTY] No usable content from documents")
            return "No valid content found in uploaded documents."

        if not use_internet:
            logging.info("[MODE] Internet OFF")
            return answer_question_from_doc(full_doc, user_prompt)

        logging.info("[MODE] Internet ON")
        summarized_requirements = summarize_text(requirements_text, 800)
        serp_results = serpapi_search(summarized_requirements)

        internet_data = ""
        for result in serp_results:
            snippet = result.get('snippet', '')
            summary = summarize_text(snippet, 150)
            internet_data += f"- {result.get('title', '')}: {summary}\n"

        final_prompt = user_prompt
        final_prompt += f"\n\n# Summary:\n{summarized_requirements}"
        final_prompt += f"\n\n# Internet Research:\n{internet_data}"
        final_prompt += f"\n\n# Document Content:\n{full_doc[:8000]}"

        response = openai.ChatCompletion.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "You are a technical Salesforce expert."},
                {"role": "user", "content": final_prompt}
            ],
            max_tokens=3500,
            temperature=0.7
        )
        result = response.choices[0].message.content.strip()
        logging.info(f"[GENERATION OK] First 200 characters:\n{result[:200]}...")
        return result

    except Exception as e:
        logging.error(f"[GENERATION ERROR] {e}")
        return "Unable to generate a response due to internal error."
