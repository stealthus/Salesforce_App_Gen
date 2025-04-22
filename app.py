from flask import Flask, request, jsonify, make_response, send_from_directory
from flask_cors import CORS
import os
import sys
import tempfile
from fpdf import FPDF
from werkzeug.middleware.proxy_fix import ProxyFix
import logging
from internet import read_files_from_datalake, generate_comprehensive_proposal

# === Logging Setup ===
logging.basicConfig(
    level=logging.INFO,
    stream=sys.stdout,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logging.getLogger().addHandler(logging.StreamHandler(sys.stdout))

# === App Setup ===
app = Flask(__name__, static_folder="frontend/build", static_url_path="")
CORS(app)

@app.route("/generate", methods=["POST"])
def generate_proposal():
    logging.info("[START] /generate called")

    try:
        # === Get Prompt and Internet Flag
        user_prompt = request.form.get("prompt")
        use_internet = request.form.get("use_internet") == 'true'

        logging.info(f"[PROMPT] Prompt received: {user_prompt}")
        logging.info(f"[CHECKBOX] Internet enabled: {use_internet}")

        if not user_prompt:
            logging.warning("[WARN] No prompt submitted")
            return jsonify({"error": "Missing prompt"}), 400

        # === Read from Azure Data Lake
        docs_info = read_files_from_datalake()
        logging.info(f"[FILES] Number of documents retrieved: {len(docs_info)}")

        if not docs_info:
            logging.warning("[DATA] No readable documents found")
            return jsonify({"error": "No readable files found in Azure Data Lake."}), 400

        document_text = "\n".join([doc.get("text", "") for doc in docs_info])
        logging.info(f"[DATA] Total character length from all docs: {len(document_text)}")

        result = generate_comprehensive_proposal(document_text, docs_info, user_prompt, use_internet)
        logging.info(f"[RESULT] First 300 characters of proposal: {result[:300]}")

        sources_used = "\n".join([f"- {doc['filename']}" for doc in docs_info])
        result += f"\n\n---\n📁 Sources Referenced:\n{sources_used}"

        # === Generate PDF
        pdf_stream = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", size=12)

        for line in result.split("\n"):
            try:
                pdf.multi_cell(0, 10, line.encode("latin-1", "ignore").decode("latin-1"))
            except Exception as e:
                logging.error(f"[PDF ENCODING ERROR] {e}")

        pdf.output(pdf_stream.name)
        pdf_stream.close()

        with open(pdf_stream.name, "rb") as f:
            pdf_bytes = f.read()
        os.unlink(pdf_stream.name)

        response = make_response(pdf_bytes)
        response.headers.set('Content-Type', 'application/pdf')
        response.headers.set('Content-Disposition', 'attachment', filename='Generated_Proposal.pdf')
        logging.info("[SUCCESS] PDF generated and sent")
        return response

    except Exception as e:
        logging.exception("[FATAL ERROR] Proposal generation failed")
        return jsonify({"error": "Internal Server Error", "details": str(e)}), 500

# === Serve React Frontend ===
@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_react(path):
    if path != "" and os.path.exists(os.path.join(app.static_folder, path)):
        return send_from_directory(app.static_folder, path)
    return send_from_directory(app.static_folder, "index.html")

if __name__ != "__main__":
    app.wsgi_app = ProxyFix(app.wsgi_app)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    logging.info(f"[INFO] Running locally on port {port}")
    app.run(host="0.0.0.0", port=port, debug=True)
