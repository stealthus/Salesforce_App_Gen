import os
import openai
import logging
import requests
from docx import Document
from PyPDF2 import PdfReader
from azure.storage.filedatalake import DataLakeServiceClient
import re
import io
# === Logging ===
logging.basicConfig(level=logging.INFO)

# === API Keys ===
openai.api_key = os.environ.get("OPENAI_API_KEY")
SERP_API_KEY = os.environ.get("SERP_API_KEY")

MODEL = "gpt-3.5-turbo"
print("Reading...")
# === File Readers ===
def analyze_pdf_with_ai(pdf_bytes, filename="unknown.pdf"):
    try:
        endpoint = os.getenv("AZURE_FORM_RECOGNIZER_ENDPOINT")
        key = os.getenv("AZURE_FORM_RECOGNIZER_KEY")
        client = DocumentAnalysisClient(endpoint, AzureKeyCredential(key))

        poller = client.begin_analyze_document("prebuilt-document", document=pdf_bytes, content_type="application/pdf")
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

# === Smart Data Lake Reader ===

def read_files_from_datalake():
    try:
        ACCOUNT_NAME = os.environ.get("AZURE_STORAGE_ACCOUNT_NAME")
        ACCOUNT_KEY = os.environ.get("AZURE_STORAGE_ACCOUNT_KEY")
        FILESYSTEM_NAME = os.environ.get("AZURE_DATA_LAKE_FILESYSTEM")

        service_client = DataLakeServiceClient(
            account_url=f"https://{ACCOUNT_NAME}.dfs.core.windows.net",
            credential=ACCOUNT_KEY
        )
        file_system_client = service_client.get_file_system_client(FILESYSTEM_NAME)
        paths = file_system_client.get_paths()

        docs_info = []

        for path in paths:
            try:
                if path.is_directory:
                    continue

                file_path = path.name
                file_client = file_system_client.get_file_client(file_path)
                download = file_client.download_file()
                file_data = download.readall()

                logging.info(f"[DATALAKE FILE] Reading: {file_path}")

                text = ""
                if file_path.lower().endswith(".pdf"):
                    text = analyze_pdf_with_ai(io.BytesIO(file_data), filename=file_path)

                elif file_path.lower().endswith(".docx"):
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as tmp:
                        tmp.write(file_data)
                        tmp.flush()
                        text = read_docx(tmp.name)

                else:
                    text = file_data.decode("utf-8", errors="ignore")

                if text.strip():
                    logging.info(f"[DATALAKE DOC READ SUCCESS] {file_path} | {len(text)} characters extracted")
                    docs_info.append({
                        "filename": file_path,
                        "text": text
                    })
                else:
                    logging.warning(f"[DATALAKE DOC EMPTY] {file_path} had no readable content.")

            except Exception as inner_e:
                logging.error(f"[DATALAKE DOC READ ERROR] {path.name} => {inner_e}")

        logging.info(f"[DATALAKE TOTAL FILES READ] {len(docs_info)}")
        return docs_info

    except Exception as e:
        logging.error(f"[DATALAKE CONNECTION ERROR] {e}")
        return []

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
        logging.info(f"[SUMMARY OK] {summary[:300]}...")
        return summary
    except Exception as e:
        logging.error(f"[OpenAI SUMMARY ERROR] {e}")
        return "Summary failed."

def serpapi_search(query, max_results=5):
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

# === Question Answering ===
def answer_question_from_doc(document_text, user_question):
    chunks = chunk_text(document_text)
    
    chunks = chunks[:8]
    for i, chunk in enumerate(chunks):
        try:
            logging.info(f"[QA Chunk {i+1}/{len(chunks)}] Searching for answer...")
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
            if "not available" not in answer.lower():
                return answer
        except Exception as e:
            logging.error(f"[OpenAI QA ERROR Chunk {i+1}] {e}")
    return "The answer is not available in the document."

# === Main Proposal Generation ===
def extract_requested_word_count(user_prompt):
    """
    Extract the number of words requested by the user from their prompt text.
    """
    match = re.search(r"(\d{2,5})\s*words?", user_prompt.lower())
    if match:
        return int(match.group(1))
    return None

def calculate_max_tokens(word_count):
    """
    Calculate maximum tokens needed for a given word count.
    1 word ≈ 0.75 tokens, so tokens ≈ words * 1.33
    """
    return int(word_count * 1.33)

