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
from pinecone import Pinecone, ServerlessSpec
from tenacity import retry, wait_fixed, stop_after_attempt

# === Logging Setup ===
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger()

# === Environment Variables ===
openai.api_key = os.getenv("OPENAI_API_KEY")
SERP_API_KEY = os.getenv("SERP_API_KEY")
MODEL = "gpt-4-turbo"

pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
index_name = os.getenv("PINECONE_INDEX_NAME")
region = os.getenv("PINECONE_ENV")

if index_name not in pc.list_indexes().names():
    logger.info(f"[PINECONE] Creating index '{index_name}' in region '{region}'...")
    pc.create_index(
        name=index_name,
        dimension=3072,
        metric="cosine",
        spec=ServerlessSpec(cloud="aws", region=region)
    )

pinecone_index = pc.Index(index_name)

@retry(wait=wait_fixed(2), stop=stop_after_attempt(3))
def get_embedding(chunk):
    return openai.Embedding.create(
        input=chunk,
        model="text-embedding-3-large"
    )["data"][0]["embedding"]

def chunk_text(text, max_words=1200):
    words = text.split()
    chunks = [' '.join(words[i:i + max_words]) for i in range(0, len(words), max_words)]
    logger.info(f"[CHUNKING] Generated {len(chunks)} chunks.")
    return chunks

def index_documents_to_pinecone(docs_info):
    indexed_files = []
    for doc in docs_info:
        filename = doc.get("filename")
        text = doc.get("text", "").strip()
        if not text:
            logger.warning(f"[INDEXING SKIPPED] Empty content: {filename}")
            continue

        chunks = chunk_text(text, max_words=300)
        logger.info(f"[CHUNKING] File '{filename}' split into {len(chunks)} chunks.")

        for i, chunk in enumerate(chunks):
            try:
                if not chunk.strip():
                    logger.warning(f"[SKIPPED] Empty chunk at {filename}__chunk_{i}")
                    continue

                embedding = get_embedding(chunk)
                vector_id = f"{filename}__chunk_{i}"
                pinecone_index.upsert([(vector_id, embedding, {"filename": filename, "text": chunk})])
                logger.info(f"[PINECONE] Indexed: {vector_id}")
            except Exception as e:
                logger.error(f"[PINECONE ERROR] {filename} chunk {i} → {e}")

        indexed_files.append((filename, len(chunks)))

    logger.info(f"[SUMMARY] Total files indexed: {len(indexed_files)}")
    for fname, count in indexed_files:
        logger.info(f"[SUMMARY] {fname} → {count} chunks indexed")


def search_pinecone_by_threshold(query, threshold=0.85):
    try:
        embedding = openai.Embedding.create(
            input=query,
            model="text-embedding-3-large"
        )["data"][0]["embedding"]

        results = pinecone_index.query(
            vector=embedding,
            top_k=100,
            include_metadata=True
        )

        filtered = []
        for match in results['matches']:
            score = match['score']
            metadata = match.get('metadata', {})
            filename = metadata.get('filename', 'Unknown')
            text_snippet = metadata.get('text', '')[:100].replace('\n', ' ') + "..."

            if score >= threshold:
                logger.info(f"[PINECONE SEARCH] Match from {filename} (score: {score:.4f}) → \"{text_snippet}\"")
                filtered.append(f"[SOURCE: {filename}]\n{metadata.get('text')}")

        return filtered or ["No relevant content found in repository."]
    except Exception as e:
        logger.error(f"[PINECONE SEARCH ERROR] {e}")
        return ["Pinecone search failed."]



def read_docx(file_path):
    try:
        doc = Document(file_path)
        return "\n".join([p.text for p in doc.paragraphs if p.text.strip()])
    except Exception as e:
        logger.error(f"[DOCX READ ERROR] {e}")
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
        if result.key_value_pairs:
            for pair in result.key_value_pairs:
                extracted_text.append(f"{pair.key.content}: {pair.value.content}")

        logger.info(f"[FORM RECOGNIZER] Extracted {len(extracted_text)} lines from {filename}")
        return "\n".join(extracted_text)
    except Exception as e:
        logger.error(f"[FORM RECOGNIZER ERROR] {filename} => {e}")
        return ""

def read_pdf(file_path):
    try:
        reader = PdfReader(file_path)
        return "\n".join([page.extract_text() for page in reader.pages if page.extract_text()])
    except Exception as e:
        logger.error(f"[PDF READ ERROR] {e}")
        return ""

