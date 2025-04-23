from flask import Flask, request, jsonify, make_response, send_from_directory
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix
from fpdf import FPDF
import os
import sys
import tempfile
import logging

from internet import read_files_from_datalake, generate_comprehensive_proposal, read_pdf, read_docx

# === Logging Configuration ===
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    stream=sys.stdout
)
logger = logging.getLogger()
logger.addHandler(logging.StreamHandler(sys.stdout))

# === Flask App Initialization ===
app = Flask(__name__, static_folder="frontend/build", static_url_path="")
CORS(app)

# === Main Endpoint ===
@app.route("/generate", methods=["POST"])
def generate_proposal():
    logger.info("[START] /generate called")

    try:
        user_prompt = request.form.get("prompt")
        use_internet = request.form.get("use_internet") == "true"
        uploaded_file = request.files.get("file")

        logger.info(f"[PROMPT] Received: {user_prompt}")
        logger.info(f"[INTERNET] Enabled: {use_internet}")

        if not user_prompt:
            logger.warning("[WARN] Missing prompt")
            return jsonify({"error": "Missing prompt"}), 400

        if not uploaded_file:
            logger.warning("[WARN] Missing requirements document")
            return jsonify({"error": "Missing requirements document"}), 400

        # === Extract uploaded requirements document ===
        ext = os.path.splitext(uploaded_file.filename)[1].lower()
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            uploaded_file.save(tmp.name)
            tmp.flush()
            if ext == ".pdf":
                from internet import read_pdf
                requirements_text = read_pdf(tmp.name)
            elif ext == ".docx":
                from internet import read_docx
                requirements_text = read_docx(tmp.name)
            else:
                return jsonify({"error": "Unsupported file type. Please upload a PDF or DOCX."}), 400

        if not requirements_text.strip():
            return jsonify({"error": "Uploaded requirements document is empty."}), 400

        logger.info(f"[REQUIREMENTS] Length: {len(requirements_text)} characters")

        # === Read from Azure Data Lake ===
        docs_info = read_files_from_datalake()
        if not docs_info:
            logger.warning("[DATA] No documents found in Azure Data Lake")
            return jsonify({"error": "No readable files found in Azure Data Lake."}), 400

        logger.info(f"[FILES] Documents retrieved: {len(docs_info)}")

        # === Generate Proposal ===
        result = generate_comprehensive_proposal(requirements_text, docs_info, user_prompt, use_internet)
        logger.info(f"[RESULT] Preview: {result[:300]}")

        sources_used = "\n".join([f"- {doc['filename']}" for doc in docs_info])
        result += f"\n\n---\n📁 Sources Referenced:\n{sources_used}"

        # === Create PDF ===
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", size=12)

        for line in result.split("\n"):
            try:
                encoded_line = line.encode("latin-1", "ignore").decode("latin-1")
                pdf.multi_cell(0, 10, encoded_line)
            except Exception as e:
                logger.error(f"[PDF ERROR] Encoding line failed: {e}")

        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_pdf:
            pdf.output(tmp_pdf.name)
            tmp_pdf.close()
            with open(tmp_pdf.name, "rb") as f:
                pdf_bytes = f.read()
            os.unlink(tmp_pdf.name)

        response = make_response(pdf_bytes)
        response.headers.set("Content-Type", "application/pdf")
        response.headers.set("Content-Disposition", "attachment", filename="Generated_Proposal.pdf")
        logger.info("[SUCCESS] Proposal PDF created and sent")
        return response

    except Exception as e:
        logger.exception("[ERROR] Failed to generate proposal")
        return jsonify({"error": "Internal Server Error", "details": str(e)}), 500
# === Frontend Route Handling ===
@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_react(path):
    target_path = os.path.join(app.static_folder, path)
    if path != "" and os.path.exists(target_path):
        return send_from_directory(app.static_folder, path)
    return send_from_directory(app.static_folder, "index.html")

# === Production WSGI Support ===
if __name__ != "__main__":
    app.wsgi_app = ProxyFix(app.wsgi_app)

# === Local Development Run ===
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    logger.info(f"[RUNNING] App running on http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=True)
