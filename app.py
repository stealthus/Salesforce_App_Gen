from flask import Flask, request, jsonify, make_response, send_file, send_from_directory
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix
from fpdf import FPDF
import os
import tempfile
import logging
from internet import read_docx, read_pdf, generate_comprehensive_proposal

# === App Setup ===
app = Flask(__name__, static_folder="frontend/build", static_url_path="")
CORS(app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger()

@app.route("/generate", methods=["POST"])
def generate_proposal():
    try:
        uploaded_file = request.files.get("file")
        user_prompt = request.form.get("prompt")
        use_internet = request.form.get("use_internet") == 'true'

        logger.info("[START] /generate called")
        logger.info(f"[PROMPT] Received: {user_prompt}")
        logger.info(f"[INTERNET] Enabled: {use_internet}")

        if not uploaded_file or not user_prompt:
            return jsonify({"error": "Missing file or prompt"}), 400

        # Save file to a temp location
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, uploaded_file.filename)
            uploaded_file.save(file_path)

            # Read uploaded file
            ext = os.path.splitext(uploaded_file.filename)[1].lower()
            if ext == ".pdf":
                document_text = read_pdf(file_path)
            elif ext == ".docx":
                document_text = read_docx(file_path)
            else:
                return jsonify({"error": "Unsupported file format. Please upload a .pdf or .docx"}), 400

            if not document_text.strip():
                return jsonify({"error": "The uploaded document appears empty or unreadable."}), 400

            # Create docs_info wrapper
            docs_info = [{"filename": uploaded_file.filename, "text": document_text}]

            logger.info(f"[UPLOAD] Parsed document length: {len(document_text)} characters")

            # Generate proposal
            result = generate_comprehensive_proposal(
                requirements_text=document_text,
                docs_info=docs_info,
                user_prompt=user_prompt,
                use_internet=use_internet
            )

            # Create PDF
            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Arial", size=12)
            pdf.set_auto_page_break(auto=True, margin=15)
            for line in result.split("\n"):
                try:
                    encoded = line.encode("latin-1", "ignore").decode("latin-1")
                    pdf.multi_cell(0, 10, encoded)
                except Exception as e:
                    logger.error(f"[PDF ERROR] Could not encode line: {e}")

            tmp_pdf_path = os.path.join(tmpdir, "Generated_Proposal.pdf")
            pdf.output(tmp_pdf_path)

            logger.info("[SUCCESS] PDF generated and ready to send")

            return send_file(tmp_pdf_path, download_name="Generated_Proposal.pdf", as_attachment=True)

    except Exception as e:
        logger.exception("[ERROR] Failed to generate proposal")
        return jsonify({"error": "Internal Server Error", "details": str(e)}), 500

# === Frontend Route ===
@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_react(path):
    target = os.path.join(app.static_folder, path)
    if path != "" and os.path.exists(target):
        return send_from_directory(app.static_folder, path)
    return send_from_directory(app.static_folder, "index.html")

# === Azure WSGI Wrapper ===
if __name__ != "__main__":
    app.wsgi_app = ProxyFix(app.wsgi_app)

# === Local Dev Server ===
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    logger.info(f"[INFO] Starting server on port {port}")
    app.run(host="0.0.0.0", port=port, debug=True)
