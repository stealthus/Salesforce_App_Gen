from flask import Flask, request, send_file, jsonify, make_response, send_from_directory
from flask_cors import CORS
import os
import tempfile
from internet import read_docx, read_pdf, generate_comprehensive_proposal
from fpdf import FPDF
from werkzeug.middleware.proxy_fix import ProxyFix
import logging

# === App Setup ===
app = Flask(__name__, static_folder="frontend/build", static_url_path="")
CORS(app)
logging.basicConfig(level=logging.INFO)

@app.route("/generate", methods=["POST"])
def generate_proposal():
    try:
        uploaded_file = request.files.get("file")
        user_prompt = request.form.get("prompt")
        use_internet = request.form.get("use_internet") == 'true'

        if not uploaded_file or not user_prompt:
            return jsonify({"error": "Missing file or prompt"}), 400

        # === Save uploaded file temporarily
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, uploaded_file.filename)
            uploaded_file.save(file_path)

            # === Read document
            ext = os.path.splitext(uploaded_file.filename)[1].lower()
            if ext == ".docx":
                document_text = read_docx(file_path)
            elif ext == ".pdf":
                document_text = read_pdf(file_path)
            else:
                return jsonify({"error": "Unsupported file format. Upload a .docx or .pdf file."}), 400

            if not document_text.strip():
                return jsonify({"error": "The uploaded document could not be parsed or is empty."}), 400

            # === Wrap into docs_info for compatibility
            docs_info = [{"filename": uploaded_file.filename, "text": document_text}]

            logging.info("[DEBUG] Calling generate_comprehensive_proposal()")
            result = generate_comprehensive_proposal(document_text, docs_info, user_prompt, use_internet)

            # === Create response PDF
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

            # === Return the PDF file
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


# === Serve React Frontend
@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_react(path):
    if path != "" and os.path.exists(os.path.join(app.static_folder, path)):
        return send_from_directory(app.static_folder, path)
    else:
        return send_from_directory(app.static_folder, "index.html")


# === Azure-friendly WSGI setup
if __name__ != "__main__":
    app.wsgi_app = ProxyFix(app.wsgi_app)

# === Local dev server
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    logging.info(f"[INFO] Starting Flask server on port {port}...")
    app.run(host="0.0.0.0", port=port, debug=True)



