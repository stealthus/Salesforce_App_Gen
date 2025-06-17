"""
Knowledge Base Embedder

This script reads documents from a specified directory,
converts them to text, splits them into chunks,
creates embeddings, and stores them in a vector database.

Features:
- Checkpointing to resume from failures
- Individual file processing to avoid losing work
- Progress tracking
- Error handling and retry mechanisms
"""

import os
import sys
import uuid
import logging
import json
import pickle
import time
from typing import List, Dict, Any, Optional, Set, Tuple
import glob
from pathlib import Path
import hashlib

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Import document loaders
from langchain_community.document_loaders import (
    PyPDFLoader,
    Docx2txtLoader,
    TextLoader,
    UnstructuredFileLoader
)

# Import text splitter
from langchain.text_splitter import RecursiveCharacterTextSplitter

# Import embeddings and vector store
from langchain.embeddings.base import Embeddings
from langchain_community.vectorstores import FAISS
from langchain_community.docstore.document import Document

# Import custom OpenAI settings and client
from semantic_similarity import OpenAISettings, get_openai_client, get_embedding

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("knowledge_embedding.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Initialize OpenAI settings
openai_settings = OpenAISettings()

class CustomAzureEmbeddings(Embeddings):
    """
    Custom embeddings class that implements the LangChain Embeddings interface
    and uses our existing Azure OpenAI client to generate embeddings.
    """
    
    def __init__(self):
        """Initialize with Azure OpenAI client"""
        self.client = None
        self.model = openai_settings.EMBEDDING_MODEL
        logger.info(f"Initialized CustomAzureEmbeddings with model: {self.model}")
    
    def _ensure_client(self):
        """Ensure the client is initialized"""
        if self.client is None:
            logger.info("Initializing Azure OpenAI client")
            self.client = get_openai_client()
            logger.info("Azure OpenAI client initialized successfully")
    
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for a list of documents"""
        self._ensure_client()
        
        logger.info(f"Generating embeddings for {len(texts)} documents")
        embeddings = []
        
        for i, text in enumerate(texts):
            if i > 0 and i % 10 == 0:
                logger.info(f"Processed {i}/{len(texts)} embeddings")
                
            embedding = get_embedding(self.client, text)
            embeddings.append(embedding)
        
        logger.info(f"Successfully generated {len(embeddings)} embeddings")
        return embeddings
    
    def embed_query(self, text: str) -> List[float]:
        """Generate embedding for a query text"""
        self._ensure_client()
        
        logger.info(f"Generating embedding for query: '{text[:50]}...'")
        embedding = get_embedding(self.client, text)
        logger.info("Query embedding generated successfully")
        return embedding
        
    # Make the class callable for compatibility with older FAISS versions
    def __call__(self, text: str or List[str]) -> List[float] or List[List[float]]:
        """Make the class callable for compatibility with FAISS"""
        if isinstance(text, list):
            return self.embed_documents(text)
        return self.embed_query(text)

class KnowledgeEmbedder:
    """Class to embed documents into a knowledge base with checkpointing."""

    def __init__(
        self, 
        source_dir: str, 
        output_dir: str,
        chunk_size: int = 2048,
        chunk_overlap: int = 200,
        max_retries: int = 3,
        retry_delay: int = 5
    ):
        """
        Initialize the KnowledgeEmbedder.
        
        Args:
            source_dir: Directory containing documents to embed
            output_dir: Directory to store the vector database
            chunk_size: Size of text chunks
            chunk_overlap: Overlap between chunks
            max_retries: Maximum number of retries for API calls
            retry_delay: Delay between retries in seconds
        """
        self.source_dir = source_dir
        self.output_dir = output_dir
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        
        # Create output directory if it doesn't exist
        os.makedirs(output_dir, exist_ok=True)
        
        # Create checkpoint directory
        self.checkpoint_dir = os.path.join(output_dir, "checkpoints")
        os.makedirs(self.checkpoint_dir, exist_ok=True)
        
        # Checkpoint file paths
        self.processed_files_path = os.path.join(self.checkpoint_dir, "processed_files.json")
        self.chunks_path = os.path.join(self.checkpoint_dir, "document_chunks.pkl")
        self.vector_store_path = os.path.join(output_dir, "vector_store")
        
        # Load processed files from checkpoint
        self.processed_files = self._load_processed_files()
        
        # Initialize embeddings with our custom class
        logger.info("Initializing custom Azure embeddings")
        self.embeddings = CustomAzureEmbeddings()
        
        # Initialize text splitter
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            length_function=len,
        )
        
        logger.info(f"Initialized KnowledgeEmbedder with source_dir={source_dir}, output_dir={output_dir}")
        logger.info(f"Loaded {len(self.processed_files)} previously processed files from checkpoint")

    def _load_processed_files(self) -> Set[str]:
        """Load the set of already processed files from checkpoint."""
        if os.path.exists(self.processed_files_path):
            try:
                with open(self.processed_files_path, 'r') as f:
                    return set(json.load(f))
            except Exception as e:
                logger.error(f"Error loading processed files: {str(e)}")
                return set()
        return set()

    def _save_processed_files(self) -> None:
        """Save the set of processed files to checkpoint."""
        try:
            with open(self.processed_files_path, 'w') as f:
                json.dump(list(self.processed_files), f)
        except Exception as e:
            logger.error(f"Error saving processed files: {str(e)}")

    def _load_chunks(self) -> List[Document]:
        """Load document chunks from checkpoint."""
        if os.path.exists(self.chunks_path):
            try:
                with open(self.chunks_path, 'rb') as f:
                    return pickle.load(f)
            except Exception as e:
                logger.error(f"Error loading chunks: {str(e)}")
                return []
        return []

    def _save_chunks(self, chunks: List[Document]) -> None:
        """Save document chunks to checkpoint."""
        try:
            with open(self.chunks_path, 'wb') as f:
                pickle.dump(chunks, f)
        except Exception as e:
            logger.error(f"Error saving chunks: {str(e)}")

    def _get_file_hash(self, file_path: str) -> str:
        """Get a hash of the file to detect changes."""
        try:
            file_stat = os.stat(file_path)
            return f"{file_path}_{file_stat.st_size}_{file_stat.st_mtime}"
        except Exception as e:
            logger.error(f"Error getting file hash for {file_path}: {str(e)}")
            return file_path  # Fallback to just the path

    def load_documents(self) -> List[Document]:
        """
        Load all documents from the source directory that haven't been processed yet.
        
        Returns:
            List of loaded documents
        """
        documents = []
        newly_processed_files = set()
        
        # Get all files in the source directory
        file_paths = []
        for ext in ["*.pdf", "*.docx", "*.txt", "*.md"]:
            file_paths.extend(glob.glob(os.path.join(self.source_dir, ext)))
        
        logger.info(f"Found {len(file_paths)} files in {self.source_dir}")
        logger.info(f"{len(self.processed_files)} files have already been processed")
        
        # Load each file that hasn't been processed yet
        for file_path in file_paths:
            file_hash = self._get_file_hash(file_path)
            
            if file_hash in self.processed_files:
                logger.info(f"Skipping already processed file: {file_path}")
                continue
            
            try:
                file_name = os.path.basename(file_path)
                file_ext = os.path.splitext(file_name)[1].lower()
                
                logger.info(f"Loading {file_path}")
                
                if file_ext == ".pdf":
                    loader = PyPDFLoader(file_path)
                elif file_ext == ".docx":
                    loader = Docx2txtLoader(file_path)
                elif file_ext in [".txt", ".md"]:
                    loader = TextLoader(file_path)
                else:
                    # Try with unstructured loader as fallback
                    loader = UnstructuredFileLoader(file_path)
                
                file_docs = loader.load()
                
                # Add metadata to each document
                doc_id = str(uuid.uuid4())
                for doc in file_docs:
                    doc.metadata["doc_id"] = doc_id
                    doc.metadata["doc_name"] = file_name
                    doc.metadata["source"] = file_path
                    doc.metadata["file_hash"] = file_hash
                
                documents.extend(file_docs)
                newly_processed_files.add(file_hash)
                logger.info(f"Loaded {len(file_docs)} pages/sections from {file_name}")
                
            except Exception as e:
                logger.error(f"Error loading {file_path}: {str(e)}")
        
        # Update processed files
        self.processed_files.update(newly_processed_files)
        self._save_processed_files()
        
        return documents

    def split_documents(self, documents: List[Document]) -> List[Document]:
        """
        Split documents into chunks.
        
        Args:
            documents: List of documents to split
            
        Returns:
            List of document chunks
        """
        if not documents:
            logger.info("No new documents to split")
            return []
            
        chunks = self.text_splitter.split_documents(documents)
        logger.info(f"Split {len(documents)} documents into {len(chunks)} chunks")
        return chunks

    def create_embeddings(self, chunks: List[Document]) -> FAISS:
        """
        Create embeddings for document chunks and store in vector database.
        Loads existing vector store if available and adds new chunks.
        
        Args:
            chunks: List of document chunks
            
        Returns:
            FAISS vector store
        """
        # If no new chunks, try to load existing vector store
        if not chunks:
            if os.path.exists(f"{self.vector_store_path}/index.faiss"):
                logger.info(f"No new chunks to embed, loading existing vector store from {self.vector_store_path}")
                try:
                    vector_store = FAISS.load_local(self.vector_store_path, self.embeddings)
                    return vector_store
                except Exception as e:
                    logger.error(f"Error loading existing vector store: {str(e)}")
                    # Continue with empty vector store
            return None
        
        # Check if we have an existing vector store to add to
        existing_vector_store = None
        if os.path.exists(f"{self.vector_store_path}/index.faiss"):
            try:
                logger.info(f"Loading existing vector store from {self.vector_store_path}")
                existing_vector_store = FAISS.load_local(self.vector_store_path, self.embeddings)
            except Exception as e:
                logger.error(f"Error loading existing vector store: {str(e)}")
                # Continue with new vector store
        
        # Process chunks in batches to avoid overwhelming the API
        batch_size = 20  # Adjust based on API limits
        total_chunks = len(chunks)
        vector_store = None
        
        for i in range(0, total_chunks, batch_size):
            batch_end = min(i + batch_size, total_chunks)
            batch = chunks[i:batch_end]
            
            logger.info(f"Creating embeddings for batch {i//batch_size + 1}/{(total_chunks + batch_size - 1)//batch_size} ({len(batch)} chunks)")
            
            # Try with retries
            for attempt in range(self.max_retries):
                try:
                    if vector_store is None:
                        # First batch
                        vector_store = FAISS.from_documents(batch, self.embeddings)
                    else:
                        # Add to existing store
                        vector_store.add_documents(batch)
                    
                    # Save checkpoint after each batch
                    if vector_store:
                        vector_store.save_local(f"{self.vector_store_path}_temp")
                    
                    break  # Success, exit retry loop
                except Exception as e:
                    if attempt < self.max_retries - 1:
                        logger.warning(f"Attempt {attempt+1} to create embeddings failed: {str(e)}. Retrying in {self.retry_delay} seconds...")
                        time.sleep(self.retry_delay)
                    else:
                        logger.error(f"Failed to create embeddings after {self.max_retries} attempts: {str(e)}")
                        # Continue with next batch rather than failing completely
        
        # If we have a new vector store and an existing one, merge them
        if vector_store and existing_vector_store:
            logger.info("Merging new embeddings with existing vector store")
            try:
                # Get documents from existing store and add them to new store
                existing_docs = list(existing_vector_store.docstore._dict.values())
                logger.info(f"Adding {len(existing_docs)} existing documents to new vector store")
                vector_store.add_documents(existing_docs)
            except Exception as e:
                logger.error(f"Error merging vector stores: {str(e)}")
        elif existing_vector_store and not vector_store:
            vector_store = existing_vector_store
        
        return vector_store

    def save_vector_store(self, vector_store: FAISS) -> str:
        """
        Save vector store to disk.
        
        Args:
            vector_store: FAISS vector store
            
        Returns:
            Path to the saved vector store
        """
        if not vector_store:
            logger.warning("No vector store to save")
            return None
            
        # Save to final location
        vector_store.save_local(self.vector_store_path)
        logger.info(f"Saved vector store to {self.vector_store_path}")
        
        # Clean up temporary files
        temp_path = f"{self.vector_store_path}_temp"
        if os.path.exists(f"{temp_path}/index.faiss"):
            try:
                os.remove(f"{temp_path}/index.faiss")
                os.remove(f"{temp_path}/docstore.pkl")
                os.rmdir(temp_path)
            except Exception as e:
                logger.warning(f"Error cleaning up temporary files: {str(e)}")
        
        return self.vector_store_path

    def process_all(self) -> str:
        """
        Process all documents in the source directory.
        Resumes from checkpoint if available.
        
        Returns:
            Path to the saved vector store
        """
        # Load documents (only new ones)
        new_documents = self.load_documents()
        
        # Load existing chunks from checkpoint
        existing_chunks = self._load_chunks()
        logger.info(f"Loaded {len(existing_chunks)} existing chunks from checkpoint")
        
        # Split new documents into chunks
        new_chunks = self.split_documents(new_documents)
        
        # Combine with existing chunks
        all_chunks = existing_chunks + new_chunks
        
        # Save all chunks to checkpoint
        if new_chunks:
            self._save_chunks(all_chunks)
            logger.info(f"Saved {len(all_chunks)} chunks to checkpoint")
        
        # Check if vector store already exists
        if os.path.exists(f"{self.vector_store_path}/index.faiss"):
            logger.info(f"Vector store already exists at {self.vector_store_path}, loading existing store")
            vector_store = FAISS.load_local(self.vector_store_path, self.embeddings)
            return self.vector_store_path
        
        # Create embeddings and vector store
        vector_store = self.create_embeddings(all_chunks)
        
        # Save vector store
        if vector_store:
            save_path = self.save_vector_store(vector_store)
            return save_path
        else:
            logger.warning("No vector store created or found")
            return None

def main():
    """Main function to run the embedder."""
    # Get source and output directories from command line arguments or use defaults
    source_dir = sys.argv[1] if len(sys.argv) > 1 else "/Users/u1112870/Library/CloudStorage/OneDrive-IQVIA/Ananth/Personal/Arokia_sir/Responses"
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "/Users/u1112870/Library/CloudStorage/OneDrive-IQVIA/Ananth/Personal/Arokia_sir/rfp-data"
    
    # Log the paths to ensure they're correct
    logger.info(f"Using source directory: {source_dir}")
    logger.info(f"Using output directory: {output_dir}")
    
    # Verify source directory exists and contains files
    if not os.path.exists(source_dir):
        logger.error(f"Source directory does not exist: {source_dir}")
        return
    
    files = glob.glob(os.path.join(source_dir, "*.pdf")) + glob.glob(os.path.join(source_dir, "*.docx"))
    logger.info(f"Found {len(files)} files in source directory")
    
    # Initialize and run embedder
    embedder = KnowledgeEmbedder(source_dir, output_dir)
    save_path = embedder.process_all()
    
    if save_path:
        logger.info(f"Successfully embedded documents from {source_dir} to {save_path}")
        # Print path information for easier debugging
        logger.info(f"Vector store is located at: {save_path}")
        logger.info(f"Index file: {os.path.join(save_path, 'index.faiss')}")
    else:
        logger.error(f"Failed to embed documents from {source_dir}")

if __name__ == "__main__":
    main()
