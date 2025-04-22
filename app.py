from flask import Flask, request, jsonify, make_response, send_from_directory
from flask_cors import CORS
import os
import sys
import tempfile
from fpdf import FPDF
from werkzeug.middleware.proxy_fix import ProxyFix
import logging
import openai

from internet import read_files_from_datalake

# === Constants ===
MAX_DOC_SIZE = 1_000_000  # Max characters from all docs
MAX_CHARS_PER_CHUNK = 3000
ALLOWED_EXTENSIONS = (".pdf", ".docx")

# === Logging Setup ===
logging.basicConfig(
    level=logging.INFO,
    stream=sys.stdout,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logging.getLogger().addHandler(logging.StreamHandler(sys.stdout))

# === App Setup ===
app = Flask(__name__, static_folder="frontend/build", static_url_path="")
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10 MB limit
CORS(app)

# === Utility: Chunk large text ===
def split_text_into_chunks(text, chunk_size=MAX_CHARS_PER_CHUNK):
    return [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]

# === Utility: Summarize each chunk ===
def summarize_chunks_with_openai(chunks, user_prompt):
    summaries = []
    for idx, chunk in enumerate(chunks):
        try:
            logging.info(f"[OPENAI] Processing chunk {idx + 1}/{len(chunks)}")
            prompt = (
                f"{user_prompt}\n\n---\nSection:\n{chunk}\n\nSummarize or extract insights."
            )
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=1024,
                temperature=0.7
            )
            summaries.append(response.choices[0].message.content.strip())
        except Exception as e:
            logging.error(f"[OPENAI ERROR] Chunk {idx + 1} failed: {e}")
            summaries.append(f"[ERROR] Chunk {idx + 1} could not be summarized")
    return "\n\n---\n".join(summaries)

@app.route("/generate", methods=["POST"])
def generate_proposal():
    logging.info("[START] /generate called")

    try:
        user_prompt = request.form.get("prompt")
        use_internet = request.form.get("use_internet") == 'true'

        logging.info(f"[PROMPT] Prompt: {user_prompt}")
        logging.info(f"[CHECKBOX] Internet: {use_internet}")

        if not user_prompt:
            return jsonify({"error": "Missing prompt"}), 400

        try:
            docs_info = read_files_from_datalake()
        except Exception as e:
            logging.error(f"[ERROR] Data lake read failed: {e}")
            return jsonify({"error": "Read failed", "details": str(e)}), 500

        docs_info = [doc for doc in docs_info if doc['filename'].lower().endswith(ALLOWED_EXTENSIONS)]
        if not docs_info:
            return jsonify({"error": "No supported files found"}), 400

        document_text = "\n".join([doc.get("text", "") for doc in docs_info])
        if len(document_text) > MAX_DOC_SIZE:
            return jsonify({"error": "Combined document too large"}), 400

        chunks = split_text_into_chunks(document_text)
        summarized_text = summarize_chunks_with_openai(chunks, user_prompt)

        sources = "\n".join([f"- {doc['filename']}" for doc in docs_info])
        summarized_text += f"\n\n---\n\ud83d\udcc1 Sources Referenced:\n{sources}"

        # === Generate PDF ===
        pdf_stream = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", size=12)

        line_count = 0
        for line in summarized_text.split("\n"):
            if line_count > 50:
                pdf.add_page()
                line_count = 0
            pdf.multi_cell(0, 10, line.encode("latin-1", "ignore").decode("latin-1"))
            line_count += 1

        pdf.output(pdf_stream.name)
        pdf_stream.close()

        with open(pdf_stream.name, "rb") as f:
            pdf_bytes = f.read()
        os.unlink(pdf_stream.name)

        response = make_response(pdf_bytes)
        response.headers.set('Content-Type', 'application/pdf')
        response.headers.set('Content-Disposition', 'attachment', filename='Generated_Proposal.pdf')
        logging.info("[SUCCESS] PDF created and returned")
        return response

    except Exception as e:
        logging.exception("[FATAL] Proposal generation failed")
        return jsonify({"error": "Internal Server Error", "details": str(e)}), 500

@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_react(path):
    if path != "" and os.path.exists(os.path.join(app.static_folder, path)):
        return send_from_directory(app.static_folder, path)
    return send_from_directory(app.static_folder, "index.html")

@app.route("/health")
def health():
    return "OK", 200

if __name__ != "__main__":
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    logging.info(f"[INFO] Running locally on port {port}")
    app.run(host="0.0.0.0", port=port, debug=True)
