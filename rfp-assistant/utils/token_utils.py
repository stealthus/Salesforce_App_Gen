"""
Utilities for token counting and document chunking for LLM processing.
"""
import tiktoken
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

def count_tokens(text: str, model: str = "cl100k_base") -> int:
    """
    Count the number of tokens in a text string using tiktoken.
    
    Args:
        text: The text to count tokens for
        model: The encoding model to use (default: cl100k_base for GPT-4)
        
    Returns:
        The number of tokens in the text
    """
    try:
        encoding = tiktoken.get_encoding(model)
        return len(encoding.encode(text))
    except Exception as e:
        logger.error(f"Error counting tokens: {str(e)}")
        # Fallback estimation if tiktoken fails
        return len(text) // 4  # Rough estimate: ~4 chars per token

def split_text_into_chunks(text: str, max_tokens: int = 110000, 
                           overlap_tokens: int = 1000, model: str = "cl100k_base") -> List[str]:
    """
    Split a text into chunks based on token count.
    
    Args:
        text: The text to split
        max_tokens: Maximum tokens per chunk
        overlap_tokens: Number of tokens to overlap between chunks
        model: The encoding model to use
        
    Returns:
        List of text chunks
    """
    encoding = tiktoken.get_encoding(model)
    tokens = encoding.encode(text)
    token_count = len(tokens)
    
    logger.info(f"Splitting text with {token_count} tokens into chunks of {max_tokens} tokens")
    
    # If text fits in one chunk, return it directly
    if token_count <= max_tokens:
        return [text]
    
    chunks = []
    start_idx = 0
    
    while start_idx < token_count:
        # Calculate end index for this chunk
        end_idx = min(start_idx + max_tokens, token_count)
        
        # Decode chunk tokens back to text
        chunk_tokens = tokens[start_idx:end_idx]
        chunk_text = encoding.decode(chunk_tokens)
        chunks.append(chunk_text)
        
        # Move start index for next chunk, accounting for overlap
        start_idx = end_idx - overlap_tokens
    
    logger.info(f"Split text into {len(chunks)} chunks")
    return chunks

def summarize_chunks(chunks: List[str], client, max_tokens: int = 50000) -> List[str]:
    """
    Summarize each chunk to a smaller size using the OpenAI client.
    
    Args:
        chunks: List of text chunks to summarize
        client: Azure OpenAI client
        max_tokens: Target token count for summarized chunks
        
    Returns:
        List of summarized chunks
    """
    summarized_chunks = []
    
    for i, chunk in enumerate(chunks):
        logger.info(f"Summarizing chunk {i+1}/{len(chunks)}")
        
        try:
            response = client.chat.completions.create(
                model=client.model_name,
                messages=[
                    {"role": "system", "content": "You are an expert text summarizer. Your task is to distill the provided text into a concise summary that retains the key information, requirements, questions, and structural elements. Focus on preserving information that would be relevant for responding to an RFP, including specific requirements, evaluation criteria, and submission instructions. Maintain all important details, dates, and specifications in your summary."},
                    {"role": "user", "content": f"Summarize the following text, preserving all key information, requirements, questions, and structural elements:\n\n{chunk}"}
                ],
                temperature=0.3,
                max_tokens=4000
            )
            
            summary = response.choices[0].message.content
            summarized_chunks.append(summary)
            
        except Exception as e:
            logger.error(f"Error summarizing chunk {i+1}: {str(e)}")
            # Fall back to using the original chunk if summarization fails
            summarized_chunks.append(chunk)
    
    return summarized_chunks
