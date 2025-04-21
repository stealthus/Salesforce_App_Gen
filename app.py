from flask import Flask, request, jsonify, make_response, send_from_directory
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix
from fpdf import FPDF
import tempfile
import os
import logging

from internet import read_docx, read_pdf, generate_comprehensive_proposal

# === App Setup ===
app = Flask(__name__, static_folder="frontend/build", static_url_path="")
CORS(app)
app.wsgi_app = ProxyFix(app.wsgi_app)
logging.basicConfig(level=logging.INFO)


def parse_document(file_path: str, extension: str) -> str:
    """Parse the uploaded document based on its extension."""
    if extension == ".docx":
        return read_docx(file_path)
    elif extension == ".pdf":
        return read_pdf(file_path)
    else:
        raise ValueError("Unsupported file format. Upload a .docx or .pdf file.")


def create_pdf_from_text(text: str) -> bytes:
    """Generate a PDF file from given text and return as bytes."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as pdf_stream:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", size=12)
        for line in text.split("\n"):
            try:
                pdf.multi_cell(0, 10, line.encode("latin-1", "ignore").decode("latin-1"))
            except Exception as e:
                logging.error(f"[PDF ERROR] Could not add line to PDF: {e}")
        pdf.output(pdf_stream.name)

        with open(pdf_stream.name, "rb") as f:
            pdf_bytes = f.read()
        os.unlink(pdf_stream.name)
        return pdf_bytes


@app.route("/generate", methods=["POST"])
def generate_proposal():
    """Handle proposal generation from uploaded document."""
    try:
        uploaded_file = request.files.get("file")
        user_prompt = request.form.get("prompt")
        use_internet = request.form.get("use_internet") == "true"

        if not uploaded_file or not user_prompt:
            return jsonify({"error": "Missing file or prompt"}), 400

        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, uploaded_file.filename)
            uploaded_file.save(file_path)

            ext = os.path.splitext(uploaded_file.filename)[1].lower()
            document_text = parse_document(file_path, ext)

            if not document_text.strip():
                return jsonify({"error": "The uploaded document could not be parsed or is empty."}), 400

            requirements_docs = [{"filename": uploaded_file.filename, "text": document_text}]
            logging.info("[DEBUG] Calling generate_comprehensive_proposal()")
            result = generate_comprehensive_proposal(requirements_docs, user_prompt, use_internet)

            pdf_bytes = create_pdf_from_text(result)
            response = make_response(pdf_bytes)
            response.headers.set("Content-Type", "application/pdf")
            response.headers.set("Content-Disposition", "attachment", filename="Generated_Proposal.pdf")
            return response

    except ValueError as ve:
        return jsonify({"error": str(ve)}), 400
    except Exception as e:
        logging.exception("Internal server error:")
        return jsonify({"error": "Internal Server Error", "details": str(e)}), 500


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_react(path):
    """Serve React frontend."""
    full_path = os.path.join(app.static_folder, path)
    if path and os.path.exists(full_path):
        return send_from_directory(app.static_folder, path)
    return send_from_directory(app.static_folder, "index.html")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    logging.info(f"[INFO] Starting Flask server on port {port}...")
    app.run(host="0.0.0.0", port=port, debug=True)
