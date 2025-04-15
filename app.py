from flask import Flask, request, jsonify, make_response, send_from_directory
from flask_cors import CORS
import os
import tempfile
import logging
from fpdf import FPDF
from werkzeug.middleware.proxy_fix import ProxyFix

# Import updated logic
from internet import list_blob_files, read_blob_file, generate_comprehensive_proposal

# === App Setup ===
app = Flask(__name__, static_folder="frontend/build", static_url_path="")
CORS(app)
logging.basicConfig(level=logging.INFO)

@app.route("/generate", methods=["POST"])
def generate_proposal():
    try:
        # Only prompt and internet toggle are expected
        user_prompt = request.form.get("prompt")
        use_internet = request.form.get("use_internet") == 'true'

        if not user_prompt:
            return jsonify({"error": "Missing prompt"}), 400

        logging.info("[INFO] Fetching all documents from Azure Blob Storage...")
        filenames = list_blob_files()
        if not filenames:
            return jsonify({"error": "No documents found in Azure Blob Storage."}), 400

        docs_info = []
        for name in filenames:
            text = read_blob_file(name)
            if text.strip():
                docs_info.append({"filename": name, "text": text})
            else:
                logging.warning(f"[WARN] Skipped empty or unreadable file: {name}")

        if not docs_info:
            return jsonify({"error": "No valid document content found."}), 400

        full_text = "\n".join([doc["text"] for doc in docs_info])

        logging.info("[DEBUG] Calling generate_comprehensive_proposal() across all documents...")
        result = generate_comprehensive_proposal(full_text, docs_info, user_prompt, use_internet)

        # === Create PDF
        pdf_stream = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", size=12)
        for line in result.split("\n"):
            try:
                pdf.multi_cell(0, 10, line.encode("latin-1", "ignore").decode("latin-1"))
            except Exception as e:
                logging.error(f"[PDF ERROR] Skipped line: {e}")
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
        logging.exception("[ERROR] Internal server error:")
        return jsonify({"error": "Internal Server Error", "details": str(e)}), 500

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
    logging.info(f"[INFO] Starting Flask server on port {port}...")
    app.run(host="0.0.0.0", port=port, debug=True)
