import React, { useState } from "react";
import axios from "axios";

function App() {
  const [file, setFile] = useState(null);
  const [prompt, setPrompt] = useState("");
  const [useInternet, setUseInternet] = useState(false);
  const [generatedText, setGeneratedText] = useState(""); // NEW
  const [loading, setLoading] = useState(false);

  const handleFileChange = (e) => {
    setFile(e.target.files[0]);
    setGeneratedText(""); // Clear previous output when new file selected
  };

  const handlePromptChange = (e) => {
    setPrompt(e.target.value);
  };

  const handleInternetToggle = (e) => {
    setUseInternet(e.target.checked);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();

    if (!file || !prompt) {
      alert("Please upload a file and enter a prompt.");
      return;
    }

    const formData = new FormData();
    formData.append("file", file);
    formData.append("prompt", prompt);
    formData.append("use_internet", useInternet);

    setLoading(true);
    try {
      const response = await axios.post("/generate", formData); 
      // ✅ No headers manually, no blob
      // ✅ Backend returns JSON { "generated_text": "..." }

      setGeneratedText(response.data.generated_text); // Save text
    } catch (error) {
      console.error("Error generating proposal:", error);
      alert("Something went wrong. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ maxWidth: "700px", margin: "40px auto", fontFamily: "Arial, sans-serif" }}>
      <h3>📄 AI-based Proposal Generator</h3>

      <form onSubmit={handleSubmit}>
        <div style={{ marginBottom: "20px" }}>
          <label><strong>Upload Requirements Document</strong></label><br />
          <input
            type="file"
            accept=".pdf,.docx"
            onChange={handleFileChange}
            required
          />
          <small style={{ color: "#555" }}>Accepted formats: .pdf, .docx</small>
        </div>

        <div style={{ marginBottom: "20px" }}>
          <label><strong>Enter Your Prompt</strong></label><br />
          <textarea
            rows={10}
            style={{ width: "100%", padding: "10px", fontSize: "14px" }}
            placeholder="Describe what you want the AI to generate using your uploaded document and internet context. Use {{requirements}} and {{internet_data}} if needed."
            value={prompt}
            onChange={handlePromptChange}
            required
          />
        </div>

        <div style={{ marginBottom: "20px" }}>
          <input
            type="checkbox"
            id="useInternet"
            checked={useInternet}
            onChange={handleInternetToggle}
          />
          <label htmlFor="useInternet" style={{ marginLeft: "8px" }}>
            Use Internet Search
          </label>
        </div>

        <button
          type="submit"
          disabled={loading}
          style={{
            backgroundColor: loading ? "#888" : "#007bff",
            color: "white",
            padding: "10px 20px",
            border: "none",
            borderRadius: "5px",
            cursor: loading ? "not-allowed" : "pointer",
          }}
        >
          {loading ? "Generating Proposal..." : "Generate Proposal"}
        </button>
      </form>

      {/* Show generated text */}
      {generatedText && (
        <div style={{ marginTop: "30px" }}>
          <h4>✅ Your Generated Proposal:</h4>
          <div
            style={{
              background: "#f9f9f9",
              padding: "20px",
              borderRadius: "5px",
              whiteSpace: "pre-wrap",
              lineHeight: "1.6",
              fontSize: "16px",
              color: "#333",
              boxShadow: "0 2px 8px rgba(0, 0, 0, 0.1)",
            }}
          >
            {generatedText}
          </div>
        </div>
      )}
    </div>
  );
}

export default App;
