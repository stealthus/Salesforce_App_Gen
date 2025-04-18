from flask import Flask, request, send_file, jsonify, make_response, send_from_directory
from flask_cors import CORS
import os
import tempfile
import logging
import io
from fpdf import FPDF
from werkzeug.middleware.proxy_fix import ProxyFix
from azure.storage.blob import BlobServiceClient
from PyPDF2 import PdfReader
from docx import Document
from internet import generate_comprehensive_proposal

# === App Setup ===
app = Flask(__name__, static_folder="frontend/build", static_url_path="")
CORS(app)
logging.basicConfig(level=logging.INFO)

# === Azure Blob Setup ===
AZURE_STORAGE_CONNECTION_STRING = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
AZURE_BLOB_CONTAINER_NAME = os.environ.get("AZURE_BLOB_CONTAINER_NAME")
blob_service_client = BlobServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)
container_client = blob_service_client.get_container_client(AZURE_BLOB_CONTAINER_NAME)

print("AZURE_STORAGE_CONNECTION_STRING =", AZURE_STORAGE_CONNECTION_STRING)

# === Utility to fetch and read all documents from Azure Blob ===
def fetch_all_documents_from_blob():
    docs_info = []
    for blob in container_client.list_blobs():
        blob_name = blob.name
        if blob_name.endswith(".pdf") or blob_name.endswith(".docx"):
            blob_client = container_client.get_blob_client(blob_name)
            stream = blob_client.download_blob().readall()
            try:
                if blob_name.endswith(".pdf"):
                    reader = PdfReader(io.BytesIO(stream))
                    text = "\n".join([page.extract_text() for page in reader.pages if page.extract_text()])
                else:
                    doc = Document(io.BytesIO(stream))
                    text = "\n".join([p.text for p in doc.paragraphs if p.text.strip()])
                docs_info.append({"filename": blob_name, "text": text})
            except Exception as e:
                logging.error(f"[READ ERROR: {blob_name}] {e}")
    return docs_info

# === Proposal Generation Endpoint ===
@app.route("/generate", methods=["POST"])
def generate_proposal():
    try:
        user_prompt = request.form.get("prompt")
        use_internet = request.form.get("use_internet") == 'true'
        requirements_text = request.form.get("requirements") or ""

        if not user_prompt:
            return jsonify({"error": "Missing prompt"}), 400

        docs_info = fetch_all_documents_from_blob()
        if not docs_info:
            return jsonify({"error": "No valid documents found in Azure Blob Storage."}), 400

        logging.info("[DEBUG] Calling generate_comprehensive_proposal()")
        result = generate_comprehensive_proposal(requirements_text, docs_info, user_prompt, use_internet)

        # === Create PDF Response ===
        pdf_stream = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", size=12)
        for line in result.split("\n"):
            try:
                pdf.multi_cell(0, 10, line.encode("latin-1", "ignore").decode("latin-1"))
            except Exception as e:
                logging.error(f"[PDF ERROR] Could not add line to PDF: {e}")
        pdf.output(pdf_stream.name)
        pdf_stream.close()

        with open(pdf_stream.name, "rb") as f:
            pdf_bytes = f.read()
        os.unlink(pdf_stream.name)

        response = make_response(pdf_bytes)
        response.headers.set('Content-Type', 'application/pdf')
        response.headers.set('Content-Disposition', 'attachment', filename='Generated_Proposal.pdf')
        return response

    except Exception as e:
        logging.exception("Internal server error:")
        return jsonify({"error": "Internal Server Error", "details": str(e)}), 500

# === Serve React Frontend ===
@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_react(path):
    if path != "" and os.path.exists(os.path.join(app.static_folder, path)):
        return send_from_directory(app.static_folder, path)
    else:
        return send_from_directory(app.static_folder, "index.html")

# === Azure-friendly WSGI setup ===
if __name__ != "__main__":
    app.wsgi_app = ProxyFix(app.wsgi_app)

# === Local dev server ===
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    logging.info(f"[INFO] Starting Flask server on port {port}...")
    app.run(host="0.0.0.0", port=port, debug=True)
