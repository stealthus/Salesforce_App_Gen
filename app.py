import os
import openai
import faiss
import numpy as np
import logging
import requests
from docx import Document
from PyPDF2 import PdfReader
from azure.storage.blob import BlobServiceClient
import io
from flask import Flask, request, send_file, jsonify, make_response, send_from_directory
from flask_cors import CORS
from fpdf import FPDF
from werkzeug.middleware.proxy_fix import ProxyFix

# === Logging ===
logging.basicConfig(level=logging.INFO)

# === Environment Variables ===
openai.api_key = os.environ.get("OPENAI_API_KEY")
SERP_API_KEY = os.environ.get("SERP_API_KEY")
AZURE_STORAGE_CONNECTION_STRING = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
BLOB_CONTAINER = "vector-db"
BLOB_NAME = "faiss_index.idx"

# === Constants ===
MODEL = "gpt-3.5-turbo"
EMBEDDING_MODEL = "text-embedding-ada-002"

# === Flask App Initialization ===
app = Flask(__name__, static_folder="frontend/build", static_url_path="")
CORS(app)

# === File Readers ===
def extract_text_from_upload(uploaded_file):
    filename = uploaded_file.filename.lower()
    file_bytes = uploaded_file.read()
    stream = io.BytesIO(file_bytes)

    if filename.endswith(".pdf"):
        reader = PdfReader(stream)
        return "\n".join([page.extract_text() for page in reader.pages if page.extract_text()])
    elif filename.endswith(".docx"):
        doc = Document(stream)
        return "\n".join([p.text for p in doc.paragraphs if p.text.strip()])
    else:
        raise ValueError("Unsupported file type")

# === Summarizer ===
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

# === Search ===
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

# === Embedding Helper ===
def get_embedding(text):
    return openai.Embedding.create(input=text, model=EMBEDDING_MODEL)["data"][0]["embedding"]

# === Azure FAISS Index Management ===
def upload_faiss_index_to_azure(index):
    blob_service = BlobServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)
    container_client = blob_service.get_container_client(BLOB_CONTAINER)
    container_client.create_container(exist_ok=True)
    index_bytes = faiss.serialize_index(index)
    container_client.upload_blob(name=BLOB_NAME, data=index_bytes, overwrite=True)
    logging.info(f"[Azure] Uploaded FAISS index to blob '{BLOB_NAME}'")

# === Proposal Generator From Upload ===
def generate_solution_from_uploaded_document(uploaded_file, use_internet):
    docs_info = []

    try:
        raw_text = extract_text_from_upload(uploaded_file)
    except Exception as e:
        return f"Error parsing uploaded file: {e}"

    summarized_text = summarize_text(raw_text)
    docs_info.append({"filename": uploaded_file.filename, "summary": summarized_text})

    internet_data = ""
    if use_internet:
        serp_results = serpapi_search(summarized_text)
        for i, result in enumerate(serp_results):
            snippet = summarize_text(f"{result['title']} - {result['snippet']} (Source: {result['link']})", 150)
            docs_info.append({"filename": f"SERP_{i+1}", "summary": snippet})
        internet_data = "\n".join([f"{r['title']} - {r['link']}: {r['snippet']}" for r in serp_results])

    embeddings = [get_embedding(d["summary"]) for d in docs_info]
    array = np.array(embeddings).astype("float32")
    index = faiss.IndexFlatL2(array.shape[1])
    index.add(array)
    upload_faiss_index_to_azure(index)

    D, I = index.search(np.array([get_embedding(summarized_text)]).astype("float32"), k=3)
    context = "\n".join([docs_info[i]["summary"] for i in I[0] if i < len(docs_info)])

    final_prompt = f"""You are an expert solution architect. Based on the following summarized requirements, provide a comprehensive technical solution.

    Summarized Requirements:
    {summarized_text}

    Context from relevant documents:
    {context}

    Additional Web Information:
    {internet_data}

    Your goal is to propose a robust, scalable, and cloud-native solution architecture tailored to the problem described.
    """

    try:
        response = openai.ChatCompletion.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "You are a solution architect."},
                {"role": "user", "content": final_prompt}
            ],
            max_tokens=3000,
            temperature=0.7
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logging.error(f"[OpenAI Generation ERROR] {e}")
        return "Proposal generation failed due to an internal error."

@app.route("/generate", methods=["POST"])
def generate_proposal():
    try:
        uploaded_file = request.files.get("file")
        use_internet = request.form.get("use_internet") == 'true'

        if not uploaded_file:
            return jsonify({"error": "Missing uploaded file"}), 400

        result = generate_solution_from_uploaded_document(uploaded_file, use_internet)

        pdf_stream = io.BytesIO()
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", size=12)
        for line in result.split("\n"):
            pdf.multi_cell(0, 10, line.encode("latin-1", "ignore").decode("latin-1"))
        pdf.output(pdf_stream)
        pdf_stream.seek(0)

        response = make_response(pdf_stream.read())
        response.headers.set('Content-Type', 'application/pdf')
        response.headers.set('Content-Disposition', 'attachment', filename='Generated_Proposal.pdf')
        return response

    except Exception as e:
        return jsonify({"error": "Internal Server Error", "details": str(e)}), 500

# React frontend catch-all route
@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_react(path):
    if path != "" and os.path.exists(os.path.join(app.static_folder, path)):
        return send_from_directory(app.static_folder, path)
    else:
        return send_from_directory(app.static_folder, "index.html")

if __name__ != "__main__":
    app.wsgi_app = ProxyFix(app.wsgi_app)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"[INFO] Starting Flask server on port {port}...")
    app.run(host="0.0.0.0", port=port, debug=True)
