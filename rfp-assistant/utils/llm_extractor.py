import os
import sys
import json
import logging
import hashlib
from typing import List, Dict, Any, Optional

# Add parent directory to path to import from semantic_similarity
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from semantic_similarity import get_openai_client, OpenAISettings
from utils.prompt_loader import prompt_loader
from utils.token_utils import count_tokens, split_text_into_chunks, summarize_chunks


logger = logging.getLogger(__name__)

# Initialize OpenAI settings
openai_settings = OpenAISettings()

def extract_questions_llm(text: str, document_title: str = "RFP Document") -> List[Dict[str, Any]]:
    """
    Extract questions from an RFP document using Azure OpenAI.
    First generates a response guide, then uses that to inform the question extraction process.
    
    Args:
        text: The document text to analyze
        document_title: The title of the document
        
    Returns:
        List of extracted questions
    """
    # Create cache directory if it doesn't exist
    cache_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "cache"
    )
    os.makedirs(cache_dir, exist_ok=True)
    
    # Generate cache key based on document content hash
    cache_key = hashlib.md5(text.encode()).hexdigest()
    cache_file = os.path.join(cache_dir, f"{cache_key}_questions.json")
    
    # Check cache first
    if os.path.exists(cache_file):
        logger.info(f"Loading questions from cache: {cache_file}")
        try:
            with open(cache_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading questions from cache: {str(e)}")
    
    # Initialize OpenAI client
    client = get_openai_client()
    logger.info("Initialized Azure OpenAI client for question extraction")
    
    # Count tokens in the document
    token_count = count_tokens(text)
    logger.info(f"Document has {token_count} tokens")
    
    # First generate a response guide to inform our question extraction
    logger.info("First generating response guide to inform question extraction...")
    response_guide = create_response_guide_llm(text, document_title)
    
    # Convert response guide to a summarized format for inclusion in our prompt
    guide_sections = []
    
    # Add submission structure if available
    if 'submission_structure' in response_guide and isinstance(response_guide['submission_structure'], list):
        for section in response_guide['submission_structure']:
            if isinstance(section, dict) and 'section' in section:
                section_info = f"Section: {section['section']}"
                if 'description' in section:
                    section_info += f" - {section['description']}"
                if 'requirements' in section and isinstance(section['requirements'], list):
                    section_info += "\nRequirements:"
                    for req in section['requirements']:
                        section_info += f"\n- {req}"
                guide_sections.append(section_info)
    
    # Add evaluation criteria if available
    if 'evaluation_criteria' in response_guide:
        eval_criteria = response_guide['evaluation_criteria']
        if isinstance(eval_criteria, dict):
            guide_sections.append("Evaluation Criteria:")
            for key, value in eval_criteria.items():
                guide_sections.append(f"- {key}: {value}")
        elif isinstance(eval_criteria, list):
            guide_sections.append("Evaluation Criteria:")
            for item in eval_criteria:
                if isinstance(item, dict) and 'criterion' in item:
                    criterion_info = f"- {item['criterion']}"
                    if 'weight' in item:
                        criterion_info += f" (Weight: {item['weight']})"
                    guide_sections.append(criterion_info)
                else:
                    guide_sections.append(f"- {item}")
        else:
            guide_sections.append(f"Evaluation Criteria: {eval_criteria}")
    
    # Add compliance checklist if available
    if 'compliance_checklist' in response_guide and isinstance(response_guide['compliance_checklist'], list):
        guide_sections.append("Compliance Requirements:")
        for item in response_guide['compliance_checklist']:
            if isinstance(item, dict) and 'requirement' in item:
                guide_sections.append(f"- {item['requirement']}")
            else:
                guide_sections.append(f"- {item}")
    
    # Add content mapping if available
    if 'content_mapping' in response_guide and isinstance(response_guide['content_mapping'], dict):
        guide_sections.append("Content Mapping:")
        for section, content in response_guide['content_mapping'].items():
            guide_sections.append(f"- {section}: {content}")
    
    response_guide_summary = "\n".join(guide_sections)
    logger.info(f"Generated response guide summary with {len(guide_sections)} sections")
    
    # Get the question extraction prompt
    extraction_prompt = prompt_loader.get_filled_prompt(
        "question_extraction",
        document_title=document_title,
        document_text="[DOCUMENT_TEXT]",  # Placeholder to be replaced
        response_guide_summary="[RESPONSE_GUIDE_SUMMARY]"  # Placeholder for response guide
    )
    
    if not extraction_prompt:
        logger.error("Failed to load question extraction prompt")
        return []
    
    all_questions = []
    
    # Process document based on size
    if token_count > 110000:
        logger.info("Document exceeds context limit, using RAPTOR chunking approach")
        
        # Split into chunks
        chunks = split_text_into_chunks(text)
        
        # Process each chunk
        for i, chunk in enumerate(chunks):
            logger.info(f"Processing chunk {i+1}/{len(chunks)}")
            
            # Replace placeholders with chunk text and response guide
            system_prompt = extraction_prompt.get("system", "")
            user_prompt = extraction_prompt.get("user", "")
            user_prompt = user_prompt.replace("[DOCUMENT_TEXT]", chunk)
            user_prompt = user_prompt.replace("[RESPONSE_GUIDE_SUMMARY]", response_guide_summary)
            
            try:
                response = client.chat.completions.create(
                    model=openai_settings.MODEL_NAME,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=0.2,
                    response_format={"type": "json_object"}
                )
                
                response_content = response.choices[0].message.content
                logger.info(f"Chunk response received: {response_content[:100]}...")
                
                try:
                    chunk_result = json.loads(response_content)
                    
                    # If we got a list of questions directly
                    if isinstance(chunk_result, list):
                        all_questions.extend(chunk_result)
                    # If we got a dictionary with a 'questions' key
                    elif isinstance(chunk_result, dict) and "questions" in chunk_result:
                        all_questions.extend(chunk_result["questions"])
                    # If we got a dictionary with a 'requirements' key
                    elif isinstance(chunk_result, dict) and "requirements" in chunk_result:
                        all_questions.extend(chunk_result["requirements"])
                        logger.info(f"Detected requirements array with {len(chunk_result['requirements'])} items")
                    # If we got a single question object with any of our expected fields
                    elif isinstance(chunk_result, dict) and any(key in chunk_result for key in ["id", "text", "type", "original_text", "search_query"]):
                        all_questions.append(chunk_result)  # Add it directly
                        logger.info(f"Detected a single question object with keys: {list(chunk_result.keys())}")
                    else:
                        logger.warning(f"Unrecognized chunk response format: {chunk_result}")
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to decode JSON chunk response: {e}")
                    logger.info(f"Full chunk response content: {response_content}")
                
            except Exception as e:
                logger.error(f"Error extracting questions from chunk {i+1}: {str(e)}")
        
    else:
        logger.info("Document within context limit, processing as a single unit")
        
        # Replace placeholders with full document text and response guide
        system_prompt = extraction_prompt.get("system", "")
        user_prompt = extraction_prompt.get("user", "")
        user_prompt = user_prompt.replace("[DOCUMENT_TEXT]", text)
        user_prompt = user_prompt.replace("[RESPONSE_GUIDE_SUMMARY]", response_guide_summary)
        
        try:
            response = client.chat.completions.create(
                model=openai_settings.MODEL_NAME,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.2,
                response_format={"type": "json_object"}
            )
            
            response_content = response.choices[0].message.content
            logger.info(f"Response received: {response_content[:100]}...")
            
            try:
                result = json.loads(response_content)
                
                # If we got a list of questions directly
                if isinstance(result, list):
                    all_questions = result
                # If we got a dictionary with a 'questions' key
                elif isinstance(result, dict) and "questions" in result:
                    all_questions = result["questions"]
                # If we got a dictionary with a 'requirements' key
                elif isinstance(result, dict) and "requirements" in result:
                    all_questions = result["requirements"]
                    logger.info(f"Detected requirements array with {len(result['requirements'])} items")
                # If we got a single question object with any of our expected fields
                elif isinstance(result, dict) and any(key in result for key in ["id", "text", "type", "original_text", "search_query"]):
                    all_questions = [result]  # Wrap it in a list
                    logger.info(f"Detected a single question object with keys: {list(result.keys())}")
                # Otherwise just use an empty list
                else:
                    logger.warning(f"Unrecognized response format: {result}")
                    all_questions = []
            except json.JSONDecodeError as e:
                logger.error(f"Failed to decode JSON response: {e}")
                logger.info(f"Full response content: {response_content}")
                # Convert non-JSON response to a single question entry as fallback
                all_questions = [{
                    "id": "q1",
                    "text": "What are the key requirements in this RFP?",
                    "type": "general",
                    "section": "General",
                    "priority": "High"
                }]
                    
        except Exception as e:
            logger.error(f"Error extracting questions: {str(e)}")
    
    # Deduplicate questions
    unique_questions = []
    seen_texts = set()
    
    for q in all_questions:
        # Use either original_text or text field for deduplication
        q_text = q.get('original_text', q.get('text', ''))
        if q_text and q_text not in seen_texts:
            seen_texts.add(q_text)
            unique_questions.append(q)
    
    logger.info(f"Extracted {len(unique_questions)} unique questions/requirements")
    
    # Cache the results
    try:
        with open(cache_file, 'w') as f:
            json.dump(unique_questions, f)
        logger.info(f"Cached extracted questions to: {cache_file}")
    except Exception as e:
        logger.error(f"Error caching questions: {str(e)}")
    
    return unique_questions


def extract_metadata_llm(text: str, document_title: str = "RFP Document") -> Dict[str, Any]:
    """
    Extract metadata from an RFP document using Azure OpenAI.
    
    Args:
        text: The document text to analyze
        document_title: The title of the document
        
    Returns:
        Dictionary containing the metadata
    """
    # Create cache directory if it doesn't exist
    cache_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "cache"
    )
    os.makedirs(cache_dir, exist_ok=True)
    
    # Generate cache key based on document content hash
    cache_key = hashlib.md5(text.encode()).hexdigest()
    cache_file = os.path.join(cache_dir, f"{cache_key}_metadata.json")
    
    # Check cache first
    if os.path.exists(cache_file):
        logger.info(f"Loading metadata from cache: {cache_file}")
        try:
            with open(cache_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading metadata from cache: {str(e)}")
    
    # Initialize OpenAI client
    client = get_openai_client()
    logger.info("Initialized Azure OpenAI client for metadata extraction")
    
    # Count tokens in the document
    token_count = count_tokens(text)
    logger.info(f"Document has {token_count} tokens")
    
    # Get the metadata prompt
    metadata_prompt = prompt_loader.get_filled_prompt(
        "metadata_extraction",
        document_title=document_title,
        document_text="[DOCUMENT_TEXT]"  # Placeholder to be replaced
    )
    
    if not metadata_prompt:
        logger.error("Failed to load metadata prompt")
        return {}
    
    # Process document based on size
    if token_count > 110000:
        logger.info("Document exceeds context limit, using RAPTOR chunking approach")
        
        # Split into chunks and summarize
        chunks = split_text_into_chunks(text)
        summarized_text = "\n\n".join(summarize_chunks(chunks, client))
        
        # Replace placeholder with summarized text
        system_prompt = metadata_prompt.get("system", "")
        user_prompt = metadata_prompt.get("user", "").replace("[DOCUMENT_TEXT]", summarized_text)
    else:
        # Replace placeholder with full document text
        system_prompt = metadata_prompt.get("system", "")
        user_prompt = metadata_prompt.get("user", "").replace("[DOCUMENT_TEXT]", text)
    
    # Extract metadata
    try:
        response = client.chat.completions.create(
            model=openai_settings.MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.2,
            response_format={"type": "json_object"}
        )
        
        response_content = response.choices[0].message.content
        logger.info(f"Metadata response received: {response_content[:100]}...")
        
        try:
            metadata = json.loads(response_content)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode JSON metadata response: {e}")
            logger.info(f"Full metadata response content: {response_content}")
            # Return a basic metadata structure as fallback
            metadata = {
                "document": {
                    "title": document_title
                },
                "issuing_organization": "Not extracted due to parsing error",
                "key_dates": {}
            }
        
        # Cache the results
        try:
            with open(cache_file, 'w') as f:
                json.dump(metadata, f)
            logger.info(f"Cached extracted metadata to: {cache_file}")
        except Exception as e:
            logger.error(f"Error caching metadata: {str(e)}")
        
        return metadata
        
    except Exception as e:
        logger.error(f"Error extracting metadata: {str(e)}")
        return {}


def create_response_guide_llm(text: str, document_title: str = "RFP Document") -> Dict[str, Any]:
    """
    Create a response guide for an RFP document using Azure OpenAI.
    
    Args:
        text: The document text to analyze
        document_title: The title of the document
        
    Returns:
        Dictionary containing the response guide
    """
    # Create cache directory if it doesn't exist
    cache_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "cache"
    )
    os.makedirs(cache_dir, exist_ok=True)
    
    # Generate cache key based on document content hash
    cache_key = hashlib.md5(text.encode()).hexdigest()
    cache_file = os.path.join(cache_dir, f"{cache_key}_response_guide.json")
    
    # Check cache first
    if os.path.exists(cache_file):
        logger.info(f"Loading response guide from cache: {cache_file}")
        try:
            with open(cache_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading response guide from cache: {str(e)}")
    
    # Initialize OpenAI client
    client = get_openai_client()
    logger.info("Initialized Azure OpenAI client for response guide creation")
    
    # Count tokens in the document
    token_count = count_tokens(text)
    logger.info(f"Document has {token_count} tokens")
    
    # Get the response guide prompt
    guide_prompt = prompt_loader.get_filled_prompt(
        "response_guide",
        document_title=document_title,
        document_text="[DOCUMENT_TEXT]"  # Placeholder to be replaced
    )
    
    if not guide_prompt:
        logger.error("Failed to load response guide prompt")
        return {}
    
    # Process document based on size
    if token_count > 110000:
        logger.info("Document exceeds context limit, using RAPTOR chunking approach")
        
        # Split into chunks and summarize
        chunks = split_text_into_chunks(text)
        summarized_text = "\n\n".join(summarize_chunks(chunks, client))
        
        # Replace placeholder with summarized text
        system_prompt = guide_prompt.get("system", "")
        user_prompt = guide_prompt.get("user", "").replace("[DOCUMENT_TEXT]", summarized_text)
    else:
        # Replace placeholder with full document text
        system_prompt = guide_prompt.get("system", "")
        user_prompt = guide_prompt.get("user", "").replace("[DOCUMENT_TEXT]", text)
    
    # Create response guide
    try:
        response = client.chat.completions.create(
            model=openai_settings.MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.2,
            response_format={"type": "json_object"}
        )
        
        response_content = response.choices[0].message.content
        logger.info(f"Response guide response received: {response_content[:100]}...")
        
        try:
            guide = json.loads(response_content)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode JSON response guide: {e}")
            logger.info(f"Full response guide content: {response_content}")
            # Return a basic guide structure as fallback
            guide = {
                "submission_structure": [
                    {
                        "section": "Executive Summary",
                        "description": "Brief overview of your proposal"
                    }
                ],
                "response_format": "Standard document format",
                "note": "Failed to parse LLM response"
            }
        
        # Cache the results
        try:
            with open(cache_file, 'w') as f:
                json.dump(guide, f)
            logger.info(f"Cached response guide to: {cache_file}")
        except Exception as e:
            logger.error(f"Error caching response guide: {str(e)}")
        
        return guide
        
    except Exception as e:
        logger.error(f"Error creating response guide: {str(e)}")
        return {}

def save_as_markdown(output_dir: str, file_id: str, content_type: str, content: Any) -> str:
    """
    Save extracted content as a formatted Markdown file in the document's output directory.
    
    Args:
        output_dir: Base output directory
        file_id: Unique document identifier
        content_type: Type of content ('questions', 'metadata', 'response_guide')
        content: The content to save
        
    Returns:
        Path to the saved markdown file
    """
    # Ensure the document directory exists
    doc_dir = os.path.join(output_dir, file_id)
    os.makedirs(doc_dir, exist_ok=True)
    
    # Generate markdown based on content type
    if content_type == 'questions':
        markdown_content = generate_questions_markdown(content)
        filename = "questions.md"
    elif content_type == 'metadata':
        markdown_content = generate_metadata_markdown(content)
        filename = "metadata.md"
    elif content_type == 'response_guide':
        markdown_content = generate_response_guide_markdown(content)
        filename = "response_guide.md"
    else:
        markdown_content = f"# {content_type.title()}\n\n```json\n{json.dumps(content, indent=2)}\n```"
        filename = f"{content_type}.md"
    
    # Save to file
    file_path = os.path.join(doc_dir, filename)
    with open(file_path, 'w') as f:
        f.write(markdown_content)
    
    logger.info(f"Saved {content_type} as markdown to: {file_path}")
    return file_path

def generate_questions_markdown(questions: List[Dict[str, Any]]) -> str:
    """
    Generate formatted markdown for questions.
    
    Args:
        questions: List of extracted questions/requirements
        
    Returns:
        Formatted markdown string
    """
    md = "# Extracted Questions and Requirements\n\n"
    
    if not questions:
        return md + "*No questions or requirements were extracted.*\n"
    
    # Group questions by section
    sections = {}
    for q in questions:
        section = q.get('section', 'General')
        if section not in sections:
            sections[section] = []
        sections[section].append(q)
    
    # Generate markdown for each section
    for section, section_questions in sections.items():
        md += f"## {section}\n\n"
        
        for q in section_questions:
            q_id = q.get('id', 'unknown')
            original_text = q.get('original_text', q.get('text', 'No text provided'))
            search_query = q.get('search_query', q.get('search_question', ''))
            search_alternatives = q.get('search_alternatives', [])
            q_type = q.get('type', q.get('type', 'question'))
            q_priority = q.get('priority', 'Medium')
            q_ref = q.get('reference', '')
            response_section = q.get('response_section', '')
            tags = q.get('tags', [])
            
            # Primary display is the search query if available, otherwise original text
            display_text = search_query if search_query else original_text
            
            md += f"### {q_id}: {display_text}\n\n"
            
            # Only show original text separately if different from search query
            if original_text != search_query and original_text and search_query:
                md += f"**Original Text:** {original_text}\n\n"
            
            md += f"- **Type:** {q_type}\n"
            md += f"- **Priority:** {q_priority}\n"
            
            if q_ref:
                md += f"- **Reference:** {q_ref}\n"
            
            if response_section:
                md += f"- **Response Section:** {response_section}\n"
            
            if search_alternatives and len(search_alternatives) > 0:
                md += "\n**Search Alternatives:**\n"
                for alt in search_alternatives:
                    md += f"- {alt}\n"
            
            if tags and len(tags) > 0:
                md += "\n**Tags:** "
                md += ", ".join(tags) + "\n"
            
            md += "\n"
    
    return md

def generate_metadata_markdown(metadata: Dict[str, Any]) -> str:
    """
    Generate formatted markdown for metadata.
    
    Args:
        metadata: Dictionary of extracted metadata
        
    Returns:
        Formatted markdown string
    """
    md = "# RFP Document Metadata\n\n"
    
    if not metadata:
        return md + "*No metadata was extracted.*\n"
    
    # Document identification
    if 'document' in metadata:
        doc = metadata['document']
        md += "## Document Information\n\n"
        
        if isinstance(doc, dict):
            for key, value in doc.items():
                md += f"- **{key.replace('_', ' ').title()}:** {value}\n"
        else:
            md += f"{doc}\n"
        
        md += "\n"
    
    # Issuing organization
    if 'issuing_organization' in metadata:
        org = metadata['issuing_organization']
        md += "## Issuing Organization\n\n"
        
        if isinstance(org, dict):
            for key, value in org.items():
                md += f"- **{key.replace('_', ' ').title()}:** {value}\n"
        else:
            md += f"{org}\n"
        
        md += "\n"
    
    # Key dates
    if 'key_dates' in metadata:
        dates = metadata['key_dates']
        md += "## Key Dates\n\n"
        
        if isinstance(dates, dict):
            for key, value in dates.items():
                md += f"- **{key.replace('_', ' ').title()}:** {value}\n"
        elif isinstance(dates, list):
            for date in dates:
                if isinstance(date, dict) and 'name' in date and 'date' in date:
                    md += f"- **{date['name']}:** {date['date']}\n"
                else:
                    md += f"- {date}\n"
        else:
            md += f"{dates}\n"
        
        md += "\n"
    
    # Process other metadata sections
    for key, value in metadata.items():
        if key not in ['document', 'issuing_organization', 'key_dates']:
            md += f"## {key.replace('_', ' ').title()}\n\n"
            
            if isinstance(value, dict):
                for k, v in value.items():
                    md += f"- **{k.replace('_', ' ').title()}:** {v}\n"
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict) and 'name' in item:
                        md += f"- **{item['name']}:** {item.get('description', '')}\n"
                    else:
                        md += f"- {item}\n"
                md += "\n"
            else:
                md += f"{value}\n"
            
            md += "\n"
    
    return md

