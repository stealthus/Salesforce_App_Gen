import os
import sys
from openai import OpenAI
openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
import logging
import requests
import tempfile
import io
import re

from docx import Document
from PyPDF2 import PdfReader
from azure.storage.filedatalake import DataLakeServiceClient
from azure.ai.formrecognizer import DocumentAnalysisClient
from azure.core.credentials import AzureKeyCredential

# LlamaIndex updated imports (as per v0.10.30 modular structure)
from llama_index.core import VectorStoreIndex, SimpleDirectoryReader, ServiceContext
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.llms.openai import OpenAI
from llama_index.core.node_parser import SentenceWindowNodeParser
from llama_index.core.text_splitter import SentenceSplitter
# === Logging Setup ===
logging.basicConfig(
    level=logging.INFO,
    stream=sys.stdout,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logging.getLogger().addHandler(logging.StreamHandler(sys.stdout))

# === Environment Variables ===
SERP_API_KEY = os.environ.get("SERP_API_KEY")
MODEL = "gpt-4-turbo"

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
                    
                    # ✅ Content preview (limit to 300 characters)
                    preview = text[:300].replace("\n", " ").replace("\r", "")
                    logging.info(f"[DATALAKE CONTENT PREVIEW] {file_path}:\n{preview}...")
                    
                    docs_info.append({"filename": file_path, "text": text})
                else:
                    logging.warning(f"[DATALAKE] No content extracted from: {file_path}")

            except Exception as e:
                logging.error(f"[DATALAKE DOC READ ERROR] {path.name} => {e}")

        # ✅ Summary log
        logging.info(f"[DATALAKE] Total files processed: {len(docs_info)}")
        for doc in docs_info:
            logging.info(f"[DATALAKE SUMMARY] {doc['filename']} (Length: {len(doc['text'])} characters)")

        return docs_info

    except Exception as e:
        logging.error(f"[DATALAKE CONNECTION ERROR] {e}")
        return []

def read_repository_docs_with_llama():
    # Azure Data Lake configuration
    api_key = os.environ.get("OPENAI_API_KEY")
    ACCOUNT_NAME = os.environ.get("AZURE_STORAGE_ACCOUNT_NAME")
    ACCOUNT_KEY = os.environ.get("AZURE_STORAGE_ACCOUNT_KEY")
    FILESYSTEM_NAME = os.environ.get("AZURE_DATA_LAKE_FILESYSTEM")

    # Initialize Data Lake service client
    service_client = DataLakeServiceClient(
        account_url=f"https://{ACCOUNT_NAME}.dfs.core.windows.net",
        credential=ACCOUNT_KEY
    )
    file_system_client = service_client.get_file_system_client(FILESYSTEM_NAME)
    paths = file_system_client.get_paths()

    # Temporary directory to store downloaded files
    with tempfile.TemporaryDirectory() as temp_dir:
        for path in paths:
            if path.is_directory:
                continue

            file_path = path.name
            ext = file_path.split(".")[-1].lower()
            if ext not in ["pdf", "docx", "txt"]:
                continue

            try:
                file_client = file_system_client.get_file_client(file_path)
                download = file_client.download_file()
                file_data = download.readall()

                # Save file to temporary directory
                local_file_path = os.path.join(temp_dir, os.path.basename(file_path))
                with open(local_file_path, "wb") as f:
                    f.write(file_data)

            except Exception as e:
                logging.error(f"Error processing file {file_path}: {e}")

        # Initialize embedding model and LLM
        embed_model = OpenAIEmbedding(api_key=api_key)
        llm = OpenAI(api_key=api_key)

        # Set up service context
        service_context = ServiceContext.from_defaults(
            embed_model=embed_model,
            llm=llm
        )

        # Load documents from the temporary directory
        documents = SimpleDirectoryReader(temp_dir).load_data()

        # Initialize text splitter and node parser
        text_splitter = SentenceSplitter(chunk_size=512, chunk_overlap=50)
        node_parser = SentenceWindowNodeParser.from_defaults(
            window_size=3,
            window_metadata_key="window",
            original_text_metadata_key="original_text",
            text_splitter=text_splitter
        )

        # Parse documents into nodes
        nodes = node_parser.get_nodes_from_documents(documents)

        # Create vector index
        index = VectorStoreIndex(nodes, service_context=service_context)

        return index

# === Helpers ===
def chunk_text(text, max_words=1200):
    words = text.split()
    return [' '.join(words[i:i + max_words]) for i in range(0, len(words), max_words)]

def summarize_text(text, max_tokens=800):
    try:
        response = openai_client.chat.completions.create(
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
            response = openai_client.chat.completions.create(
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
        intent_response = openai_client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": intent_prompt.strip()}],
            max_tokens=10,
            temperature=0
        )
        mode = intent_response.choices[0].message.content.strip().lower()
        logging.info(f"[INTENT] Classified user prompt as: {mode}")

        # === Step 3: Gather repository content using LlamaIndex ===
        logging.info("[STEP 3] Querying repository content from Azure Data Lake via LlamaIndex")
        azure_context = ""
        if mode in ["repository-needed", "solution-needed", "full-context"]:
            index = read_repository_docs_with_llama()
            query_engine = index.as_query_engine()
            azure_context = query_engine.query(user_prompt).response.strip()
            logging.info("[REPO] LlamaIndex response for repository query obtained.")

        # === Step 4: Gather internet data (optional) ===
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
        response = openai_client.chat.completions.create(
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

