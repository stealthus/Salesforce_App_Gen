import os
import openai
import pickle
from docx import Document
from PyPDF2 import PdfReader
from fpdf import FPDF
import requests
import faiss
import numpy as np

# === Config ===
openai.api_key = "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"
SERP_API_KEY = "b5b3ca2923207caee780f81704559d4644948a4fffcffa3f9bf12f3dc074a270"
MODEL = "gpt-3.5-turbo"
VECTOR_DB_FILE = "vector_db.pkl"
OUTPUT_FOLDER = "output"
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# === Utilities ===
def read_docx(file_path):
    doc = Document(file_path)
    return "\n".join([p.text for p in doc.paragraphs if p.text.strip()])

def read_pdf(file_path):
    reader = PdfReader(file_path)
    return "\n".join([page.extract_text() for page in reader.pages if page.extract_text()])

def summarize_text(text, max_tokens=800):
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

def serpapi_search(query, max_results=3):
    params = {
        "engine": "google",
        "q": query,
        "api_key": SERP_API_KEY
    }
    response = requests.get("https://serpapi.com/search.json", params=params).json()
    return response.get("organic_results", [])[:max_results]

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
        texts = [doc["summary"] for doc in docs_info]
        embeddings = [openai.Embedding.create(input=t, model="text-embedding-ada-002")["data"][0]["embedding"] for t in texts]
        array = np.array(embeddings).astype("float32")
        index = faiss.IndexFlatL2(array.shape[1])
        index.add(array)
        with open(VECTOR_DB_FILE, "wb") as f:
            pickle.dump((index, embeddings), f)
    return index

def generate_comprehensive_proposal(requirements_text, docs_info, user_prompt, use_internet):
    summarized_requirements = summarize_text(requirements_text, 800)

    internet_data = ""
    if use_internet:
        serp_results = serpapi_search(summarized_requirements)
        for i, result in enumerate(serp_results):
            snippet_summary = summarize_text(f"{result['title']} - {result['snippet']} (Source: {result['link']})", 150)
            docs_info.append({"filename": f"SERP_{i+1}", "summary": snippet_summary})
        internet_data = "\n".join([f"Source: {r['link']}\nTitle: {r['title']}\nSnippet: {r['snippet']}\n" for r in serp_results])

    # Update vector DB
    create_or_load_vector_db(docs_info)

    # Inject into user prompt
    final_prompt = user_prompt.replace("{{requirements}}", summarized_requirements)\
                              .replace("{{internet_data}}", internet_data)

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
