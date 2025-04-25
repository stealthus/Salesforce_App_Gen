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

def generate_solution_from_prompt(document_text, user_prompt):
    try:
        chunks = chunk_text(document_text)
        context = "\n".join(chunks[:3])  # using first few chunks only
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


# === Azure Data Lake Integration ===
def get_datalake_service_client():
    account_name = os.environ.get("AZURE_STORAGE_ACCOUNT_NAME")
    account_key = os.environ.get("AZURE_STORAGE_ACCOUNT_KEY")
    return DataLakeServiceClient(
        account_url=f"https://{account_name}.dfs.core.windows.net",
        credential=account_key
    )

def read_files_from_datalake():
    ACCOUNT_NAME = os.environ.get("AZURE_STORAGE_ACCOUNT_NAME")
    ACCOUNT_KEY = os.environ.get("AZURE_STORAGE_ACCOUNT_KEY")
    FILESYSTEM_NAME = os.environ.get("AZURE_DATA_LAKE_FILESYSTEM")

    service_client = DataLakeServiceClient(
        account_url=f"https://{ACCOUNT_NAME}.dfs.core.windows.net",
        credential=ACCOUNT_KEY
    )
    file_system_client = service_client.get_file_system_client(FILESYSTEM_NAME)
    paths = file_system_client.get_paths()

    docs = []

    for path in paths:
        try:
            if path.is_directory:
                continue

            file_path = path.name
            logging.info(f"[READING] {file_path}")
            file_client = file_system_client.get_file_client(file_path)

            download = file_client.download_file()
            bytes_data = download.readall()

            # === Handle PDF ===
            if file_path.lower().endswith(".pdf"):
                file_contents = analyze_pdf_with_ai(io.BytesIO(bytes_data), filename=file_path)

            # === Handle TXT, DOCX, or Fallback ===
            elif file_path.lower().endswith(".docx"):
                with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as tmp:
                    tmp.write(bytes_data)
                    tmp.flush()
                    file_contents = read_docx(tmp.name)
            else:
                file_contents = bytes_data.decode("utf-8", errors="ignore")

            docs.append({
                "filename": file_path,
                "text": file_contents
            })

        except Exception as e:
            logging.error(f"[FAIL READ] {file_path} => {e}")

    return docs

# === Proposal Generation ===
def generate_comprehensive_proposal(requirements_text, docs_info, user_prompt, use_internet):
    try:
        full_doc = "\n".join([doc.get("text", "") for doc in docs_info if doc.get("text")])
        summarized_requirements = summarize_text(requirements_text, 800)

        # === Use OpenAI to infer intent smartly ===
        intent_prompt = f"""
You are a smart assistant. Classify this user prompt into one of the following categories:
- question-about-uploaded-document: The user is asking a question based on the uploaded document.
- solution-needed-from-repo: The user is seeking a solution, proposal, or design, not just Q&A.
Prompt:
{user_prompt.strip()}
Respond with only one of the above categories.
"""

        intent_response = openai.ChatCompletion.create(
            model=MODEL,
            messages=[{"role": "user", "content": intent_prompt.strip()}],
            max_tokens=10,
            temperature=0
        )
        mode = intent_response.choices[0].message.content.strip().lower()
        logging.info(f"[INTENT] Mode selected: {mode}")

        # === If user asks a question about the document, answer from doc ===
        if mode == "question-about-uploaded-document":
            logging.info("[MODE] Mode: question-about-uploaded-document")

            logging.info(f"[DEBUG] Uploaded Document Content Length: {len(requirements_text)}")
            logging.info(f"[DEBUG] First 300 characters of document:\n{requirements_text[:300]}")

            summary = summarize_text(requirements_text, max_tokens=600)
            logging.info(f"[SUMMARY] {summary[:300]}...")

            combined_context = f"Summary:\n{summary}\n\nFull Document:\n{requirements_text}"

            answer = answer_question_from_doc(combined_context, user_prompt)
            logging.info(f"[RESULT] Preview: {answer[:300]}")
            return answer

        # === If user seeks a solution, pull from repository ===
        elif mode == "solution-needed-from-repo" and not use_internet:
            logging.info("[MODE] Building solution using repo + uploaded requirements (no internet)")

            azure_docs = read_files_from_datalake()
            keywords = re.findall(r"\\w+", summarized_requirements.lower())[:30]

            matches = []
            for doc in azure_docs:
                content = doc.get("text", "").lower()
                if any(k in content for k in keywords):
                    matches.append(doc.get("text", ""))
                    logging.info(f"[MATCH] {doc.get('filename')} relevant to problem statement.")

            repo_insights = "\n\n".join(matches)[:8000] if matches else "No repository matches found."

            final_prompt = f"""
# User Prompt
{user_prompt.strip()}

# Requirements Summary
{summarized_requirements.strip()}

# Uploaded Document Content
{requirements_text.strip()}

# Repository Insights
{repo_insights}
"""

            response = openai.ChatCompletion.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": "You are a technical expert designing Salesforce solutions."},
                    {"role": "user", "content": final_prompt}
                ],
                max_tokens=3500,
                temperature=0.7
            )
            return response.choices[0].message.content.strip()

        else:
            logging.info("[MODE] Full-context mode: using document, repository, and internet.")

            serp_results = serpapi_search(summarized_requirements)
            internet_data = ""
            for result in serp_results:
                title = result.get("title", "")
                snippet = result.get("snippet", "")
                link = result.get("link", "")
                summary = summarize_text(f"{title} - {snippet}", 150)
                internet_data += f"Source: {link}\nTitle: {title}\nSnippet: {snippet}\nSummary: {summary}\n\n"

            azure_docs = read_files_from_datalake()
            keywords = re.findall(r"\\w+", summarized_requirements.lower())[:30]
            matches = []
            for doc in azure_docs:
                content = doc.get("text", "").lower()
                if any(k in content for k in keywords):
                    matches.append(doc.get("text", ""))
                    logging.info(f"[MATCH] {doc.get('filename')} relevant.")
            repo_insights = "\n\n".join(matches)[:8000] if matches else "No repository matches found."

            final_prompt = f"""
# Prompt
{user_prompt.strip()}

# Requirements Summary
{summarized_requirements.strip()}

# Uploaded Document Content
{requirements_text.strip()}

# Repository Insights
{repo_insights}

# Internet Insights
{internet_data.strip()}
"""

            response = openai.ChatCompletion.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": "You are a Salesforce and enterprise architecture expert."},
                    {"role": "user", "content": final_prompt}
                ],
                max_tokens=3500,
                temperature=0.7
            )
            return response.choices[0].message.content.strip()

    except Exception as e:
        logging.error(f"[generate_comprehensive_proposal ERROR] {e}")
        return "Unable to generate a response due to an internal error."


# === Question Answering from Document ===

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
