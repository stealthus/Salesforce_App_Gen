import os
import sys
import openai
import logging
import requests
from docx import Document
from PyPDF2 import PdfReader
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

print("Intenret")

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

def read_pdf(file_path):
    try:
        reader = PdfReader(file_path)
        return "\n".join([page.extract_text() for page in reader.pages if page.extract_text()])
    except Exception as e:
        logging.error(f"[PDF READ ERROR] {e}")
        return ""

# === Azure Data Lake Reader ===
def get_datalake_service_client():
    account_name = os.environ.get("AZURE_STORAGE_ACCOUNT_NAME")
    account_key = os.environ.get("AZURE_STORAGE_ACCOUNT_KEY")
    return DataLakeServiceClient(
        account_url=f"https://{account_name}.dfs.core.windows.net",
        credential=account_key
    )

def read_files_from_datalake():
    try:
        ACCOUNT_NAME = os.environ.get("AZURE_STORAGE_ACCOUNT_NAME")
        ACCOUNT_KEY = os.environ.get("AZURE_STORAGE_ACCOUNT_KEY")
        FILESYSTEM_NAME = os.environ.get("AZURE_DATA_LAKE_FILESYSTEM")

        logging.info(f"[DATALAKE] Connecting to Data Lake: {ACCOUNT_NAME}, filesystem: {FILESYSTEM_NAME}")

        service_client = DataLakeServiceClient(
            account_url=f"https://{ACCOUNT_NAME}.dfs.core.windows.net",
            credential=ACCOUNT_KEY
        )
        file_system_client = service_client.get_file_system_client(FILESYSTEM_NAME)
        paths = file_system_client.get_paths()

        docs_info = []
        file_count = 0

        for path in paths:
            if path.is_directory:
                continue
            try:
                file_path = path.name
                logging.info(f"[DATALAKE] Reading file: {file_path}")

                file_client = file_system_client.get_file_client(file_path)
                download = file_client.download_file()
                file_data = download.readall()

                text = ""
                if file_path.lower().endswith(".pdf"):
                    logging.info(f"[DATALAKE] Detected PDF: {file_path}")
                    text = analyze_pdf_with_ai(io.BytesIO(file_data), filename=file_path)
                elif file_path.lower().endswith(".docx"):
                    logging.info(f"[DATALAKE] Detected DOCX: {file_path}")
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as tmp:
                        tmp.write(file_data)
                        tmp.flush()
                        text = read_docx(tmp.name)
                else:
                    logging.info(f"[DATALAKE] Detected text file: {file_path}")
                    text = file_data.decode("utf-8", errors="ignore")

                if text.strip():
                    char_count = len(text)
                    logging.info(f"[DATALAKE] Extracted {char_count} characters from: {file_path}")
                    docs_info.append({"filename": file_path, "text": text})
                else:
                    logging.warning(f"[DATALAKE] No content extracted from: {file_path}")

            except Exception as e:
                logging.error(f"[DATALAKE DOC READ ERROR] {path.name} => {e}")

        logging.info(f"[DATALAKE] Total files processed: {len(docs_info)}")
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
        return response.choices[0].message.content.strip()
    except Exception as e:
        logging.error(f"[OpenAI SUMMARY ERROR] {e}")
        return "Summary failed."

def serpapi_search(query, max_results=5):
    try:
        params = {"engine": "google", "q": query, "api_key": SERP_API_KEY}
        response = requests.get("https://serpapi.com/search.json", params=params, timeout=10)
        return response.json().get("organic_results", [])[:max_results]
    except Exception as e:
        logging.error(f"[SERPAPI ERROR] {e}")
        return []

def extract_requested_word_count(user_prompt):
    match = re.search(r"(\d{2,5})\s*words?", user_prompt.lower())
    return int(match.group(1)) if match else None

def calculate_max_tokens(word_count):
    return int(word_count * 1.5)