def get_datalake_service_client():
    account_name = os.getenv("AZURE_STORAGE_ACCOUNT_NAME")
    account_key = os.getenv("AZURE_STORAGE_ACCOUNT_KEY")
    return DataLakeServiceClient(
        account_url=f"https://{account_name}.dfs.core.windows.net",
        credential=account_key
    )

def read_files_from_datalake():
    try:
        ACCOUNT_NAME = os.getenv("AZURE_STORAGE_ACCOUNT_NAME")
        ACCOUNT_KEY = os.getenv("AZURE_STORAGE_ACCOUNT_KEY")
        FILESYSTEM_NAME = os.getenv("AZURE_DATA_LAKE_FILESYSTEM")

        logger.info(f"[DATALAKE] Connecting to {ACCOUNT_NAME}/{FILESYSTEM_NAME}")
        service_client = DataLakeServiceClient(
            account_url=f"https://{ACCOUNT_NAME}.dfs.core.windows.net",
            credential=ACCOUNT_KEY
        )
        file_system_client = service_client.get_file_system_client(FILESYSTEM_NAME)
        paths = file_system_client.get_paths()

        docs_info = []

        for path in paths:
            if path.is_directory:
                continue
            try:
                file_path = path.name
                file_client = file_system_client.get_file_client(file_path)
                download = file_client.download_file()
                file_data = download.readall()

                if len(file_data) > 10 * 1024 * 1024:
                    logger.warning(f"[SKIPPED] File too large: {file_path}")
                    continue

                text = ""
                if file_path.lower().endswith(".pdf"):
                    text = analyze_pdf_with_ai(io.BytesIO(file_data), filename=file_path)
                elif file_path.lower().endswith(".docx"):
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as tmp:
                        tmp.write(file_data)
                        tmp.flush()
                        text = read_docx(tmp.name)
                elif file_path.lower().endswith(".txt"):
                    text = file_data.decode("utf-8", errors="ignore")
                else:
                    logger.warning(f"[SKIPPED] Unsupported file type: {file_path}")

                if text.strip():
                    docs_info.append({"filename": file_path, "text": text})
                    logger.info(f"[DATALAKE] Loaded {file_path} ({len(text)} chars)")
                    logger.info(f"[DATALAKE] Sample content from {file_path}: {text[:300]}")
                else:
                    logger.warning(f"[DATALAKE] Empty content: {file_path}")

            except Exception as e:
                logger.error(f"[DATALAKE READ ERROR] {path.name} => {e}")

        logger.info(f"[DATALAKE] Processed {len(docs_info)} files.")
        return docs_info

    except Exception as e:
        logger.error(f"[DATALAKE CONNECTION ERROR] {e}")
        return []



# === Helpers ===
def chunk_text(text, max_words=1200):
    words = text.split()
    chunks = [' '.join(words[i:i + max_words]) for i in range(0, len(words), max_words)]
    logging.info(f"[CHUNKING] Created {len(chunks)} chunks (max {max_words} words each).")
    return chunks

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
        logger.info("[REPO QA] Using Pinecone to retrieve relevant repository context")
        pinecone_matches = search_pinecone_by_threshold(user_question, threshold=0.85)

        combined_context = "\n\n".join(pinecone_matches)
        token_estimate = int(len(combined_context.split()) * 1.5)
        logger.info(f"[REPO QA] Retrieved {len(pinecone_matches)} matches, estimated token usage: {token_estimate}")

        if not combined_context.strip():
            logger.warning("[REPO QA] No relevant context found in Pinecone.")
            return "No valid repository content available for answering the question."

        if token_estimate > 100000:
            logger.warning("⚠️ [REPO QA] Retrieved content may exceed GPT-4 Turbo's token limit (~128K).")

        prompt = f"""
You are a technical assistant. Use ONLY the content below (retrieved from a vector database) to answer the user's question.
Be detailed, accurate, and cite any filenames if present.
If the answer is not present, respond with:
"The answer is not available in the repository documents."

# Retrieved Repository Content:
\"\"\"{combined_context}\"\"\"

# User Question:
{user_question}
"""

        response = openai.ChatCompletion.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=3000,
            temperature=0.3
        )

        answer = response.choices[0].message.content.strip()
        logger.info("[REPO QA] Answer successfully generated using Pinecone context")
        return answer

    except Exception as e:
        logger.error(f"[REPO QA ERROR] {e}")
        return "Unable to answer the question due to an internal error."

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


