"""
Document processing service for RFP documents.
Handles extraction of text, questions, and metadata from RFP documents using LLM.
"""
import os
import logging
from typing import Dict, List, Any, Optional

# Import traditional text extraction for file reading
from utils.text_extraction import get_file_text

# Import LLM-based extractors
from utils.llm_extractor import (
    extract_questions_llm,
    extract_metadata_llm,
    create_response_guide_llm,
    save_as_markdown
)

# Import local storage service as primary and S3 storage as secondary
from services.local_storage import local_storage_service
from services.storage import storage_service
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

class DocumentService:
    def __init__(self):
        """Initialize document service"""
        # Cache for processed documents
        self.document_cache = {}
        
        logger.info("DocumentService initialized")
    
    async def process_document(self, file_id: str) -> Dict[str, Any]:
        """
        Process an RFP document to extract text, questions, and metadata using LLM
        
        Args:
            file_id: The unique identifier for the document
            
        Returns:
            Dict containing extracted information
        """
        logger.info(f"Processing document with file_id: {file_id}")
        
        # Check if document is already processed
        if file_id in self.document_cache:
            logger.info(f"Using cached document processing results for {file_id}")
            return self.document_cache[file_id]
        
        try:
            # Get file path from local storage
            logger.info(f"Getting file path from local storage: {file_id}")
            local_path = local_storage_service.get_file_path(file_id)
            logger.info(f"File path: {local_path}")
            
            # Get metadata from local storage
            metadata = local_storage_service.get_metadata(file_id)
            document_title = metadata.get('Original filename', os.path.basename(local_path))
            logger.info(f"Document title: {document_title}")
            
            # Extract text from document
            logger.info("Extracting text from document")
            text = get_file_text(local_path)
            
            if not text:
                logger.error(f"Failed to extract text from document: {file_id}")
                raise ValueError(f"Could not extract text from document: {file_id}")
            
            logger.info(f"Successfully extracted {len(text)} characters of text")
            
            # Extract questions using LLM
            logger.info("Extracting questions from document using LLM")
            questions = extract_questions_llm(text, document_title)
            if not isinstance(questions, list):
                logger.warning(f"Expected list of questions but got {type(questions)}. Converting to empty list.")
                questions = []
            logger.info(f"Extracted {len(questions)} questions/requirements using LLM")
            
            # Save questions as markdown
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            questions_md_path = save_as_markdown(os.path.join(base_dir, "outputs"), 
                                               file_id, "questions", questions)
            logger.info(f"Saved questions as markdown to: {questions_md_path}")
            
            # Extract metadata using LLM
            logger.info("Extracting metadata from document using LLM")
            metadata_llm = extract_metadata_llm(text, document_title)
            if not isinstance(metadata_llm, dict):
                logger.warning(f"Expected dict for metadata but got {type(metadata_llm)}. Using empty dict.")
                metadata_llm = {}
            logger.info(f"Extracted metadata using LLM: {list(metadata_llm.keys() if isinstance(metadata_llm, dict) else [])}")
            
            # Save metadata as markdown
            metadata_md_path = save_as_markdown(os.path.join(base_dir, "outputs"), 
                                              file_id, "metadata", metadata_llm)
            logger.info(f"Saved metadata as markdown to: {metadata_md_path}")
            
            # Create response guide using LLM
            logger.info("Creating response guide for document using LLM")
            response_guide = create_response_guide_llm(text, document_title)
            if not isinstance(response_guide, dict):
                logger.warning(f"Expected dict for response guide but got {type(response_guide)}. Using empty dict.")
                response_guide = {}
            logger.info(f"Created response guide using LLM: {list(response_guide.keys() if isinstance(response_guide, dict) else [])}")
            
            # Save response guide as markdown
            guide_md_path = save_as_markdown(os.path.join(base_dir, "outputs"), 
                                           file_id, "response_guide", response_guide)
            logger.info(f"Saved response guide as markdown to: {guide_md_path}")
            
            # Create result
            result = {
                "file_id": file_id,
                "document_title": document_title,
                "text": text,  # Store the full text for reference
                "text_length": len(text),
                "questions": questions,
                "metadata": metadata_llm,
                "response_guide": response_guide
            }
            
            # Cache result
            logger.info(f"Caching processing results for {file_id}")
            self.document_cache[file_id] = result
            
            logger.info(f"Document processing completed successfully for {file_id}")
            return result
        except Exception as e:
            logger.error(f"Error processing document {file_id}: {str(e)}")
            raise
        finally:
            # No need to clean up local files as they're stored in the outputs directory
            pass
    
    def get_questions(self, file_id: str) -> List[Dict[str, str]]:
        """
        Get questions extracted from a document
        
        Args:
            file_id: The unique identifier for the document
            
        Returns:
            List of extracted questions
        """
        logger.info(f"Getting questions for document: {file_id}")
        
        if file_id not in self.document_cache:
            logger.error(f"Document not found in cache: {file_id}")
            raise ValueError(f"Document not processed: {file_id}")
        
        questions = self.document_cache[file_id]["questions"]
        logger.info(f"Returning {len(questions)} questions for {file_id}")
        return questions
    
    def get_metadata(self, file_id: str) -> Dict[str, Any]:
        """
        Get metadata extracted from a document
        
        Args:
            file_id: The unique identifier for the document
            
        Returns:
            Dict of extracted metadata
        """
        logger.info(f"Getting metadata for document: {file_id}")
        
        if file_id not in self.document_cache:
            logger.error(f"Document not found in cache: {file_id}")
            raise ValueError(f"Document not processed: {file_id}")
        
        metadata = self.document_cache[file_id]["metadata"]
        if not isinstance(metadata, dict):
            logger.warning(f"Metadata is not a dictionary: {type(metadata)}. Returning empty dict.")
            return {}
        logger.info(f"Returning metadata with keys: {list(metadata.keys() if isinstance(metadata, dict) else [])}")
        return metadata
        
    def get_response_guide(self, file_id: str) -> Dict[str, Any]:
        """
        Get response guide for a document
        
        Args:
            file_id: The unique identifier for the document
            
        Returns:
            Response guide dictionary
        """
        logger.info(f"Getting response guide for document: {file_id}")
        
        if file_id not in self.document_cache:
            logger.error(f"Document not found in cache: {file_id}")
            raise ValueError(f"Document not processed: {file_id}")
        
        response_guide = self.document_cache[file_id].get("response_guide", {})
        if not isinstance(response_guide, dict):
            logger.warning(f"Response guide is not a dictionary: {type(response_guide)}. Returning empty dict.")
            return {}
        logger.info(f"Returning response guide with sections: {list(response_guide.keys() if isinstance(response_guide, dict) else [])}")
        return response_guide
    
    def get_text(self, file_id: str) -> str:
        """
        Get the full text of a document
        
        Args:
            file_id: The unique identifier for the document
            
        Returns:
            Full text of the document
        """
        logger.info(f"Getting full text for document: {file_id}")
        
        if file_id not in self.document_cache:
            logger.error(f"Document not found in cache: {file_id}")
            raise ValueError(f"Document not processed: {file_id}")
        
        text = self.document_cache[file_id]["text"]
        logger.info(f"Returning {len(text)} characters of text for {file_id}")
        return text

# Create singleton instance
document_service = DocumentService()
