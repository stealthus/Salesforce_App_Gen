from flask import Flask, request, jsonify, make_response, send_from_directory
from flask_cors import CORS
import os
import tempfile
from fpdf import FPDF
from werkzeug.middleware.proxy_fix import ProxyFix
import logging

from internet import read_files_from_datalake, generate_comprehensive_proposal

# === App Setup ===
app = Flask(__name__, static_folder="frontend/build", static_url_path="")
CORS(app)
logging.basicConfig(level=logging.INFO)


@app.route("/generate", methods=["POST"])
def generate_proposal():
    try:
        # === Parse Input ===
        user_prompt = request.form.get("prompt")
        use_internet = request.form.get("use_internet") == 'true'

        if not user_prompt:
            return jsonify({"error": "Missing prompt"}), 400

        # === Load Documents from Data Lake ===
        docs_info = read_files_from_datalake()
        if not docs_info:
            return jsonify({"error": "No readable PDF/DOCX files found in Azure Data Lake."}), 400

        document_text = "\n".join([doc.get("text", "") for doc in docs_info])
        result = generate_comprehensive_proposal(document_text, docs_info, user_prompt, use_internet)

        # === Append Sources Used ===
        sources_used = "\n".join([f"- {doc['filename']}" for doc in docs_info])
        result += f"\n\n---\n📁 Sources Referenced:\n{sources_used}"

        # === Generate PDF from Result ===
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

        # === Return PDF to Client ===
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
    return send_from_directory(app.static_folder, "index.html")


# === Azure WSGI Setup ===
if __name__ != "__main__":
    app.wsgi_app = ProxyFix(app.wsgi_app)

# === Local Dev Server ===
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    logging.info(f"[INFO] Starting Flask server on port {port}...")
    app.run(host="0.0.0.0", port=port, debug=True)
