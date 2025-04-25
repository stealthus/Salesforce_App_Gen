import os
import openai
import logging
import requests
from docx import Document
from PyPDF2 import PdfReader
from azure.storage.filedatalake import DataLakeServiceClient
import re

# === Logging ===
logging.basicConfig(level=logging.INFO)

# === API Keys ===
openai.api_key = os.environ.get("OPENAI_API_KEY")
SERP_API_KEY = os.environ.get("SERP_API_KEY")

MODEL = "gpt-3.5-turbo"
print("Reading...")
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
        return "\n".join([page.extract_text() for page in reader.pages if page.extract_text()])
    except Exception as e:
        logging.error(f"[PDF READ ERROR] {e}")
        return ""

# === Azure Setup ===
def read_files_from_datalake():
    try:
        account_name = os.getenv("AZURE_STORAGE_ACCOUNT_NAME")
        account_key = os.getenv("AZURE_STORAGE_ACCOUNT_KEY")
        filesystem = os.getenv("AZURE_DATA_LAKE_FILESYSTEM")

        service_client = DataLakeServiceClient(
            account_url=f"https://{account_name}.dfs.core.windows.net",
            credential=account_key
        )
        file_system_client = service_client.get_file_system_client(filesystem)
        paths = file_system_client.get_paths()

        docs = []
        for path in paths:
            if path.is_directory:
                continue
            file_client = file_system_client.get_file_client(path.name)
            content = file_client.download_file().readall().decode("utf-8", errors="ignore")
            docs.append({"filename": path.name, "text": content})
        return docs
    except Exception as e:
        logging.error(f"[DATALAKE ERROR] {e}")
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
def generate_comprehensive_proposal(requirements_text, docs_info, user_prompt, use_internet):
    try:
        summarized_requirements = summarize_text(requirements_text, 800)
        full_doc = "\n".join([doc.get("text", "") for doc in docs_info if doc.get("text")])

        # === Intent Classification ===
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

        # === Mode 1: Q&A from uploaded document ===
        if mode == "question-about-uploaded-document":
            logging.info("[MODE] Answering using uploaded document only.")
            summary = summarize_text(requirements_text, 600)
            combined_context = f"Summary:\n{summary}\n\nFull Document:\n{requirements_text}"
            return answer_question_from_doc(combined_context, user_prompt)

        # === Mode 2: Use repository only (no internet) ===
        if mode == "solution-needed-from-repo" and not use_internet:
            logging.info("[MODE] Building solution using repository and uploaded document (no internet).")
            azure_docs = read_files_from_datalake()
            keywords = re.findall(r"\w+", summarized_requirements.lower())[:30]
            matches = [doc["text"] for doc in azure_docs if any(k in doc["text"].lower() for k in keywords)]
            repo_insights = "\n\n".join(matches[:3]) if matches else "No relevant repository content found."

            final_prompt = f"""
# Prompt
{user_prompt}

# Requirements Summary
{summarized_requirements}

# Uploaded Document
{requirements_text}

# Repository Insights
{repo_insights}
"""

            # === Safe prompt trimming ===
            if len(final_prompt) > 12000:
                logging.warning("[TRIM] Final prompt is too long. Trimming to 12,000 characters.")
                final_prompt = final_prompt[:12000]

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

        # === Mode 3: Full context (Internet + Repo) ===
        logging.info("[MODE] Using document + repository + internet.")
        azure_docs = read_files_from_datalake()
        keywords = re.findall(r"\w+", summarized_requirements.lower())[:30]
        matches = [doc["text"] for doc in azure_docs if any(k in doc["text"].lower() for k in keywords)]
        repo_insights = "\n\n".join(matches[:3]) if matches else "No relevant repository content found."

        internet_data = ""
        if use_internet:
            serp_results = serpapi_search(summarized_requirements)
            for result in serp_results:
                snippet_summary = summarize_text(
                    f"{result.get('title')} - {result.get('snippet')}", 150
                )
                internet_data += f"Source: {result.get('link')}\nTitle: {result.get('title')}\nSnippet: {result.get('snippet')}\nSummary: {snippet_summary}\n\n"

        final_prompt = f"""
# Prompt
{user_prompt}

# Requirements Summary
{summarized_requirements}

# Uploaded Document
{requirements_text}

# Repository Insights
{repo_insights}

# Internet Insights
{internet_data}
"""

        # === Safe prompt trimming ===
        if len(final_prompt) > 12000:
            logging.warning("[TRIM] Final prompt is too long. Trimming to 12,000 characters.")
            final_prompt = final_prompt[:12000]

        response = openai.ChatCompletion.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "You are a Salesforce and enterprise systems expert."},
                {"role": "user", "content": final_prompt}
            ],
            max_tokens=3500,
            temperature=0.7
        )
        return response.choices[0].message.content.strip()

    except Exception as e:
        logging.error(f"[generate_comprehensive_proposal ERROR] {e}")
        return "Unable to generate a response due to an internal error."

