"""
RFP Response Assistant - FastAPI Application
Main entry point for the RFP Response Assistant application.
"""
import os
from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import uvicorn
from dotenv import load_dotenv
import json
import uuid

# Import services
from services.local_storage import local_storage_service
from services.storage import storage_service  # Keep for backward compatibility
from services.document import document_service
from services.knowledge import knowledge_service
from services.response import response_service

# Load environment variables
load_dotenv()

# Create FastAPI app
app = FastAPI(
    title="RFP Response Assistant",
    description="AI-powered tool for generating RFP responses",
    version="0.1.0"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Pydantic models
class Question(BaseModel):
    id: str
    text: str
    type: Optional[str] = None
    section: Optional[str] = None
    search_query: Optional[str] = None
    original_text: Optional[str] = None

class ResponseRequest(BaseModel):
    file_key: str
    questions: List[Dict[str, Any]]

class Response(BaseModel):
    question_id: str
    question_text: str
    response_text: str
    sources: List[Dict[str, Any]]

class ResponseList(BaseModel):
    file_key: str
    responses: List[Dict[str, Any]]
    
class ChatRequest(BaseModel):
    message: str

# New model classes for enhanced features
class ResponseCacheRequest(BaseModel):
    file_key: str
    question_id: str
    response: Dict[str, Any]

class CreateQuestionRequest(BaseModel):
    file_key: str
    section: str
    text: str

class FinalResponseRequest(BaseModel):
    file_key: str

# Background task to initialize knowledge service
async def init_knowledge_service():
    await knowledge_service.initialize()

# Routes
@app.on_event("startup")
async def startup_event():
    # Initialize knowledge service
    background_tasks = BackgroundTasks()
    background_tasks.add_task(init_knowledge_service)

@app.get("/", response_class=HTMLResponse)
async def read_root():
    """Serve the main application page"""
    with open("static/index.html", "r") as f:
        return f.read()

@app.post("/api/upload")
async def upload_rfp(file: UploadFile = File(...), background_tasks: BackgroundTasks = None):
    """
    Upload an RFP document and process it
    
    Args:
        file: The RFP document file
        
    Returns:
        Dict containing file information and extracted questions
    """
    try:
        # Check file type
        if not file.filename.lower().endswith(('.pdf', '.docx')):
            raise HTTPException(status_code=400, detail="Only PDF and DOCX files are supported")
        
        # Store file locally instead of uploading to S3
        file_id, local_path = await local_storage_service.upload_file(file)
        
        # Process document
        result = await document_service.process_document(file_id)
        
        # Note: We no longer add RFP documents to the knowledge base
        # as they are client questions, not our knowledge
        
        return {
            "file_id": file_id,
            "filename": file.filename,
            "questions_count": len(result["questions"]),
            "document_title": result["document_title"],
            "text_length": result["text_length"]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/questions/{file_id}")
async def get_questions(file_id: str):
    """
    Get questions extracted from an RFP document
    
    Args:
        file_id: The unique identifier for the document
        
    Returns:
        List of extracted questions
    """
    try:
        questions = document_service.get_questions(file_id)
        return {"questions": questions}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/metadata/{file_id}")
async def get_metadata(file_id: str):
    """
    Get detailed metadata extracted from an RFP document
    
    Args:
        file_id: The unique identifier for the document
        
    Returns:
        Dict of extracted metadata
    """
    try:
        metadata = document_service.get_metadata(file_id)
        return {"metadata": metadata}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/response-guide/{file_id}")
async def get_response_guide(file_id: str):
    """
    Get response guide for an RFP document
    
    Args:
        file_id: The unique identifier for the document
        
    Returns:
        Response guide with structured information for preparing a response
    """
    try:
        response_guide = document_service.get_response_guide(file_id)
        return {"response_guide": response_guide}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/chat")
async def chat(request: ChatRequest):
    """
    Generate a response to a direct chat query about the knowledge base
    
    Args:
        request: The chat request containing the user's message
        
    Returns:
        Dict containing the generated response and knowledge sources
    """
    try:
        # Validate the request
        if not request.message.strip():
            raise HTTPException(status_code=400, detail="Message cannot be empty")
            
        # Generate a response to the chat query
        response = await response_service.generate_chat_response(request.message)
        
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/generate")
async def generate_responses(request: ResponseRequest):
    """
    Generate responses for RFP questions
    
    Args:
        request: The response generation request
        
    Returns:
        List of generated responses
    """
    try:
        print(f"Received generate request for file: {request.file_key} with {len(request.questions)} questions")
        print(f"First question sample: {request.questions[0] if request.questions else 'No questions'}")
        
        responses = []
        
        for i, question in enumerate(request.questions):
            print(f"Processing question {i+1}/{len(request.questions)}: {question.get('id', 'unknown')}")
            
            # Determine which text field to use for search
            question_text = question.get('search_query') or question.get('original_text') or question.get('text', '')
            print(f"Using question text for search: {question_text[:100]}...")
            
            # Find relevant knowledge
            print(f"Finding relevant knowledge for question {i+1}")
            knowledge = await knowledge_service.find_relevant_content(question_text)
            print(f"Found {len(knowledge)} knowledge items for question {i+1}")
            
            # Generate response
            print(f"Generating response for question {i+1}")
            response = await response_service.generate_response(question, knowledge)
            print(f"Response generated successfully for question {i+1}")
            
            responses.append(response)
        
        print(f"Successfully generated {len(responses)} responses")
        # Log the response structure for debugging - with safety checks
        if responses and len(responses) > 0 and responses[0] is not None:
            print(f"Response structure sample: {responses[0].keys() if hasattr(responses[0], 'keys') else 'Not a dictionary'}")
        else:
            print("Warning: Response is None or empty")
            # Filter out None values to prevent errors
            responses = [r for r in responses if r is not None]
            if not responses:
                # Add a fallback response if all responses are None
                responses = [{
                    "question_id": "unknown",
                    "question_text": "unknown",
                    "response_text": "Sorry, there was an error generating the response. Please try again.",
                    "sources": []
                }]
        
        return {"responses": responses}
    except Exception as e:
        import traceback
        print(f"Error generating responses: {str(e)}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/export")
async def export_document(response_list: ResponseList):
    """
    Export responses as a document
    
    Args:
        response_list: The list of responses to export
        
    Returns:
        Document information
    """
    try:
        document = await response_service.create_document(response_list.responses)
        return document
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# New endpoints for enhanced features
@app.post("/api/cache-response")
async def cache_response(request: ResponseCacheRequest):
    """
    Cache a generated response for later use
    
    Args:
        request: Response cache request with file_key, question_id, and response
        
    Returns:
        Dictionary with status
    """
    try:
        file_key = request.file_key
        question_id = request.question_id
        response = request.response
        
        # Use the outputs directory structure
        output_dir = os.path.join("outputs", file_key)
        os.makedirs(output_dir, exist_ok=True)
        
        # Load existing responses or create new
        response_file = os.path.join(output_dir, "responses.json")
        responses = {}
        if os.path.exists(response_file):
            with open(response_file, "r") as f:
                responses = json.load(f)
        
        # Add/update response
        responses[question_id] = response
        
        # Save back
        with open(response_file, "w") as f:
            json.dump(responses, f)
        
        # Generate markdown version
        responses_md = os.path.join(output_dir, "responses.md")
        with open(responses_md, "w") as f:
            f.write("# Generated Responses\n\n")
            for qid, resp in responses.items():
                f.write(f"## Question: {resp.get('question_text', 'Unknown')}\n\n")
                f.write(f"{resp.get('response_text', 'No response generated')}\n\n")
                f.write("---\n\n")
        
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to cache response: {str(e)}")

@app.post("/api/create-question")
async def create_question(request: CreateQuestionRequest):
    """
    Create a custom question for a section
    
    Args:
        request: Create question request with file_key, section, and text
        
    Returns:
        Dictionary with the created question
    """
    try:
        file_key = request.file_key
        section = request.section
        text = request.text
        
        # Create a new question object
        question = {
            "id": str(uuid.uuid4()),
            "text": text,
            "section": section,
            "response_section": section,
            "type": "Custom",
            "search_query": text
        }
        
        # Add to questions.json if it exists
        questions_file = os.path.join("data", "cache", file_key, "questions.json")
        if os.path.exists(questions_file):
            with open(questions_file, "r") as f:
                questions_data = json.load(f)
                
            if "questions" in questions_data and isinstance(questions_data["questions"], list):
                questions_data["questions"].append(question)
                
                with open(questions_file, "w") as f:
                    json.dump(questions_data, f)
        
        return {"status": "success", "question": question}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create question: {str(e)}")

@app.post("/api/create-final-response")
async def create_final_response(request: FinalResponseRequest):
    """
    Create a final comprehensive response document
    
    Args:
        request: Final response request with file_key
        
    Returns:
        Dictionary with status and file_path
    """
    try:
        print(f"Creating final response for file key: {request.file_key}")
        file_key = request.file_key
        
        # Use cache dir for metadata and guide
        cache_dir = os.path.join("data", "cache", file_key)
        
        # Use outputs dir for responses and final response
        output_dir = os.path.join("outputs", file_key)
        os.makedirs(output_dir, exist_ok=True)
        
        # Get response guide - check multiple locations
        guide_md_cache = os.path.join(cache_dir, "response_guide.md")
        guide_json_cache = os.path.join(cache_dir, "response_guide.json")
        guide_md_output = os.path.join(output_dir, "response_guide.md")
        
        # Check all possible locations
        if os.path.exists(guide_md_cache):                                # Check MD in cache
            with open(guide_md_cache, "r") as f:
                guide_text = f.read()
                guide = {"content": guide_text}
        elif os.path.exists(guide_json_cache):                           # Check JSON in cache
            with open(guide_json_cache, "r") as f:
                guide = json.load(f)
        elif os.path.exists(guide_md_output):                            # Check MD in output dir
            with open(guide_md_output, "r") as f:
                guide_text = f.read()
                guide = {"content": guide_text}
        else:
            # If no guide found, create a minimal one from metadata if available
            if os.path.exists(os.path.join(cache_dir, "metadata.json")):
                with open(os.path.join(cache_dir, "metadata.json"), "r") as f:
                    metadata = json.load(f)
                    if "sections" in metadata and metadata["sections"]:
                        guide = {"content": "# Response Structure\n\n" + "\n".join([f"## {s}" for s in metadata["sections"]])}
                        # No need to raise exception
                    else:
                        raise HTTPException(status_code=404, detail="Response guide not found and no sections in metadata")
            else:
                raise HTTPException(status_code=404, detail="Response guide not found")
        
        # Get responses from outputs directory
        responses_md_path = os.path.join(output_dir, "responses.md")
        responses_json_path = os.path.join(output_dir, "responses.json")
        
        responses_text = ""
        responses = {}
        
        # Get markdown responses if available
        if os.path.exists(responses_md_path):
            with open(responses_md_path, "r") as f:
                responses_text = f.read()
        
        # Get JSON responses for metadata
        if os.path.exists(responses_json_path):
            with open(responses_json_path, "r") as f:
                responses = json.load(f)
        
        # Use a template if no responses exist (warning instead of error)
        if not responses and not responses_text:
            print(f"WARNING: No response files found for {file_key}, using template")
            responses_text = """# Generated Responses

This section would typically contain responses to the questions in the RFP.

*Note: No responses have been generated yet. You can generate responses by selecting questions from the list and clicking 'Generate Response' for each.*

---

This is a preliminary document structure based on the response guide."""
            # Don't write this to disk as it's just a temporary template
        
        # Get metadata for context
        metadata_path = os.path.join(cache_dir, "metadata.json")
        metadata = {}
        if os.path.exists(metadata_path):
            with open(metadata_path, "r") as f:
                metadata = json.load(f)
        
        # Create final response with fallback
        try:
            # Try using the response service
            final_response = await response_service.generate_final_response(
                file_key=file_key,
                guide=guide,
                responses=responses,
                metadata=metadata,
                responses_text=responses_text
            )
        except Exception as e:
            # Fallback to simple combination
            final_response = f"# Final RFP Response\n\n"
            
            if "content" in guide:
                final_response += f"## Response Structure\n{guide['content']}\n\n"
            
            if responses_text:
                final_response += f"## Generated Responses\n{responses_text}"
            else:
                # Format responses from JSON if MD not available
                final_response += "## Generated Responses\n\n"
                for q_id, resp in responses.items():
                    question = resp.get("question_text", "Unknown Question")
                    answer = resp.get("response_text", "No response")
                    final_response += f"### {question}\n\n{answer}\n\n---\n\n"
        
        # Save the result to outputs directory
        output_path = os.path.join(output_dir, "final_response.md")
        with open(output_path, "w") as f:
            f.write(final_response)
        
        # Return the path relative to the outputs directory
        return {"status": "success", "file_path": f"{file_key}/final_response.md"}
    except Exception as e:
        # Log the error for debugging
        print(f"ERROR - Failed to create final response: {str(e)}")
        
        # Create a more specific error message
        error_message = str(e)
        if not responses and not responses_text:
            # Provide a more helpful error message with workflow guidance
            raise HTTPException(
                status_code=404, 
                detail="No responses found. Please generate individual responses to questions first by selecting questions from the list and clicking 'Generate Response' for each."
            )
        elif "Response guide not found" in error_message:
            raise HTTPException(status_code=404, detail="Response guide not found. Please process the document first.")
        elif "OpenAI" in error_message or "Azure" in error_message:
            raise HTTPException(status_code=500, detail="AI service error. Please check your API credentials.")
        else:
            raise HTTPException(status_code=500, detail=f"Failed to create final response: {str(e)}")


@app.get("/api/download/{file_key}/{filename}")
async def download_file(file_key: str, filename: str):
    """
    Download a generated file
    
    Args:
        file_key: The document ID
        filename: The filename to download
        
    Returns:
        The file for download
    """
    try:
        # Check the outputs directory first
        file_path = os.path.join("outputs", file_key, filename)
        
        # If not found in outputs, check the cache directory
        if not os.path.exists(file_path):
            file_path = os.path.join("data", "cache", file_key, filename)
            
        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail=f"File {filename} not found")
        
        return FileResponse(
            path=file_path,
            filename=filename,
            media_type="text/markdown"
        )
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=f"Failed to download file: {str(e)}")

# Simple diagnostic endpoint for debugging file paths
@app.get("/api/check-paths/{file_key}")
async def check_paths(file_key: str):
    """Simple path checking endpoint"""
    try:
        # Check both cache and outputs directories
        cache_dir = os.path.join("data", "cache", file_key)
        output_dir = os.path.join("outputs", file_key)
        
        # Get lists of files in both directories
        cache_files = []
        if os.path.exists(cache_dir):
            cache_files = os.listdir(cache_dir)
            
        output_files = []
        if os.path.exists(output_dir):
            output_files = os.listdir(output_dir)
        
        return {
            "file_key": file_key,
            "cache_dir_exists": os.path.exists(cache_dir),
            "output_dir_exists": os.path.exists(output_dir),
            "cache_files": cache_files,
            "output_files": output_files
        }
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8001, reload=True)
