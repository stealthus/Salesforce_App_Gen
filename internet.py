import os
import openai
import pickle
from docx import Document
from PyPDF2 import PdfReader
from fpdf import FPDF
import requests
import faiss
import numpy as np
import logging

# === Logging ===
logging.basicConfig(level=logging.INFO)

# === Environment Variables ===
openai.api_key = os.environ["OPENAI_API_KEY"]
SERP_API_KEY = os.environ["SERP_API_KEY"]

# === Config ===
MODEL = "gpt-3.5-turbo"
VECTOR_DB_FILE = os.path.join("/home", "vector_db.pkl")

# === Utilities ===
def read_docx(file_path):
    doc = Document(file_path)
    return "\n".join([p.text for p in doc.paragraphs if p.text.strip()])


def read_pdf(file_path):
    reader = PdfReader(file_path)
    return "\n".join([page.extract_text() for page in reader.pages if page.extract_text()])


def summarize_text(text, max_tokens=800):
    try:
        logging.info("[OpenAI] Summarizing text...")
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
        logging.error(f"[OpenAI ERROR] {e}")
        return "Summary not available due to an error."


def serpapi_search(query, max_results=3):
    try:
        logging.info("[SERPAPI] Searching...")
        params = {
            "engine": "google",
            "q": query,
            "api_key": SERP_API_KEY
        }
        response = requests.get("https://serpapi.com/search.json", params=params).json()
        return response.get("organic_results", [])[:max_results]
    except Exception as e:
        logging.error(f"[SERPAPI ERROR] {e}")
        return []


def save_pdf(content, filename):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    for line in content.split("\n"):
        pdf.multi_cell(0, 10, line.encode("latin-1", "ignore").decode("latin-1"))
    pdf.output(filename)


def create_or_load_vector_db(docs_info):
    if os.path.exists(VECTOR_DB_FILE):
        with open(VECTOR_DB_FILE, "rb") as f:
            index, embeddings = pickle.load(f)
    else:
        texts = [doc["summary"] for doc in docs_info if "summary" in doc]
        embeddings = [openai.Embedding.create(input=t, model="text-embedding-ada-002")["data"][0]["embedding"] for t in texts]
        array = np.array(embeddings).astype("float32")
        index = faiss.IndexFlatL2(array.shape[1])
        index.add(array)
        with open(VECTOR_DB_FILE, "wb") as f:
            pickle.dump((index, embeddings), f)
    return index


def generate_comprehensive_proposal(requirements_text, docs_info, user_prompt, use_internet):
    if not use_internet:
        logging.info("[MODE] Document-only mode — no internet or vector DB used.")
        full_doc = "\n".join([doc.get("text", "") for doc in docs_info])
        final_prompt = user_prompt.replace("{{document_content}}", full_doc)

        try:
            response = openai.ChatCompletion.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant answering only based on the document."},
                    {"role": "user", "content": final_prompt}
                ],
                max_tokens=3500,
                temperature=0.7
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logging.error(f"[OpenAI ERROR - Doc Only] {e}")
            return "Unable to generate proposal based on document."
    else:
        logging.info("[MODE] Internet-enhanced mode — using summaries, SerpAPI, and vector DB.")
        summarized_requirements = summarize_text(requirements_text, 800)
        serp_results = serpapi_search(summarized_requirements)

        internet_data = ""
        for i, result in enumerate(serp_results):
            snippet_summary = summarize_text(
                f"{result['title']} - {result['snippet']} (Source: {result['link']})", 150
            )
            docs_info.append({"filename": f"SERP_{i+1}", "summary": snippet_summary})
        internet_data = "\n".join(
            [f"Source: {r['link']}\nTitle: {r['title']}\nSnippet: {r['snippet']}\n" for r in serp_results]
        )

        create_or_load_vector_db(docs_info)

        final_prompt = user_prompt.replace("{{requirements}}", summarized_requirements)\
                                  .replace("{{internet_data}}", internet_data)

        try:
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
            logging.error(f"[OpenAI Generation ERROR] {e}")
            return "Proposal generation failed."
