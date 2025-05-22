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
import pinecone

# === Logging Setup ===
logging.basicConfig(
    level=logging.INFO,
    stream=sys.stdout,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logging.getLogger().addHandler(logging.StreamHandler(sys.stdout))

# === Environment Variables ===
PINECONE_API_KEY = os.environ.get("PINECONE_API_KEY")
PINECONE_ENVIRONMENT = os.environ.get("PINECONE_ENVIRONMENT")
PINECONE_INDEX_NAME = os.environ.get("PINECONE_INDEX_NAME")

openai.api_key = os.environ.get("OPENAI_API_KEY")
SERP_API_KEY = os.environ.get("SERP_API_KEY")
MODEL = "gpt-3.5-turbo"

print("hello")

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

def index_all_documents_to_pinecone(docs_info):
    try:
        pinecone.init(api_key=PINECONE_API_KEY, environment=PINECONE_ENVIRONMENT)

        if PINECONE_INDEX_NAME not in pinecone.list_indexes():
            pinecone.create_index(PINECONE_INDEX_NAME, dimension=3072, metric="cosine")

        index = pinecone.Index(PINECONE_INDEX_NAME)

        for i, doc in enumerate(docs_info):
            try:
                text = doc.get("text", "").strip()
                if not text:
                    continue

                input_text = text[:12000]  # truncate to stay within token limit

                embedding_response = openai.Embedding.create(
                    input=input_text,
                    model="text-embedding-3-large"
                )
                embedding = embedding_response["data"][0]["embedding"]

                index.upsert([
                    (f"doc-{i}", embedding, {"filename": doc["filename"]})
                ])
                logging.info(f"[PINECONE] Indexed {doc['filename']}")

            except Exception as e:
                logging.error(f"[PINECONE ERROR] {doc.get('filename', 'unknown')} => {e}")

    except Exception as e:
        logging.error(f"[PINECONE INIT ERROR] {e}")

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

def limit_text_by_words(text, word_limit):
    words = text.split()
    return ' '.join(words[:word_limit])

def safe_concatenate_and_trim(docs, word_limit):
    combined = "\n\n".join(docs)
    return limit_text_by_words(combined, word_limit)

def pinecone_vector_search(query_text, top_k=5):
    try:
        pinecone.init(api_key=os.environ.get("PINECONE_API_KEY"), environment=os.environ.get("PINECONE_ENVIRONMENT"))
        index = pinecone.Index(os.environ.get("PINECONE_INDEX_NAME"))

        embedding_response = openai.Embedding.create(
            input=query_text[:12000],
            model="text-embedding-3-large"
        )
        embedding = embedding_response["data"][0]["embedding"]

        results = index.query(vector=embedding, top_k=top_k, include_metadata=True)

        chunks = []
        for match in results.get("matches", []):
            metadata = match.get("metadata", {})
            chunk_text = metadata.get("text", "")
            if chunk_text:
                chunks.append(chunk_text)

        logging.info(f"[PINECONE SEARCH] Retrieved {len(chunks)} matches from Pinecone.")
        return "\n\n---\n\n".join(chunks)

    except Exception as e:
        logging.error(f"[PINECONE SEARCH ERROR] {e}")
        return ""

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
        logging.info(f"[INTENT] Classified user prompt as: {mode}")

        # === Step 3: Retrieve repository content from Pinecone ===
        logging.info("[STEP 3] Retrieving repository context from Pinecone vector DB")
        azure_context = ""
        if mode in ["repository-needed", "solution-needed", "full-context"]:
            try:
                from pinecone import Pinecone
                pinecone.init(
                    api_key=os.environ.get("PINECONE_API_KEY"),
                    environment=os.environ.get("PINECONE_ENVIRONMENT")
                )
                index = Pinecone().Index(os.environ.get("PINECONE_INDEX_NAME"))

                embedding_response = openai.Embedding.create(
                    input=summarized_requirements[:12000],
                    model="text-embedding-3-large"
                )
                embedding = embedding_response["data"][0]["embedding"]

                pinecone_results = index.query(
                    vector=embedding,
                    top_k=5,
                    include_metadata=True
                )

                matches = [
                    match["metadata"].get("text", "")
                    for match in pinecone_results.get("matches", [])
                    if "metadata" in match and "text" in match["metadata"]
                ]

                if matches:
                    azure_context = safe_concatenate_and_trim(matches, word_limit=3000)
                    logging.info(f"[PINECONE] Retrieved {len(matches)} chunks from vector DB.")
                else:
                    azure_context = "No relevant vector matches found in the repository."
                    logging.warning("[PINECONE] No matches found.")

            except Exception as e:
                logging.error(f"[PINECONE RETRIEVAL ERROR] {e}")
                azure_context = "No relevant repository content could be retrieved."

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
            f"# Uploaded Document Context\n{uploaded_doc_text.strip()}"
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
