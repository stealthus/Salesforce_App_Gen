from flask import Flask, request, jsonify, make_response, send_from_directory, send_file
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix
from fpdf import FPDF
import os
import sys
import tempfile
import logging
import io
from internet import (
    read_files_from_datalake,
    generate_comprehensive_proposal,
    analyze_pdf_with_ai,
    read_pdf,
    read_docx
)

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
    try:
        uploaded_file = request.files.get("file")
        user_prompt = request.form.get("prompt", "")
        use_internet = request.form.get("use_internet", "false").lower() == "true"

        logger.info("[START] /generate called")
        logger.info(f"[PROMPT] Received: {user_prompt}")
        logger.info(f"[INTERNET] Enabled: {use_internet}")

        if not uploaded_file or uploaded_file.filename == "":
            return jsonify({"error": "No file uploaded"}), 400

        filename = uploaded_file.filename.lower()
        file_bytes = uploaded_file.stream.read()   # <=== FIXED: .stream.read()
        uploaded_file.stream.seek(0)               # <=== Reset stream pointer

        logger.info(f"[FILE] Uploaded: {filename} | Size: {len(file_bytes)} bytes")

        if filename.endswith(".pdf"):
            requirements_text = analyze_pdf_with_ai(io.BytesIO(file_bytes), filename)
        elif filename.endswith(".docx"):
            with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as tmp:
                tmp.write(file_bytes)
                tmp.flush()
                requirements_text = read_docx(tmp.name)
        else:
            requirements_text = file_bytes.decode("utf-8", errors="ignore")

        if not requirements_text.strip():
            logger.warning("[WARNING] Extracted document text is empty.")
        else:
            logger.info(f"[UPLOAD] Extracted {len(requirements_text)} characters from uploaded document")

        # === Get repository documents ===
        docs_info = read_files_from_datalake()
        logger.info(f"[FILES] Repository documents retrieved: {len(docs_info)}")

        # === Generate proposal ===
        final_output = generate_comprehensive_proposal(
            requirements_text=requirements_text,
            docs_info=docs_info,
            user_prompt=user_prompt,
            use_internet=use_internet
        )

        # === Create PDF ===
        pdf = FPDF()
        pdf.add_page()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.set_font("Arial", size=12)
        for line in final_output.split("\n"):
            pdf.multi_cell(0, 10, line)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_pdf:
            pdf.output(tmp_pdf.name)
            tmp_pdf.close()

            with open(tmp_pdf.name, "rb") as f:
                pdf_bytes = f.read()
            os.unlink(tmp_pdf.name)

        logger.info("[SUCCESS] Proposal PDF created and sent")
        return send_file(io.BytesIO(pdf_bytes), download_name="Generated_Proposal.pdf", as_attachment=True)

    except Exception as e:
        logger.exception("[ERROR] Failed to generate proposal")
        return jsonify({"error": "Internal server error"}), 500
    
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
    print("[INFO] Starting Flask server with latest code...")
    app.run(debug=True)