# === Proposal Generation ===
def generate_comprehensive_proposal(requirements_text, docs_info, user_prompt, use_internet):
    try:
        logging.info("[STEP 1] Summarizing uploaded document")
        summarized_requirements = summarize_text(requirements_text, 800)
        uploaded_doc_text = safe_concatenate_and_trim(
            [doc.get("text", "") for doc in docs_info if doc.get("text")],
            word_limit=3000
        )

        logging.info("[STEP 2] Classifying user prompt intent")
        intent_prompt = f"""
You are a smart assistant classifying user intent. Choose exactly ONE of the following categories:

1. question-about-uploaded-document → The user is asking only about the uploaded document.
2. question-about-repository → The user is asking about stored reference documents.
3. solution-needed-from-repo → The user needs a solution using stored repository examples.
4. full-context → The user needs a proposal requiring document + repo + internet.

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

        # === Step 3: Use Pinecone to retrieve relevant repo context ===
        logging.info("[STEP 3] Querying Pinecone for semantically similar context")
        pinecone_context = search_pinecone_by_threshold(user_prompt, threshold=0.85)
        azure_context = "\n\n".join(pinecone_context).strip()

        token_estimate = int(len(azure_context.split()) * 1.5)
        logging.info(f"[REPO] Pinecone word count: {len(azure_context.split())}")
        logging.info(f"[REPO] Token estimate: {token_estimate}")

        if not azure_context:
            azure_context = "[REPO EMPTY] No relevant content retrieved from Pinecone."
        elif token_estimate > 100000:
            logging.warning("⚠️ Pinecone content approaching GPT-4 token limit")

        if not use_internet and mode != "question-about-uploaded-document":
            logging.info("[ENFORCEMENT] Internet OFF. Using only Pinecone context.")
            internet_data = ""
        else:
            logging.info("[STEP 4] Searching internet context if required")
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

        logging.info("[STEP 5] Calculating max token allowance")
        requested_words = extract_requested_word_count(user_prompt)
        dynamic_max_tokens = min(calculate_max_tokens(requested_words), 7000) if requested_words else 3500

        word_instruction = f"IMPORTANT: Your response must be at least {requested_words} words." if requested_words else ""

        logging.info("[STEP 6] Constructing final prompt for OpenAI")
        sections = [
            word_instruction,
            f"# User Prompt\n{user_prompt.strip()}",
            f"# Requirements Summary\n{summarized_requirements.strip()}",
            f"# Uploaded Document Context\n{uploaded_doc_text.strip()}",
            f"# Repository Insights\n{azure_context.strip()}",
            "IMPORTANT: Pay attention to small details like emails, addresses, clause refs."
        ]
        if internet_data:
            sections.append(f"# Internet Findings\n{internet_data.strip()}")

        final_prompt = "\n\n".join([s for s in sections if s.strip()])
        logging.info(f"[OPENAI] Prompt word count: {len(final_prompt.split())}, max_tokens: {dynamic_max_tokens}")

        logging.info("[STEP 7] Calling OpenAI to generate final proposal")
        response = openai.ChatCompletion.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "You are a technical expert. Follow word count instructions."},
                {"role": "user", "content": final_prompt}
            ],
            max_tokens=dynamic_max_tokens,
            temperature=0.6
        )

        return response.choices[0].message.content.strip()

    except Exception as e:
        logging.error(f"[generate_comprehensive_proposal ERROR] {e}")
        return "Unable to generate a response due to an internal error."

def list_indexed_vector_ids():
    try:
        stats = pinecone_index.describe_index_stats()
        total_vectors = stats.get("total_vector_count", 0)
        logging.info(f"[PINECONE] Total vectors currently in index: {total_vectors}")
    except Exception as e:
        logging.error(f"[PINECONE DIAGNOSTIC ERROR] {e}")

if __name__ == "__main__":
    logging.info("[MAIN] ====== Starting Repository Indexing Process ======")

    docs_info = read_files_from_datalake()
    logging.info(f"[MAIN] Total documents fetched from Data Lake: {len(docs_info)}")

    for doc in docs_info:
        filename = doc.get("filename")
        text_length = len(doc.get("text", ""))
        logging.info(f"[MAIN] Document Loaded → {filename} ({text_length} characters)")

    if docs_info:
        logging.info("[MAIN] Indexing documents into Pinecone...")
        index_documents_to_pinecone(docs_info)
        logging.info("[MAIN] ✅ Pinecone indexing completed.")
    else:
        logging.warning("[MAIN] No documents found to index — skipping Pinecone upload.")

    list_indexed_vector_ids()
    logging.info("[MAIN] ====== Indexing Routine Complete ======")   



