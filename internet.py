import os
import openai
import logging
import requests
from docx import Document
from PyPDF2 import PdfReader

# === Logging ===
logging.basicConfig(level=logging.INFO)

# === Environment Variables ===
openai.api_key = os.environ.get("OPENAI_API_KEY")
SERP_API_KEY = os.environ.get("SERP_API_KEY")

# === Config ===
MODEL = "gpt-3.5-turbo"

# === Utilities ===

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


# === Proposal Logic (checkbox checked)
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


# === QA Logic (checkbox unchecked)
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


# === Main Entry Point
def generate_comprehensive_proposal(requirements_text, docs_info, user_prompt, use_internet):
    try:
        full_doc = "\n".join([doc.get("text", "") for doc in docs_info if doc.get("text")])

        if not use_internet:
            logging.info("[MODE] Internet OFF: answering strictly from document.")
            return answer_question_from_doc(full_doc, user_prompt)

        else:
            logging.info("[MODE] Internet ON: referencing document + requirements + internet.")

            summarized_requirements = summarize_text(requirements_text, 800)
            serp_results = serpapi_search(summarized_requirements)

            internet_data = ""
            for i, result in enumerate(serp_results):
                snippet_summary = summarize_text(
                    f"{result.get('title', '')} - {result.get('snippet', '')} (Source: {result.get('link', '')})",
                    150
                )
                internet_data += f"Source: {result.get('link', '')}\nTitle: {result.get('title', '')}\nSnippet: {result.get('snippet', '')}\nSummary: {snippet_summary}\n\n"

            final_prompt = user_prompt.replace("{{requirements}}", summarized_requirements)\
                                      .replace("{{internet_data}}", internet_data)\
                                      .replace("{{document_content}}", full_doc[:8000])

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

    except Exception as e:
        logging.error(f"[generate_comprehensive_proposal ERROR] {e}")
        return "Unable to generate a response due to an internal error."