def generate_response_guide_markdown(guide: Dict[str, Any]) -> str:
    """
    Generate formatted markdown for response guide.
    
    Args:
        guide: Dictionary containing response guide information
        
    Returns:
        Formatted markdown string
    """
    md = "# RFP Response Guide\n\n"
    
    if not guide:
        return md + "*No response guide was generated.*\n"
    
    # Submission structure
    if 'submission_structure' in guide:
        structure = guide['submission_structure']
        md += "## Submission Structure\n\n"
        
        if isinstance(structure, list):
            for section in structure:
                if isinstance(section, dict):
                    section_name = section.get('section', 'Unnamed Section')
                    md += f"### {section_name}\n\n"
                    
                    if 'description' in section:
                        md += f"{section['description']}\n\n"
                    
                    if 'content_requirements' in section:
                        md += "**Content Requirements:**\n\n"
                        for req in section['content_requirements']:
                            md += f"- {req}\n"
                        md += "\n"
                else:
                    md += f"- {section}\n"
        else:
            md += f"{structure}\n\n"
    
    # Response format
    if 'response_format' in guide:
        format_info = guide['response_format']
        md += "## Response Format\n\n"
        
        if isinstance(format_info, dict):
            for key, value in format_info.items():
                md += f"### {key.replace('_', ' ').title()}\n\n"
                md += f"{value}\n\n"
        else:
            md += f"{format_info}\n\n"
    
    # Process other guide sections
    for key, value in guide.items():
        if key not in ['submission_structure', 'response_format']:
            md += f"## {key.replace('_', ' ').title()}\n\n"
            
            if isinstance(value, dict):
                for k, v in value.items():
                    md += f"### {k.replace('_', ' ').title()}\n\n"
                    md += f"{v}\n\n"
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict) and 'title' in item:
                        md += f"### {item['title']}\n\n"
                        if 'description' in item:
                            md += f"{item['description']}\n\n"
                    else:
                        md += f"- {item}\n"
                md += "\n"
            else:
                md += f"{value}\n\n"
    
    return md
