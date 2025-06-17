"""
Local storage service for handling document uploads and retrieval.
Stores files locally in output directory and serves as primary storage.
"""
import os
import shutil
import logging
from fastapi import UploadFile
from utils.generate_id import generate_id

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class LocalStorageService:
    def __init__(self):
        """Initialize local storage service with output directory"""
        # Base directory for all outputs
        self.output_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "outputs"
        )
        
        # Create output directory if it doesn't exist
        os.makedirs(self.output_dir, exist_ok=True)
        logger.info(f"LocalStorageService initialized with output_dir: {self.output_dir}")
        
    async def upload_file(self, file: UploadFile) -> tuple:
        """
        Store a file locally in the outputs directory
        
        Args:
            file: The uploaded file object
            
        Returns:
            tuple: (file_id, filepath) where file_id is the unique ID and filepath is the path to the stored file
        """
        # Generate a unique file ID
        file_id = generate_id()
        
        # Get file extension
        _, ext = os.path.splitext(file.filename)
        
        # Create directory for this file
        file_dir = os.path.join(self.output_dir, file_id)
        os.makedirs(file_dir, exist_ok=True)
        
        # Set the output path
        filepath = os.path.join(file_dir, f"document{ext}")
        
        logger.info(f"Saving uploaded file to: {filepath}")
        
        # Save the file
        content = await file.read()
        with open(filepath, "wb") as f:
            f.write(content)
        
        # Store metadata
        metadata_path = os.path.join(file_dir, "metadata.txt")
        with open(metadata_path, "w") as f:
            f.write(f"Original filename: {file.filename}\n")
            f.write(f"Content type: {file.content_type}\n")
            
        logger.info(f"File uploaded successfully with ID: {file_id}")
        return file_id, filepath
        
    def get_file_path(self, file_id: str) -> str:
        """
        Get the file path for a specific file ID
        
        Args:
            file_id: The unique file ID
            
        Returns:
            str: The path to the file
        """
        file_dir = os.path.join(self.output_dir, file_id)
        
        if not os.path.exists(file_dir):
            logger.error(f"File directory not found: {file_dir}")
            raise FileNotFoundError(f"No file found with ID: {file_id}")
        
        # Find the document file (there should only be one document)
        for filename in os.listdir(file_dir):
            if filename.startswith("document"):
                return os.path.join(file_dir, filename)
                
        logger.error(f"No document file found in directory: {file_dir}")
        raise FileNotFoundError(f"No document file found in directory: {file_dir}")
        
    def get_metadata(self, file_id: str) -> dict:
        """
        Get metadata for a specific file ID
        
        Args:
            file_id: The unique file ID
            
        Returns:
            dict: The metadata for the file
        """
        metadata_path = os.path.join(self.output_dir, file_id, "metadata.txt")
        
        if not os.path.exists(metadata_path):
            logger.error(f"Metadata file not found: {metadata_path}")
            return {}
            
        metadata = {}
        with open(metadata_path, "r") as f:
            for line in f:
                if ":" in line:
                    key, value = line.strip().split(":", 1)
                    metadata[key.strip()] = value.strip()
                    
        return metadata
        
# Create singleton instance
local_storage_service = LocalStorageService()
