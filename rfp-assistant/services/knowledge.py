"""
Knowledge service for managing the vector database and retrieval.
Uses FAISS for efficient similarity search with Azure OpenAI embeddings.
"""
import os
import time
import sys
import logging
from typing import List, Dict, Any, Optional, Union
import numpy as np
from langchain_community.vectorstores import FAISS
from langchain.embeddings.base import Embeddings
from langchain.docstore.document import Document
from dotenv import load_dotenv

# Add parent directory to path to import from semantic_similarity
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from semantic_similarity import get_openai_client, get_embedding, OpenAISettings

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Initialize OpenAI settings
openai_settings = OpenAISettings()


class AzureOpenAIEmbeddings(Embeddings):
    """
    Azure OpenAI embeddings implementation that satisfies the LangChain Embeddings interface.
    This class wraps the Azure OpenAI client and provides the embed_documents and embed_query methods
    required by LangChain's vectorstore implementations.
    """
    
    def __init__(self, azure_deployment: str = None):
        """
        Initialize the Azure OpenAI embeddings class.
        The client will be lazily initialized when needed.
        
        Args:
            azure_deployment: Optional deployment name to override the default
        """
        self.client = None
        self.model = azure_deployment or openai_settings.EMBEDDING_MODEL
        logger.info(f"Initialized AzureOpenAIEmbeddings with model: {self.model}")
    
    def _ensure_client(self):
        """
        Ensure the Azure OpenAI client is initialized.
        """
        if self.client is None:
            logger.info("Initializing Azure OpenAI client for embeddings")
            self.client = get_openai_client()
            logger.info("Azure OpenAI client initialized successfully")
    
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """
        Generate embeddings for a list of documents.
        
        Args:
            texts: List of document texts to embed
            
        Returns:
            List of embeddings, one for each text
        """
        self._ensure_client()
        
        logger.info(f"Generating embeddings for {len(texts)} documents")
        embeddings = []
        
        try:
            for i, text in enumerate(texts):
                if i > 0 and i % 10 == 0:
                    logger.info(f"Processed {i}/{len(texts)} embeddings")
                    
                embedding = get_embedding(self.client, text)
                embeddings.append(embedding)
            
            logger.info(f"Successfully generated {len(embeddings)} embeddings")
            return embeddings
        except Exception as e:
            logger.error(f"Error generating embeddings: {str(e)}")
            raise
    
    def embed_query(self, text: str) -> List[float]:
        """
        Generate embedding for a query text.
        
        Args:
            text: Query text to embed
            
        Returns:
            Embedding for the query text
        """
        self._ensure_client()
        
        logger.info(f"Generating embedding for query: '{text[:50]}...'")
        try:
            embedding = get_embedding(self.client, text)
            logger.info("Query embedding generated successfully")
            return embedding
        except Exception as e:
            logger.error(f"Error generating query embedding: {str(e)}")
            raise

class KnowledgeService:
    def __init__(self):
        """Initialize knowledge service with vector store"""
        # DIRECT HARDCODED PATH - Using the confirmed location of the vector store
        self.vector_store_path = "/Users/u1112870/Library/CloudStorage/OneDrive-IQVIA/Ananth/Personal/Arokia_sir/rfp-data/vector_store"
        
        self.embeddings = AzureOpenAIEmbeddings()
        self.vector_store = None
        self.initialized = False
        logger.info(f"Using hardcoded vector store path: {self.vector_store_path}")
        
        # Verify if the vector store exists at this location
        if os.path.exists(self.vector_store_path):
            logger.info(f"Confirmed vector store directory exists at: {self.vector_store_path}")
            if os.path.exists(os.path.join(self.vector_store_path, "index.faiss")):
                logger.info(f"Confirmed index.faiss exists in the vector store directory")
            else:
                logger.warning(f"index.faiss not found in the vector store directory!")
        else:
            logger.error(f"Vector store directory does not exist at: {self.vector_store_path}")
    
    async def initialize(self):
        """Initialize the knowledge base"""
        if self.initialized:
            logger.info("Knowledge service already initialized, skipping initialization")
            return
            
        logger.info("Initializing knowledge service...")
            
        # Check if vector store already exists
        if os.path.exists(f"{self.vector_store_path}/index.faiss"):
            try:
                logger.info(f"Loading existing vector store from {self.vector_store_path}")
                # Load existing vector store with our embeddings class
                self.vector_store = FAISS.load_local(
                    self.vector_store_path,
                    self.embeddings,
                    allow_dangerous_deserialization=True
                )
                self.initialized = True
                logger.info(f"Successfully loaded existing vector store")
                return
            except Exception as e:
                logger.error(f"Error loading vector store: {str(e)}")
                logger.info("Will not create a new vector store")
        else:
            logger.info(f"Vector store directory {self.vector_store_path} not found")
        
        logger.error("Vector store not found and will not be created")
        logger.error("Please run the embed_knowledge.sh script to create the vector store first")
        self.initialized = False
    
    async def find_relevant_content(self, query: str, k: int = 5) -> List[Dict[str, Any]]:
        """
        Find content relevant to a query
        
        Args:
            query: The query string
            k: Number of results to return
            
        Returns:
            List of relevant document chunks with metadata
        """
        logger.info(f"Searching for content relevant to query: '{query[:50]}...'")
        
        if not self.initialized:
            logger.info("Vector store not initialized, initializing now")
            await self.initialize()
            
            # If still not initialized after attempting to initialize, return empty results
            if not self.initialized:
                logger.warning("Cannot perform search: Vector store could not be initialized")
                return []
        
        try:
            # Search for relevant documents with scores
            logger.info(f"Performing similarity search with k={k}")
            try:
                # First try the similarity_search_with_score method
                docs_with_scores = self.vector_store.similarity_search_with_score(query, k=k)
                logger.info(f"Found {len(docs_with_scores)} relevant documents using similarity_search_with_score")
            except (AttributeError, NotImplementedError) as e:
                # Fall back to similarity_search with relevance scores if available
                logger.info(f"Falling back to similarity_search_with_relevance_scores: {str(e)}")
                try:
                    docs_with_scores = self.vector_store.similarity_search_with_relevance_scores(query, k=k)
                    logger.info(f"Found {len(docs_with_scores)} relevant documents using similarity_search_with_relevance_scores")
                except (AttributeError, NotImplementedError):
                    # Last resort: regular similarity search without scores
                    logger.info("Falling back to basic similarity_search without scores")
                    docs = self.vector_store.similarity_search(query, k=k)
                    # Create tuples with dummy scores
                    docs_with_scores = [(doc, 0.0) for doc in docs]
                    logger.info(f"Found {len(docs_with_scores)} relevant documents using similarity_search")
            
            # Format results
            results = []
            for doc, score in docs_with_scores:
                # Convert distance to similarity score (1 - distance)
                similarity = 1.0 - min(score, 1.0)  # Ensure score is between 0 and 1
                
                # Extract source document name from metadata
                source = "Unknown"
                if "doc_name" in doc.metadata:
                    source = doc.metadata["doc_name"]
                elif "source" in doc.metadata:
                    source = os.path.basename(doc.metadata["source"])
                
                results.append({
                    "text": doc.page_content,
                    "metadata": doc.metadata,
                    "score": similarity,
                    "source": source
                })
            
            logger.info(f"Returning {len(results)} formatted results")
            return results
        except Exception as e:
            logger.error(f"Error finding relevant content: {str(e)}")
            # Return empty results on error rather than crashing
            logger.info("Returning empty results due to error")
            return []

# Create singleton instance
knowledge_service = KnowledgeService()
