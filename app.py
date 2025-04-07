from flask import Flask, request, send_file, jsonify, make_response, send_from_directory
from flask_cors import CORS
import os
import tempfile
from internet import read_docx, read_pdf, generate_comprehensive_proposal
from fpdf import FPDF
from werkzeug.middleware.proxy_fix import ProxyFix

# === Flask app with React frontend ===
app = Flask(
    __name__,
    static_folder="frontend/build",      # React build path
    static_url_path=""                   # Serve React from root
)
CORS(app)
app.wsgi_app = ProxyFix(app.wsgi_app)

# === React frontend serving ===
@app.route("/", methods=["GET"])
def serve_react_index():
    return send_from_directory(app.static_folder, "index.html")

@app.route("/<path:path>", methods=["GET"])
def serve_react_static(path):
    file_path = os.path.join(app.static_folder, path)
    if os.path.isfile(file_path):
        return send_from_directory(app.static_folder, path)
    else:
        return send_from_directory(app.static_folder, "index.html")

# ✅ NEW: Environment variable check route
@app.route("/check", methods=["GET"])
def check_env_vars():
    return jsonify({
        "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY", "not set"),
        "SERP_API_KEY": os.getenv("SERP_API_KEY", "not set")
    })

# === Main functionality endpoint ===
@app.route("/generate", methods=["POST"])
def generate_proposal():
    try:
        print("[DEBUG] Entered generate_proposal endpoint")

        uploaded_file = request.files.get("file")
        user_prompt = request.form.get("prompt")
        use_internet = request.form.get("use_internet") == 'true'

        print("[DEBUG] File received:", uploaded_file.filename if uploaded_file else 'None')
        print("[DEBUG] Prompt received:", user_prompt[:100] if user_prompt else 'None')
        print("[DEBUG] Use Internet:", use_internet)

        if not uploaded_file or not user_prompt:
            print("[ERROR] Missing file or prompt")
            return jsonify({"error": "Missing file or prompt"}), 400

        with tempfile.TemporaryDirectory() as tmpdir:
            print("[DEBUG] Temporary directory created")
            file_path = os.path.join(tmpdir, uploaded_file.filename)
            uploaded_file.save(file_path)
            print(f"[DEBUG] File saved to {file_path}")

            if uploaded_file.filename.lower().endswith(".docx"):
                requirements_text = read_docx(file_path)
            elif uploaded_file.filename.lower().endswith(".pdf"):
                requirements_text = read_pdf(file_path)
            else:
                print("[ERROR] Unsupported file format")
                return jsonify({"error": "Unsupported file format"}), 400

            docs_info = []

            print("[DEBUG] Calling generate_comprehensive_proposal...")
            result = generate_comprehensive_proposal(requirements_text, docs_info, user_prompt, use_internet)

            print("[INFO] Generated Result Preview:")
            print(result[:500])

            pdf_stream = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Arial", size=12)
            for line in result.split("\n"):
                pdf.multi_cell(0, 10, line.encode("latin-1", "ignore").decode("latin-1"))
            pdf.output(pdf_stream.name)
            pdf_stream.close()

            with open(pdf_stream.name, "rb") as f:
                pdf_bytes = f.read()

            os.unlink(pdf_stream.name)
            print("[INFO] PDF generated and sent as download")

            response = make_response(pdf_bytes)
            response.headers.set('Content-Type', 'application/pdf')
            response.headers.set('Content-Disposition', 'attachment', filename='Generated_Proposal.pdf')
            return response

    except Exception as e:
        print("[ERROR] Exception in /generate:", str(e))
        return jsonify({"error": "Internal Server Error", "details": str(e)}), 500


if __name__ == "__main__":
    print("[INFO] Starting Flask server with latest code...")
    app.run(debug=True)