def answer_question_from_repository(user_question):
    try:
        logging.info("[REPO QA] Reading documents from repository for QA")
        azure_docs = read_files_from_datalake()
        processed_texts = []

        for doc in azure_docs:
            filename = doc.get("filename", "").lower()
            if filename.endswith(".pdf"):
                logging.info(f"[REPO QA] Analyzing PDF with AI: {filename}")
                try:
                    file_client = get_datalake_service_client().get_file_system_client(
                        os.getenv("AZURE_DATA_LAKE_FILESYSTEM")
                    ).get_file_client(filename)
                    download = file_client.download_file()
                    file_data = download.readall()
                    processed_text = analyze_pdf_with_ai(io.BytesIO(file_data), filename=filename)
                except Exception as e:
                    logging.error(f"[REPO QA] Error reprocessing PDF: {filename} → {e}")
                    processed_text = doc.get("text", "")
                processed_texts.append(processed_text)
            else:
                processed_texts.append(doc.get("text", ""))

        all_text = "\n\n".join([t for t in processed_texts if t.strip()])
        if not all_text:
            logging.warning("[REPO QA] No content extracted from repository.")
            return "No valid repository content available for answering the question."

        logging.info(f"[REPO QA] Total repository characters: {len(all_text)}")
        chunks = chunk_text(all_text)
        logging.info(f"[REPO QA] Total chunks generated: {len(chunks)}")

        # Search through all chunks, not limited
        for i, chunk in enumerate(chunks):
            try:
                logging.info(f"[REPO QA] Searching in chunk {i+1}/{len(chunks)}")
                prompt = f"""
You are a technical assistant. Use ONLY the repository content below to answer the user's question. Be accurate and concise.

Repository Content:
\"\"\"{chunk}\"\"\"

User Question:
{user_question}

If the answer is not present in the above content, reply strictly with:
"The answer is not available in the repository documents."
"""
                response = openai.ChatCompletion.create(
                    model=MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=500,
                    temperature=0.2
                )
                answer = response.choices[0].message.content.strip()

                # Return immediately if it's not the fallback response
                if "not available" not in answer.lower():
                    logging.info(f"[REPO QA] Answer found in chunk {i+1}")
                    return answer

            except Exception as e:
                logging.error(f"[OpenAI REPO QA ERROR in chunk {i+1}] {e}")

        return "The answer is not available in the repository documents."

    except Exception as e:
        logging.error(f"[REPO QA ERROR] {e}")
        return "Unable to answer the question due to an internal error."




def limit_text_by_words(text, word_limit):
    words = text.split()
    return ' '.join(words[:word_limit])

def safe_concatenate_and_trim(docs, word_limit):
    combined = "\n\n".join(docs)
    return limit_text_by_words(combined, word_limit)


