from flask import Flask, request, jsonify, make_response, send_from_directory
from flask_cors import CORS
import os
import tempfile
from fpdf import FPDF
from azure.storage.blob import BlobServiceClient
from werkzeug.middleware.proxy_fix import ProxyFix
import logging

from internet import generate_comprehensive_proposal, extract_text_from_pdf, extract_text_from_docx

# === App Config ===
app = Flask(__name__, static_folder="frontend/build", static_url_path="")
CORS(app)
logging.basicConfig(level=logging.INFO)

# === Azure Blob Setup ===
AZURE_CONNECTION_STRING = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
AZURE_CONTAINER_NAME = os.environ.get("AZURE_BLOB_CONTAINER_NAME")
blob_service_client = BlobServiceClient.from_connection_string(AZURE_CONNECTION_STRING)
container_client = blob_service_client.get_container_client(AZURE_CONTAINER_NAME)

@app.route("/generate", methods=["POST"])
def generate_proposal():
    try:
        filename = request.form.get("filename")
        user_prompt = request.form.get("prompt")
        use_internet = request.form.get("use_internet") == 'true'

        if not filename or not user_prompt:
            return jsonify({"error": "Missing filename or prompt"}), 400

        # === Download file from Azure Blob
        blob_client = container_client.get_blob_client(f"existing_documents/{filename}")
        blob_data = blob_client.download_blob().readall()

        # === Determine format and extract text
        ext = os.path.splitext(filename)[1].lower()
        if ext == ".pdf":
            document_text = extract_text_from_pdf(blob_data)
        elif ext == ".docx":
            document_text = extract_text_from_docx(blob_data)
        else:
            return jsonify({"error": "Unsupported file format. Use .docx or .pdf only."}), 400

        if not document_text.strip():
            return jsonify({"error": "The document appears empty or unparseable."}), 400

        docs_info = [{"filename": filename, "text": document_text}]
        result = generate_comprehensive_proposal(document_text, docs_info, user_prompt, use_internet)

        # === Create PDF from result
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

        # === Send back the generated PDF
        with open(pdf_stream.name, "rb") as f:
            pdf_bytes = f.read()
        os.unlink(pdf_stream.name)

        response = make_response(pdf_bytes)
        response.headers.set('Content-Type', 'application/pdf')
        response.headers.set('Content-Disposition', 'attachment', filename='Generated_Proposal.pdf')
        return response

    except Exception as e:
        logging.exception("Internal error during proposal generation:")
        return jsonify({"error": "Internal Server Error", "details": str(e)}), 500

# === Serve React Frontend
@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_react(path):
    if path != "" and os.path.exists(os.path.join(app.static_folder, path)):
        return send_from_directory(app.static_folder, path)
    else:
        return send_from_directory(app.static_folder, "index.html")

# === Azure WSGI compatibility
if __name__ != "__main__":
    app.wsgi_app = ProxyFix(app.wsgi_app)

# === Local Dev
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    logging.info(f"[INFO] Starting Flask server on port {port}...")
    app.run(host="0.0.0.0", port=port, debug=True)
