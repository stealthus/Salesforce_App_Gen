from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix
import os
import tempfile
import logging

from internet import (
    read_docx,
    read_pdf,
    generate_comprehensive_proposal,
    index_documents_to_pinecone,
    read_files_from_datalake,
    list_indexed_vector_ids
)

# === App Setup ===
app = Flask(__name__, static_folder="frontend/build", static_url_path="")
CORS(app, resources={r"/*": {"origins": "*"}})  # Adjust if needed
app.wsgi_app = ProxyFix(app.wsgi_app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("flask-app")

# === Proposal Generation Endpoint ===
@app.route("/generate", methods=["POST"])
def generate_proposal():
    try:
        uploaded_file = request.files.get("file")
        user_prompt = request.form.get("prompt")
        use_internet = request.form.get("use_internet") == 'true'

        if not uploaded_file or not user_prompt:
            return jsonify({"error": "Missing file or prompt"}), 400

        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, uploaded_file.filename)
            uploaded_file.save(file_path)

            ext = os.path.splitext(uploaded_file.filename)[1].lower()
            if ext == ".pdf":
                document_text = read_pdf(file_path)
            elif ext == ".docx":
                document_text = read_docx(file_path)
            elif ext == ".txt":
                document_text = uploaded_file.read().decode("utf-8", errors="ignore")
            else:
                return jsonify({"error": "Unsupported file format"}), 400

            if not document_text.strip():
                return jsonify({"error": "Empty document"}), 400

            docs_info = [{"filename": uploaded_file.filename, "text": document_text}]
            index_documents_to_pinecone(docs_info)

            result = generate_comprehensive_proposal(
                requirements_text=document_text,
                docs_info=docs_info,
                user_prompt=user_prompt,
                use_internet=use_internet
            )

            logger.info("[RESPONSE] Proposal sent to frontend.")
            return jsonify({"generated_text": result}), 200

    except Exception as e:
        logger.exception("[ERROR] Internal server error")
        return jsonify({"error": "Internal Server Error", "details": str(e)}), 500

# === Trigger Indexing from Azure Data Lake ===
@app.route("/triggerindex", methods=["POST"])
def trigger_index():
    api_key = request.headers.get("x-api-key")
    expected_key = os.getenv("ADMIN_API_KEY")

    if expected_key and api_key != expected_key:
        return jsonify({"error": "Unauthorized"}), 401

    try:
        read_files_from_datalake()
        return jsonify({"message": "✅ Indexing triggered from Data Lake"}), 200
    except Exception as e:
        logger.error(f"[TRIGGER ERROR] {e}")
        return jsonify({"error": str(e)}), 500

# === List Indexed Vectors (Optional Debug Route) ===
@app.route("/list-indexed", methods=["GET"])
def list_indexed_vectors():
    try:
        list_indexed_vector_ids()
        return jsonify({"message": "🧠 Vector index listing complete"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# === Health Check ===
@app.route("/healthz", methods=["GET"])
def health_check():
    return jsonify({"status": "ok"}), 200

# === React Frontend Routing ===
@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_react(path):
    target = os.path.join(app.static_folder, path)
    if path and os.path.exists(target):
        return send_from_directory(app.static_folder, path)
    return send_from_directory(app.static_folder, "index.html")

# === Run Local Dev Server ===
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    logger.info(f"[INFO] Starting Flask server on port {port}")
    app.run(host="0.0.0.0", port=port, debug=True)
