from flask import Flask, request, jsonify, make_response, send_from_directory
from flask_cors import CORS
import os
import tempfile
import logging
from fpdf import FPDF
from werkzeug.middleware.proxy_fix import ProxyFix

# === Your Azure and OpenAI integration logic ===
from internet import read_blob_file, generate_comprehensive_proposal

# === App Initialization ===
app = Flask(__name__, static_folder="frontend/build", static_url_path="")
CORS(app)
logging.basicConfig(level=logging.INFO)

# === Main Proposal Generation Endpoint ===
@app.route("/generate", methods=["POST"])
def generate_proposal():
    try:
        # === Collect Input ===
        filename = request.form.get("filename")
        user_prompt = request.form.get("prompt")
        use_internet = request.form.get("use_internet") == 'true'

        if not filename or not user_prompt:
            return jsonify({"error": "Missing required fields: filename or prompt"}), 400

        logging.info(f"[INFO] Reading document from Azure Blob Storage: {filename}")
        document_text = read_blob_file(filename)

        if not document_text or not document_text.strip():
            return jsonify({"error": "The document is empty or could not be parsed."}), 400

        # === Wrap into required format
        docs_info = [{"filename": filename, "text": document_text}]

        logging.info("[DEBUG] Generating proposal using OpenAI and document content...")
        result = generate_comprehensive_proposal(document_text, docs_info, user_prompt, use_internet)

        # === Create temporary PDF
        pdf_stream = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", size=12)

        for line in result.split("\n"):
            try:
                pdf.multi_cell(0, 10, line.encode("latin-1", "ignore").decode("latin-1"))
            except Exception as e:
                logging.error(f"[PDF ERROR] Skipped line due to encoding: {e}")
        pdf.output(pdf_stream.name)
        pdf_stream.close()

        # === Return as downloadable PDF
        with open(pdf_stream.name, "rb") as f:
            pdf_bytes = f.read()
        os.unlink(pdf_stream.name)

        response = make_response(pdf_bytes)
        response.headers.set('Content-Type', 'application/pdf')
        response.headers.set('Content-Disposition', 'attachment', filename='Generated_Proposal.pdf')
        return response

    except Exception as e:
        logging.exception("[ERROR] Internal server error:")
        return jsonify({"error": "Internal Server Error", "details": str(e)}), 500

# === Serve Frontend (React Build Folder) ===
@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_react(path):
    if path != "" and os.path.exists(os.path.join(app.static_folder, path)):
        return send_from_directory(app.static_folder, path)
    else:
        return send_from_directory(app.static_folder, "index.html")

# === Azure-Compatible WSGI Setup ===
if __name__ != "__main__":
    app.wsgi_app = ProxyFix(app.wsgi_app)

# === Local Development Server ===
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    logging.info(f"[INFO] Starting Flask server on port {port}...")
    app.run(host="0.0.0.0", port=port, debug=True)