# === Your Original Function with Only the Needed Insertions ===
def generate_comprehensive_proposal(requirements_text, docs_info, user_prompt, use_internet):
    try:
        # === Summarize the uploaded document ===
        summarized_requirements = summarize_text(requirements_text, 800)
        uploaded_doc_text = "\n".join([doc.get("text", "") for doc in docs_info if doc.get("text")])

        # === Infer Intent based on User Prompt ===
        intent_prompt = f"""
Classify this prompt into one of the following:
- question-about-uploaded-document
- solution-needed-from-repo
- full-context

Prompt:
{user_prompt.strip()}
"""
        intent_response = openai.ChatCompletion.create(
            model=MODEL,
            messages=[{"role": "user", "content": intent_prompt.strip()}],
            max_tokens=10,
            temperature=0
        )
        mode = intent_response.choices[0].message.content.strip().lower()
        logging.info(f"[INTENT] Mode selected: {mode}")

        # === Mode 1: QA strictly from uploaded document ===
        if mode == "question-about-uploaded-document":
            logging.info("[MODE] Using only the uploaded document for answering.")
            summary = summarize_text(requirements_text, 600)
            combined_context = f"Summary:\n{summary}\n\nFull Document:\n{requirements_text}"

            return answer_question_from_doc(combined_context, user_prompt)

        # === Read repository documents ===
        logging.info("[DATALAKE] Fetching documents from Azure Data Lake...")
        azure_docs = read_files_from_datalake()

        logging.info(f"[DATALAKE] Total repository files fetched: {len(azure_docs)}")
        for doc in azure_docs:
            logging.info(f"[FILE] {doc.get('filename', '')} | Characters: {len(doc.get('text', ''))}")

        # === Mode 2: Build Solution from Repo + Uploaded doc ===
        if mode == "solution-needed-from-repo" and not use_internet:
            logging.info("[MODE] Using repository + uploaded document without internet.")

            keywords = re.findall(r"\w+", summarized_requirements.lower())[:30]
            matches = [doc["text"] for doc in azure_docs if any(k in doc["text"].lower() for k in keywords)]

            repo_insights = "\n\n".join(matches[:3]) if matches else "No strong repository content match found."

            final_prompt = f"""
# User Prompt
{user_prompt}

# Requirements Summary
{summarized_requirements}

# Uploaded Document Context
{uploaded_doc_text[:8000]}

# Repository Insights
{repo_insights}
"""

            # Trim if very large
            if len(final_prompt) > 12000:
                logging.warning("[TRIM] Reducing prompt size to 12000 characters.")
                final_prompt = final_prompt[:12000]

            # === New: Set dynamic max_tokens ===
            requested_words = extract_requested_word_count(user_prompt)
            if requested_words:
                dynamic_max_tokens = min(calculate_max_tokens(requested_words), 7000)
                logging.info(f"[WORD COUNT DETECTED] User requested approx {requested_words} words, setting max_tokens={dynamic_max_tokens}")
            else:
                dynamic_max_tokens = 3500

            response = openai.ChatCompletion.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": "You are an expert Salesforce and enterprise systems integrator."},
                    {"role": "user", "content": final_prompt}
                ],
                max_tokens=dynamic_max_tokens,
                temperature=0.7
            )
            return response.choices[0].message.content.strip()

        # === Mode 3: Full Context (Internet + Repo + Uploaded Doc) ===
        logging.info("[MODE] Using uploaded document + repository + internet context.")

        keywords = re.findall(r"\w+", summarized_requirements.lower())[:30]
        matches = [doc["text"] for doc in azure_docs if any(k in doc["text"].lower() for k in keywords)]
        repo_insights = "\n\n".join(matches[:3]) if matches else "No strong repository content match found."

        internet_data = ""
        if use_internet:
            serp_results = serpapi_search(summarized_requirements)
            for result in serp_results:
                snippet_summary = summarize_text(
                    f"{result.get('title')} - {result.get('snippet')}", 150
                )
                internet_data += f"Source: {result.get('link')}\nTitle: {result.get('title')}\nSnippet: {result.get('snippet')}\nSummary: {snippet_summary}\n\n"

        final_prompt = f"""
# User Prompt
{user_prompt}

# Requirements Summary
{summarized_requirements}

# Uploaded Document Context
{uploaded_doc_text[:8000]}

# Repository Insights
{repo_insights}

# Internet Insights
{internet_data}
"""

        # Again trim if very large
        if len(final_prompt) > 12000:
            logging.warning("[TRIM] Reducing final prompt size to 12000 characters.")
            final_prompt = final_prompt[:12000]

        # === New: Set dynamic max_tokens ===
        requested_words = extract_requested_word_count(user_prompt)
        if requested_words:
            dynamic_max_tokens = min(calculate_max_tokens(requested_words), 7000)
            logging.info(f"[WORD COUNT DETECTED] User requested approx {requested_words} words, setting max_tokens={dynamic_max_tokens}")
        else:
            dynamic_max_tokens = 3500

        response = openai.ChatCompletion.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "You are an expert Salesforce architect and integration consultant."},
                {"role": "user", "content": final_prompt}
            ],
            max_tokens=dynamic_max_tokens,
            temperature=0.7
        )
        return response.choices[0].message.content.strip()

    except Exception as e:
        logging.error(f"[generate_comprehensive_proposal ERROR] {e}")
        return "Unable to generate a response due to an internal error."