# === Proposal Generation ===
def generate_comprehensive_proposal(requirements_text, docs_info, user_prompt, use_internet):
    try:
        # === Step 1: Summarize uploaded document ===
        logging.info("[STEP 1] Summarizing uploaded document")
        summarized_requirements = summarize_text(requirements_text, 800)
        uploaded_doc_text = safe_concatenate_and_trim(
            [doc.get("text", "") for doc in docs_info if doc.get("text")],
            word_limit=3000
        )

        # === Step 2: Classify prompt intent ===
        logging.info("[STEP 2] Classifying user prompt intent")
        intent_prompt = f"""
You are a smart assistant classifying user intent. Choose exactly ONE of the following categories:

1. question-about-uploaded-document → The user is asking only about the uploaded document (e.g., "Summarize", "What does this file say?", "Explain this doc").
2. question-about-repository → The user is asking about information that likely exists in previously stored reference documents from the repository (e.g., "What does the policy say about X?" or "What standards are defined in the archive?").
3. solution-needed-from-repo → The user is asking for a solution or system design that requires using repository examples, specifications, or strategies.
4. full-context → The user is asking for a complete proposal or output requiring uploaded doc + repository + external knowledge (e.g., internet search).

User Prompt:
{user_prompt.strip()}

Respond with only the exact category name.
"""
        intent_response = openai.ChatCompletion.create(
            model=MODEL,
            messages=[{"role": "user", "content": intent_prompt.strip()}],
            max_tokens=10,
            temperature=0
        )
        mode = intent_response.choices[0].message.content.strip().lower()
        logging.info(f"[INTENT] Classified user prompt as: {mode}")

        # === Special Mode: Repository-only QA ===
        if mode == "question-about-repository":
            logging.info("[SPECIAL MODE] Answering question based only on repository documents")
            azure_docs = read_files_from_datalake()
            all_text = "\n\n".join([doc.get("text", "") for doc in azure_docs if doc.get("text")])

            internet_data = ""
            if use_internet:
                logging.info("[INTERNET AUGMENTATION] Augmenting repo-based response with internet search")
                serp_results = serpapi_search(user_prompt)
                for result in serp_results:
                    snippet_summary = summarize_text(f"{result.get('title')} - {result.get('snippet')}", 150)
                    internet_data += (
                        f"Source: {result.get('link')}\n"
                        f"Title: {result.get('title')}\n"
                        f"Snippet: {result.get('snippet')}\n"
                        f"Summary: {snippet_summary}\n\n"
                    )

            if internet_data:
                combined_prompt = f"""
You are a helpful assistant. Answer the question using the repository content and internet findings below.

# Repository Documents:
{all_text}

# Internet Findings:
{internet_data}

Question:
{user_prompt.strip()}
"""
                response = openai.ChatCompletion.create(
                    model=MODEL,
                    messages=[{"role": "user", "content": combined_prompt}],
                    max_tokens=2000,
                    temperature=0.5
                )
                return response.choices[0].message.content.strip()
            else:
                return answer_question_from_doc(all_text, user_prompt)

        # === Step 3: Gather repository content ===
        logging.info("[STEP 3] Reading all Azure Data Lake documents (no keyword filtering)")
        azure_context = ""
        if mode in ["repository-needed", "solution-needed-from-repo", "full-context"]:
            azure_docs = read_files_from_datalake()
            logging.info(f"[REPO] Total documents read from Data Lake: {len(azure_docs)}")

            all_texts = [doc.get("text", "") for doc in azure_docs if doc.get("text", "").strip()]
            azure_context = "\n\n".join(all_texts)

            logging.info(f"[REPO] Combined repository content word count: {len(azure_context.split())}")

        # === Step 4: Gather internet data ===
        logging.info("[STEP 4] Searching internet context (if required)")
        internet_data = ""
        if use_internet and mode == "full-context":
            serp_results = serpapi_search(summarized_requirements)
            for result in serp_results:
                snippet_summary = summarize_text(f"{result.get('title')} - {result.get('snippet')}", 150)
                internet_data += (
                    f"Source: {result.get('link')}\n"
                    f"Title: {result.get('title')}\n"
                    f"Snippet: {result.get('snippet')}\n"
                    f"Summary: {snippet_summary}\n\n"
                )

        # === Step 5: Calculate max token allowance ===
        logging.info("[STEP 5] Calculating max token allowance")
        requested_words = extract_requested_word_count(user_prompt)
        dynamic_max_tokens = min(calculate_max_tokens(requested_words), 7000) if requested_words else 3500

        word_instruction = ""
        if requested_words:
            word_instruction = (
                f"IMPORTANT: Your response must be at least {requested_words} words. "
                "Do not stop early. Expand fully until reaching the requested word count."
            )

        # === Step 6: Build final prompt ===
        logging.info("[STEP 6] Constructing final prompt for OpenAI")
        sections = [
                word_instruction,
                f"# User Prompt\n{user_prompt.strip()}",
                f"# Requirements Summary\n{summarized_requirements.strip()}",
                f"# Uploaded Document Context\n{uploaded_doc_text.strip()}",
                f"# Repository Insights\n{azure_context.strip()}",
                "IMPORTANT: Pay special attention to small details such as phone numbers, emails, addresses, clause references, and identifiers within the repository documents."
            ]

        if azure_context:
            sections.append(f"# Repository Insights\n{azure_context.strip()}")
        if internet_data:
            sections.append(f"# Internet Findings\n{internet_data.strip()}")

        final_prompt = "\n\n".join(sections)
        logging.info(f"[OPENAI] Prompt word count: {len(final_prompt.split())}, max_tokens: {dynamic_max_tokens}")

        # === Step 7: Call OpenAI ===
        logging.info("[STEP 7] Calling OpenAI to generate final proposal")
        response = openai.ChatCompletion.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "You are a technical expert and must strictly follow the user's instructions, especially regarding word count."},
                {"role": "user", "content": final_prompt}
            ],
            max_tokens=dynamic_max_tokens,
            temperature=0.6
        )

        return response.choices[0].message.content.strip()

    except Exception as e:
        logging.error(f"[generate_comprehensive_proposal ERROR] {e}")
        return "Unable to generate a response due to an internal error."


