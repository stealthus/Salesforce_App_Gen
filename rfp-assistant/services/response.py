"""
Response generation service for RFP questions.
Uses Azure OpenAI to generate responses based on retrieved knowledge.
"""
import os
import sys
import logging
from typing import List, Dict, Any, Optional
import json
import time
from dotenv import load_dotenv
from services.knowledge import knowledge_service
from utils.prompt_loader import prompt_loader

# Add parent directory to path to import from semantic_similarity
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from semantic_similarity import get_openai_client, OpenAISettings

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Initialize OpenAI settings
openai_settings = OpenAISettings()

class ResponseService:
    def __init__(self):
        """Initialize response service"""
        self.model = os.getenv("RESPONSE_MODEL", openai_settings.MODEL_NAME)
        self.client = None
        self.max_retries = 3
        self.retry_delay = 2  # seconds
        
        # Cache for generated responses
        self.response_cache = {}
        
        logger.info(f"ResponseService initialized with model: {self.model}")
    
    async def generate_response(self, question: Dict[str, str], knowledge: List[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Generate a response to an RFP question
        
        Args:
            question: The question to answer
            knowledge: Optional list of relevant knowledge documents
            
        Returns:
            Dict containing the generated response
        """
        question_id = question.get('id', 'unknown')
        question_text = question.get('search_query', question.get('original_text', question.get('text', '')))
        truncated_question = question_text[:50] + '...' if len(question_text) > 50 else question_text
        
        logger.info(f"Generating response for question {question_id}: '{truncated_question}'")
        
        # Generate cache key
        cache_key = f"{question_id}_{question_text}"
        
        # Check cache
        if cache_key in self.response_cache:
            logger.info(f"Using cached response for question {question_id}")
            return self.response_cache[cache_key]
        
        try:
            # Initialize client if not already done
            if self.client is None:
                logger.info("Initializing Azure OpenAI client for response generation")
                self.client = get_openai_client()
                logger.info("Azure OpenAI client initialized successfully")
            
            # If no knowledge provided, retrieve it
            if knowledge is None:
                logger.info(f"Retrieving knowledge for question {question_id}")
                knowledge = await knowledge_service.find_relevant_content(question_text)
                logger.info(f"Retrieved {len(knowledge)} knowledge items")
            
            # Format knowledge context
            logger.info("Formatting knowledge context")
            knowledge_context = ""
            for i, item in enumerate(knowledge):
                source = item.get('source', f"Source {i+1}")
                knowledge_context += f"\n--- {source} ---\n{item['text']}\n"
            
            # Get response generation prompt
            prompt_data = prompt_loader.get_filled_prompt(
                "response_generation",
                question=question_text,
                knowledge_content=knowledge_context
            )
            
            if not prompt_data:
                logger.warning("Failed to load response generation prompt, using fallback")
                system_prompt = "You are an expert RFP response writer."
                user_prompt = f"""
                Generate a professional response to the following RFP question:
                
                QUESTION: {question_text}
                
                Use the following knowledge base content to inform your response:
                
                {knowledge_context}
                
                Your response should be professional, detailed, and directly address the question.
                """
            else:
                system_prompt = prompt_data.get("system", "You are an expert RFP response writer.")
                user_prompt = prompt_data.get("user", "")
            
            # Generate response using Azure OpenAI with retries
            logger.info(f"Generating response using Azure OpenAI model {self.model}")
            response_text = None
            retries = 0
            
            while retries < self.max_retries:
                try:
                    response = self.client.chat.completions.create(
                        model=self.model,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt}
                        ],
                        temperature=0.2,
                        max_tokens=2000
                    )
                    
                    # Extract response text
                    response_text = response.choices[0].message.content
                    logger.info(f"Successfully generated response for question {question_id}")
                    break
                except Exception as e:
                    retries += 1
                    logger.warning(f"Attempt {retries} failed: {str(e)}")
                    if retries < self.max_retries:
                        wait_time = self.retry_delay * (2 ** (retries - 1))  # Exponential backoff
                        logger.info(f"Retrying in {wait_time} seconds...")
                        time.sleep(wait_time)
                    else:
                        logger.error(f"Failed to generate response after {self.max_retries} attempts")
                        raise
            
            # Create response object with full transparency
            logger.info("Creating response object with full transparency data")
            response_obj = {
                "question_id": question_id,
                "question_text": question_text,
                "response_text": response_text,
                "search_query": question_text,  # The exact query used for search
                "system_prompt": system_prompt,  # The system prompt used
                "user_prompt": user_prompt,  # The user prompt used
                "knowledge_context": knowledge_context,  # The full context provided to the LLM
                "sources": [{
                    "text": k["text"],
                    "metadata": k.get("metadata", {}),
                    "source": k.get("source", "Unknown"),
                    "score": k.get("score", 0.0)
                } for k in knowledge]
            }
            
            # Cache response
            logger.info(f"Caching response for question {question_id}")
            self.response_cache[cache_key] = response_obj
            
            return response_obj
        except Exception as e:
            logger.error(f"Error generating response for question {question_id}: {str(e)}")
            # Return a fallback response instead of crashing
            return {
                "question_id": question_id,
                "question_text": question_text,
                "response_text": "I apologize, but I was unable to generate a response to this question due to a technical issue. Please try again later.",
                "sources": [],
                "error": str(e)
            }
    
    async def generate_chat_response(self, query: str, knowledge: List[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Generate a response to a direct knowledge base query via chat
        
        Args:
            query: The user's question or query
            knowledge: Optional list of relevant knowledge documents
            
        Returns:
            Dict containing the generated response with transparency data
        """
        question_id = question.get('id', 'unknown')
        question_text = question.get('search_query', question.get('original_text', question.get('text', '')))
        truncated_question = question_text[:50] + '...' if len(question_text) > 50 else question_text
        
        logger.info(f"Generating response for question {question_id}: '{truncated_question}'")
        
        # Generate cache key
        cache_key = f"{question_id}_{question_text}"
        
        # Check cache
        if cache_key in self.response_cache:
            logger.info(f"Using cached response for question {question_id}")
            return self.response_cache[cache_key]
        
        try:
            # Initialize client if not already done
            if self.client is None:
                logger.info("Initializing Azure OpenAI client for response generation")
                self.client = get_openai_client()
                logger.info("Azure OpenAI client initialized successfully")
            
            # If no knowledge provided, retrieve it
            if knowledge is None:
                logger.info(f"Retrieving knowledge for question {question_id}")
                knowledge = await knowledge_service.find_relevant_content(question_text)
                logger.info(f"Retrieved {len(knowledge)} knowledge items")
            
            # Format knowledge context
            logger.info("Formatting knowledge context")
            knowledge_context = ""
            for i, item in enumerate(knowledge):
                source = item.get('source', f"Source {i+1}")
                knowledge_context += f"\n--- {source} ---\n{item['text']}\n"
            
            # Get response generation prompt
            prompt_data = prompt_loader.get_filled_prompt(
                "response_generation",
                question=question_text,
                knowledge_content=knowledge_context
            )
            
            if not prompt_data:
                logger.warning("Failed to load response generation prompt, using fallback")
                system_prompt = "You are an expert RFP response writer."
                user_prompt = f"""
Generate a professional response to the following RFP question:

QUESTION: {question_text}

Use the following knowledge base content to inform your response:

{knowledge_context}

Your response should be professional, detailed, and directly address the question.
"""
            else:
                system_prompt = prompt_data.get("system", "You are an expert RFP response writer.")
                user_prompt = prompt_data.get("user", "")
            
            # Generate response using Azure OpenAI with retries
            logger.info(f"Generating response using Azure OpenAI model {self.model}")
            response_text = None
            retries = 0
            
            while retries < self.max_retries:
                try:
                    response = self.client.chat.completions.create(
                        model=self.model,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt}
                        ],
                        temperature=0.2,
                        max_tokens=2000
                    )
                    
                    # Extract response text
                    response_text = response.choices[0].message.content
                    logger.info(f"Successfully generated response for question {question_id}")
                    break
                except Exception as e:
                    retries += 1
                    logger.warning(f"Attempt {retries} failed: {str(e)}")
                    if retries < self.max_retries:
                        wait_time = self.retry_delay * (2 ** (retries - 1))  # Exponential backoff
                        logger.info(f"Retrying in {wait_time} seconds...")
                        time.sleep(wait_time)
                    else:
                        logger.error(f"Failed to generate response after {self.max_retries} attempts")
                        raise
            
            # Create response object with full transparency
            logger.info("Creating response object with full transparency data")
            response_obj = {
                "question_id": question_id,
                "question_text": question_text,
                "response_text": response_text,
                "search_query": question_text,  # The exact query used for search
                "system_prompt": system_prompt,  # The system prompt used
                "user_prompt": user_prompt,  # The user prompt used
                "knowledge_context": knowledge_context,  # The full context provided to the LLM
                "sources": [{
                    "text": k["text"],
                    "metadata": k.get("metadata", {}),
                    "source": k.get("source", "Unknown"),
                    "score": k.get("score", 0.0)
                } for k in knowledge]
            }
            
            # Cache response
            logger.info(f"Caching response for question {question_id}")
            self.response_cache[cache_key] = response_obj
            
            return response_obj
        except Exception as e:
            logger.error(f"Error generating response for question {question_id}: {str(e)}")
            # Return a fallback response instead of crashing
            return {
                "question_id": question_id,
                "question_text": question_text,
                "response_text": "I apologize, but I was unable to generate a response to this question due to a technical issue. Please try again later.",
                "sources": [],
                "error": str(e)
            }
    
    async def generate_chat_response(self, query: str, knowledge: List[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Generate a response to a direct chat query about the knowledge base
        
        Args:
            query: The user's question or query text
            knowledge: Optional list of relevant knowledge documents
            
        Returns:
            Dict containing the generated response with transparency data
        """
        truncated_query = query[:50] + '...' if len(query) > 50 else query
        logger.info(f"Generating chat response for query: '{truncated_query}'")
        
        # Generate cache key
        cache_key = f"chat_{query}"
        
        # Check cache
        if cache_key in self.response_cache:
            logger.info(f"Using cached response for chat query: '{truncated_query}'")
            return self.response_cache[cache_key]
        
        try:
            # Initialize client if not already done
            if self.client is None:
                logger.info("Initializing Azure OpenAI client for chat response generation")
                self.client = get_openai_client()
                logger.info("Azure OpenAI client initialized successfully")
            
            # If no knowledge provided, retrieve it
            if knowledge is None:
                logger.info(f"Retrieving knowledge for chat query: '{truncated_query}'")
                knowledge = await knowledge_service.find_relevant_content(query)
                logger.info(f"Retrieved {len(knowledge)} knowledge items")
            
            # Format knowledge context
            logger.info("Formatting knowledge context for chat")
            knowledge_context = ""
            for i, item in enumerate(knowledge):
                source = item.get('source', f"Source {i+1}")
                knowledge_context += f"\n--- {source} ---\n{item['text']}\n"
            
            # Get chat response prompt
            prompt_data = prompt_loader.get_filled_prompt(
                "knowledge_chat",
                question=query,
                knowledge=knowledge_context
            )
            
            if not prompt_data:
                logger.warning("Failed to load chat prompt, using fallback")
                system_prompt = "You are a knowledgeable assistant that helps users find information."
                user_prompt = f"""
                Please answer the following question using only the information provided in the knowledge context below:
                
                USER QUESTION: {query}
                
                KNOWLEDGE CONTEXT:
                {knowledge_context}
                
                If the information provided doesn't contain the answer, just say "I don't have enough information about that."
                Always cite the sources you used in your answer.
                """
            else:
                system_prompt = prompt_data.get("system", "You are a knowledgeable assistant.")
                user_prompt = prompt_data.get("user", "")
            
            # Generate response using Azure OpenAI with retries
            logger.info(f"Generating chat response using Azure OpenAI model {self.model}")
            response_text = None
            retries = 0
            
            while retries < self.max_retries:
                try:
                    response = self.client.chat.completions.create(
                        model=self.model,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt}
                        ],
                        temperature=0.3,
                        max_tokens=1500
                    )
                    
                    # Extract response text
                    response_text = response.choices[0].message.content
                    logger.info(f"Successfully generated chat response for query: '{truncated_query}'")
                    break
                except Exception as e:
                    retries += 1
                    logger.warning(f"Attempt {retries} failed: {str(e)}")
                    if retries < self.max_retries:
                        wait_time = self.retry_delay * (2 ** (retries - 1))  # Exponential backoff
                        logger.info(f"Retrying in {wait_time} seconds...")
                        time.sleep(wait_time)
                    else:
                        logger.error(f"Failed to generate chat response after {self.max_retries} attempts")
                        raise
            
            # Create response object with full transparency
            logger.info("Creating chat response object with full transparency data")
            response_obj = {
                "query": query,
                "response_text": response_text,
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "knowledge_context": knowledge_context,
                "sources": [{
                    "text": k["text"],
                    "metadata": k.get("metadata", {}),
                    "source": k.get("source", "Unknown"),
                    "score": k.get("score", 0.0)
                } for k in knowledge]
            }
            
            # Cache response
            logger.info(f"Caching chat response for query: '{truncated_query}'")
            self.response_cache[cache_key] = response_obj
            
            return response_obj
        except Exception as e:
            logger.error(f"Error generating chat response: {str(e)}")
            # Return a fallback response instead of crashing
            return {
                "query": query,
                "response_text": "I apologize, but I was unable to generate a response due to a technical issue. Please try again later.",
                "sources": [],
                "error": str(e)
            }
    
    async def generate_responses(self, questions: List[Dict[str, str]]) -> List[Dict[str, Any]]:
        """
        Generate responses for multiple questions
        
        Args:
            questions: List of questions to answer
            
        Returns:
            List of generated responses
        """
        logger.info(f"Generating responses for {len(questions)} questions")
        responses = []
        
        try:
            for i, question in enumerate(questions):
                logger.info(f"Processing question {i+1}/{len(questions)}")
                response = await self.generate_response(question)
                responses.append(response)
                
            logger.info(f"Successfully generated {len(responses)} responses")
            return responses
        except Exception as e:
            logger.error(f"Error generating multiple responses: {str(e)}")
            # Return any responses we've generated so far
            logger.info(f"Returning {len(responses)} successful responses")
            return responses
    
    async def _generate_openai_content(self, system_prompt: str, user_prompt: str, temp: float = 0.3, max_tokens: int = 4000) -> str:
        """
        Helper method to generate content using OpenAI with error handling
        
        Args:
            system_prompt: The system prompt
            user_prompt: The user prompt
            temp: Temperature setting
            max_tokens: Maximum tokens to generate
            
        Returns:
            Generated content or None on failure
        """
        if not self.client:
            logger.info("Initializing Azure OpenAI client")
            self.client = get_openai_client()
            
        retries = 0
        while retries < self.max_retries:
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=temp,
                    max_tokens=max_tokens
                )
                
                if response and hasattr(response, 'choices') and len(response.choices) > 0 and hasattr(response.choices[0], 'message'):
                    return response.choices[0].message.content
                else:
                    logger.warning("Invalid response structure from OpenAI")
                    return None
            except Exception as e:
                logger.error(f"Error in OpenAI call: {str(e)}")
                retries += 1
                if retries >= self.max_retries:
                    logger.error("Max retries reached")
                    return None
                wait_time = self.retry_base_wait_time * (2 ** retries)  # Exponential backoff
                logger.info(f"Waiting {wait_time}s before retry {retries}")
                await asyncio.sleep(wait_time)
        
        return None
        
    async def _generate_multistage_response(self, system_prompt: str, structure: str, rfp_summary: str, evaluation_criteria: str="") -> str:
        """
        Generate a comprehensive response by breaking it into multiple sections to overcome token limits
        
        Args:
            system_prompt: The main system prompt
            structure: The response structure
            rfp_summary: The RFP summary
            evaluation_criteria: Optional evaluation criteria
            
        Returns:
            Complete generated response combining multiple sections
        """
        logger.info("Beginning multi-stage response generation for comprehensive content")
        
        try:
            # 1. Parse the structure to identify major sections
            structure_lines = structure.split('\n')
            major_sections = []
            
            for line in structure_lines:
                # Look for potential section headers (usually start with "Volume" or have other indicators)
                if line.strip() and (line.strip().startswith('-') or 
                                    'volume' in line.lower() or 
                                    ':' in line or
                                    'section' in line.lower()):
                    # Clean up the line
                    section = line.strip()
                    if section.startswith('-'):
                        section = section[1:].strip()
                    major_sections.append(section)
            
            if not major_sections:
                # If no sections found, create default sections
                major_sections = ["Technical Approach", "Past Performance", "Pricing", "Implementation Plan"]
            
            logger.info(f"Identified {len(major_sections)} major sections for multi-stage generation")
            
            # 2. Generate Executive Summary
            logger.info("Generating Executive Summary")
            exec_summary_prompt = f"""Create a detailed, compelling executive summary for an RFP response.
            
            RFP OVERVIEW:
            {rfp_summary}
            
            SUBMISSION STRUCTURE:
            {structure}
            
            Create a detailed executive summary (1-2 pages) that introduces the proposal, highlights key differentiators,
            and touches on the main value propositions. Format in professional markdown."""
            
            exec_summary = await self._generate_openai_content(
                system_prompt,
                exec_summary_prompt,
                temp=0.3,
                max_tokens=3000  # Smaller token limit for summary
            )
            
            # 3. Generate each major section
            full_response = "# RFP Response Document\n\n" + (exec_summary or "## Executive Summary\n\nExecutive summary content could not be generated.") + "\n\n"
            
            # Process each section
            for section in major_sections:
                logger.info(f"Generating content for section: {section}")
                
                section_prompt = f"""Create detailed, comprehensive content for the '{section}' section of an RFP response.
                
                RFP OVERVIEW:
                {rfp_summary}
                
                SECTION REQUIREMENTS:
                {section}
                
                EVALUATION CRITERIA:
                {evaluation_criteria}
                
                Generate extremely detailed content (3-4 pages) for this section with multiple subsections, addressing all requirements
                thoroughly. Include specific examples, methodologies, approaches, and metrics where applicable.
                Format in professional markdown with appropriate headings and subheadings."""
                
                section_content = await self._generate_openai_content(
                    system_prompt,
                    section_prompt,
                    temp=0.3,
                    max_tokens=4000  # Substantial content per section
                )
                
                if section_content:
                    # Clean up formatting if needed
                    if not section_content.startswith("#"):
                        section_content = f"## {section}\n\n{section_content}"
                    full_response += section_content + "\n\n"
                else:
                    full_response += f"## {section}\n\n*Note: Content for this section could not be generated.*\n\n"
            
            # 4. Generate Conclusion
            logger.info("Generating Conclusion")
            conclusion_prompt = f"""Create a strong conclusion for an RFP response.
            
            RFP OVERVIEW:
            {rfp_summary}
            
            SUBMISSION STRUCTURE:
            {structure}
            
            Create a detailed conclusion (1 page) that summarizes the key value propositions, reiterates commitment,
            and provides a compelling call to action. Format in professional markdown."""
            
            conclusion = await self._generate_openai_content(
                system_prompt,
                conclusion_prompt,
                temp=0.3,
                max_tokens=2000  # Smaller token limit for conclusion
            )
            
            if conclusion:
                if not conclusion.startswith("#"):
                    conclusion = "## Conclusion\n\n" + conclusion
                full_response += conclusion
            else:
                full_response += "## Conclusion\n\n*Note: Conclusion content could not be generated.*\n\n"
            
            logger.info("Multi-stage generation completed successfully")
            return full_response
            
        except Exception as e:
            logger.error(f"Error in multi-stage generation: {str(e)}")
            return None
    
    async def generate_final_response(self, file_key: str, guide: Dict[str, Any], responses: Dict[str, Any], metadata: Dict[str, Any], responses_text: str = "") -> str:
        """
        Generate a comprehensive final response document using the response guide structure 
        and individual question responses. Uses multi-stage generation for very detailed content.
        
        Args:
            file_key: The document ID
            guide: The response guide data
            responses: Dictionary of cached responses
            metadata: Document metadata
            responses_text: Optional pre-formatted markdown responses text
            
        Returns:
            Markdown formatted final response
        """
        logger.info(f"Generating final response document for {file_key}")
        
        # Initialize OpenAI client if not already initialized
        if self.client is None:
            try:
                logger.info("Initializing OpenAI client")
                self.client = get_openai_client()
                logger.info("OpenAI client initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize OpenAI client: {str(e)}")
                # Return a markdown error message to avoid breaking functionality
                return self._create_fallback_response(guide, responses, responses_text, metadata, 
                                                     error_msg=f"Failed to initialize AI client: {str(e)}")
        else:
            logger.info("Using existing OpenAI client")
        
        try:

            # Organize responses by section
            section_responses = {}
            
            # Extract sections from the response guide
            sections = []
            if "submission_structure" in guide and isinstance(guide["submission_structure"], list):
                sections = [item.get("section", "") for item in guide["submission_structure"] if isinstance(item, dict)]
            
            # Add other standard sections
            if "evaluation_criteria" in guide:
                sections.append("Evaluation Criteria")
            if "compliance_checklist" in guide:
                sections.append("Compliance Checklist")
            
            # Map responses to sections
            for question_id, response in responses.items():
                section = response.get("section", "Other")
                if section not in section_responses:
                    section_responses[section] = []
                section_responses[section].append(response)
            
            # Prepare for prompt
            # Format response guide structure
            response_structure = ""
            if "executive_summary" in guide:
                response_structure += "Executive Summary\n\n"
            
            for section in sections:
                response_structure += f"{section}\n"
            
            # Format section answers - use pre-formatted text if available
            section_answers = ""
            if responses_text:
                # Use the pre-formatted markdown
                section_answers = responses_text
            else:
                # Generate from JSON responses
                for section, resp_list in section_responses.items():
                    section_answers += f"SECTION: {section}\n\n"
                    for resp in resp_list:
                        question_text = resp.get("question_text", "Unknown Question")
                        response_text = resp.get("response_text", "No response generated")
                        section_answers += f"QUESTION: {question_text}\n\n"
                        section_answers += f"ANSWER: {response_text}\n\n"
                    section_answers += "---\n\n"
            
            # Format RFP summary from metadata
            rfp_summary = ""
            if "summary" in metadata:
                rfp_summary += metadata["summary"]
            elif "executive_summary" in guide:
                rfp_summary += guide["executive_summary"]
            else:
                rfp_summary = "No summary available"
                
            # Extract additional sections for the enhanced prompt
            format_requirements = ""
            if isinstance(guide, dict) and "response_format" in guide:
                format_requirements = str(guide["response_format"])
            
            # Extract evaluation criteria
            evaluation_criteria = ""
            if isinstance(guide, dict) and "evaluation_criteria" in guide:
                evaluation_criteria = str(guide["evaluation_criteria"])
            elif "content" in guide and "Evaluation Criteria" in guide["content"]:
                # Try to extract from content
                content = guide["content"]
                start_idx = content.find("## Evaluation Criteria")
                if start_idx != -1:
                    end_idx = content.find("##", start_idx + 1)
                    if end_idx != -1:
                        evaluation_criteria = content[start_idx:end_idx].strip()
                    else:
                        evaluation_criteria = content[start_idx:].strip()
            
            # Load final response prompt template with enhanced parameters
            prompt_data = prompt_loader.get_filled_prompt(
                "final_response",
                rfp_summary=rfp_summary,
                response_structure=response_structure,
                section_answers=section_answers,
                evaluation_criteria=evaluation_criteria,
                format_requirements=format_requirements
            )
            
            # Debug - log what prompts are available
            print(f"Available prompts: {list(prompt_loader.prompts.keys())}")
            print(f"Prompt data: {prompt_data if prompt_data else 'None'}")            
            
            # Initialize prompt content
            system_prompt = "You are an expert proposal writer who creates winning RFP responses."
            user_prompt = f"""
            I need to create a comprehensive RFP response based on the following structure and individual answers.
            
            RFP OVERVIEW:
            {rfp_summary}
            
            REQUIRED RESPONSE STRUCTURE:
            {response_structure}
            
            SECTION ANSWERS:
            {section_answers}
            
            Please create a cohesive, compelling final response document that follows the required structure.
            Format the response in proper markdown with appropriate headings, subheadings, and formatting.
            """
            
            # If prompt data was loaded successfully, use it instead
            if prompt_data:
                print("Using loaded prompt template")
                if "system" in prompt_data:
                    system_prompt = prompt_data["system"]
                if "user" in prompt_data:
                    user_prompt = prompt_data["user"]
                    
            # Generate response using Azure OpenAI with retries
            logger.info(f"Generating final response using Azure OpenAI model {self.model}")
            response_text = None
            retries = 0
            
            # Announce the multi-stage approach we're using
            logger.info("Using multi-stage generation approach for comprehensive content")
            
            # Multi-stage generation helper function
            async def generate_section(section_name, section_prompt, section_system_prompt=None):
                """Generate content for a specific section"""
                logger.info(f"Generating content for section: {section_name}")
                try:
                    # Ensure proper indentation and format in prompts
                    cleaned_prompt = "\n".join([line.strip() for line in section_prompt.split("\n")])
                    
                    # If we have a client, use it directly
                    if self.client:
                        response = self.client.chat.completions.create(
                            model=self.model,
                            messages=[
                                {"role": "system", "content": section_system_prompt or system_prompt},
                                {"role": "user", "content": cleaned_prompt}
                            ],
                            temperature=0.3,
                            max_tokens=4000  # Use smaller tokens per section
                        )
                        
                        if response and hasattr(response, 'choices') and len(response.choices) > 0 and hasattr(response.choices[0], 'message'):
                            return response.choices[0].message.content
                    
                    # If direct call failed, use the helper method as fallback
                    if 'response' not in locals() or not response:
                        logger.info(f"Using fallback method for section: {section_name}")
                        section_response = await self._generate_openai_content(
                            section_system_prompt or system_prompt,
                            cleaned_prompt,
                            temp=0.3,
                            max_tokens=4000  # Use smaller tokens per section
                        )
                        if section_response:
                            return section_response
                            
                    # If we get here, both methods failed
                    logger.warning(f"Failed to generate content for section {section_name}")
                    return f"# {section_name}\n\n*Note: Content generation for this section failed. Please try regenerating the document.*\n\n"
                except Exception as e:
                    logger.error(f"Error generating content for section {section_name}: {str(e)}")
                    return f"# {section_name}\n\n*Note: Error occurred while generating this section: {str(e)}*\n\n"
            
            # Extract major sections from structure for multi-stage generation
            try:
                # First, generate document outline with explicit formatting instructions
                outline_prompt = f"Based on the following submission structure, create a detailed document outline with all major sections and subsections:\n\n{response_structure}\n\nCreate ONLY the outline with headings and subheadings (no content). Format each major heading with '# ' prefix (e.g., '# Technical Approach') and each subheading with '## ' prefix."
                
                outline = await generate_section("Document Outline", outline_prompt)
                
                # Extract major section headings from outline with robust parsing
                major_sections = []
                
                # First try to find properly formatted markdown headings
                for line in outline.split("\n"):
                    if line.startswith("# "):  # Level 1 headings
                        section = line.replace("# ", "").strip()
                        if section.lower() not in ["table of contents", "contents", "appendix", "appendices"]:
                            major_sections.append(section)
                
                # If no sections found, try alternative formats like numbered lists or plain text
                if not major_sections:
                    logger.info("No standard markdown headings found, trying alternative formats")
                    
                    # Look for numbered or bullet lists that might indicate sections
                    import re
                    section_patterns = [
                        r'^\d+\.\s+([A-Z][^\n]+)$',  # "1. Technical Approach"
                        r'^-\s+([A-Z][^\n]+)$',      # "- Technical Approach"
                        r'^\*\s+([A-Z][^\n]+)$',     # "* Technical Approach"
                        r'^([A-Z][a-zA-Z\s]+):',     # "Technical Approach:"
                        r'^VOLUME\s+[\dIVX]+[\s:]+(.+)$'  # "VOLUME I: Technical Approach"
                    ]
                    
                    for pattern in section_patterns:
                        matches = re.findall(pattern, outline, re.MULTILINE)
                        if matches:
                            for match in matches:
                                if match.strip() and match.strip().lower() not in ["table of contents", "contents", "appendix", "appendices"]:
                                    major_sections.append(match.strip())
                            if major_sections:
                                break
                
                # Last resort: If still no sections found, fall back to using structure
                if not major_sections and response_structure:
                    logger.info("No sections extracted from outline, parsing structure directly")
                    structure_lines = [line.strip() for line in response_structure.split('\n') if line.strip()]
                    
                    # Get potential section headers from structure
                    for line in structure_lines:
                        if line.strip() and (line.strip().startswith('-') or 
                                          'volume' in line.lower() or 
                                          ':' in line or
                                          'section' in line.lower()):
                            # Clean up the line
                            section = line.strip()
                            if section.startswith('-'):
                                section = section[1:].strip()
                            if section and section.lower() not in ["table of contents", "contents", "appendix", "appendices"]:
                                major_sections.append(section)
                
                # If still empty, use default sections as last resort
                if not major_sections:
                    logger.warning("Could not extract any sections - using default sections")
                    major_sections = ["Technical Approach", "Management Approach", "Past Performance", "Pricing", "Implementation Plan"]
                
                logger.info(f"Extracted {len(major_sections)} major sections for multi-stage generation: {major_sections}")
                
                # Generate executive summary
                exec_summary = await generate_section(
                    "Executive Summary", 
                    f"Create a compelling executive summary (2-3 pages) for the RFP response with the following requirements:\n\n{response_structure}\n\nRFP Overview:\n{rfp_summary}\n\nCreate a comprehensive executive summary that introduces your solution, highlights key differentiators, addresses critical client needs, and outlines the major benefits and value propositions. Focus on strategic positioning, strong value statements, and business outcomes. Format using professional markdown with appropriate headings."
                )
                
                # Initialize final response with executive summary
                final_content = exec_summary + "\n\n"
                
                # Generate content for each major section in parallel
                section_contents = []
                for section in major_sections:
                    section_prompt = f"Create detailed content for the '{section}' section of an RFP response.\n\n"
                    section_prompt += f"RFP Overview:\n{rfp_summary}\n\n"
                    section_prompt += f"Full Submission Structure:\n{response_structure}\n\n"
                    
                    # If we have section answers relevant to this section, include them
                    if section in section_responses:
                        section_prompt += f"Relevant section answers for {section}:\n"
                        for resp in section_responses[section]:
                            question = resp.get("question_text", "Unknown")
                            answer = resp.get("response_text", "No response")
                            section_prompt += f"Q: {question}\nA: {answer}\n\n"
                    
                    # Add evaluation criteria if available
                    if evaluation_criteria:
                        section_prompt += f"Evaluation Criteria to address:\n{evaluation_criteria}\n\n"
                    
                    # Request extremely detailed content
                    section_prompt += f"Generate EXTREMELY DETAILED AND COMPREHENSIVE content (4-5 pages minimum) for the {section} section with the following structure:\n\n"
                    section_prompt += f"1. Begin with a strategic overview paragraph positioning your solution\n"
                    section_prompt += f"2. Create 4-5 detailed subsections with specific headings relevant to this section\n"
                    section_prompt += f"3. Include concrete examples, case studies, methodologies, and metrics\n"
                    section_prompt += f"4. Address explicit requirements from the RFP and also unstated needs\n"
                    section_prompt += f"5. Connect capabilities to measurable business value and outcomes\n\n"
                    section_prompt += f"Format as professional markdown with proper heading hierarchy. Do not use placeholder text - generate substantive, detailed content even with limited source material."
                    
                    # Add this section to the list to process
                    section_contents.append((section, generate_section(section, section_prompt)))
                
                # Wait for all section content to be generated
                for section, content_future in section_contents:
                    final_content += await content_future + "\n\n"
                
                # Generate conclusion
                conclusion_prompt = f"Create a comprehensive conclusion (1-2 pages) for the RFP response based on:\n\n{rfp_summary}\n\n{response_structure}\n\nThe conclusion should:\n1. Summarize the key value propositions and differentiators\n2. Reaffirm commitments to client success and outcomes\n3. Address the business impact of your complete solution\n4. Include confidence statements about meeting or exceeding requirements\n5. Provide a strong, compelling call to action\n\nFormat as professional markdown with appropriate headings and structure. Create substantive content (1-2 pages) rather than a brief summary."
                conclusion = await generate_section("Conclusion", conclusion_prompt)
                final_content += conclusion
                
                # Use the multi-stage generated content
                return final_content
                
            except Exception as e:
                logger.error(f"Error in multi-stage generation: {str(e)}")
                logger.error("Falling back to single-call generation")
                # Fall back to single-call generation if multi-stage fails
                try:
                    # Defensive check for client
                    if not self.client:
                        logger.error("OpenAI client is still None after initialization attempt")
                        return self._create_fallback_response(guide, responses, responses_text, metadata,
                                                             error_msg="OpenAI client initialization failed")
                        
                    response = self.client.chat.completions.create(
                        model=self.model,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt}
                        ],
                        temperature=0.3,
                        max_tokens=12000,  # Substantially increased for extremely detailed 20+ page content
                    
                    )
                    
                    # Extract response text with defensive coding
                    if response and hasattr(response, 'choices') and len(response.choices) > 0 and hasattr(response.choices[0], 'message'):
                        response_text = response.choices[0].message.content
                        logger.info(f"Successfully generated final response document")
                        # Exit loop on success
                        retries = self.max_retries  # This exits the loop instead of using break
                    else:
                        logger.warning(f"Received invalid response format from API")
                        retries += 1
                except Exception as e:
                    retries += 1
                    logger.warning(f"Attempt {retries} failed: {str(e)}")
                    if retries < self.max_retries:
                        wait_time = self.retry_delay * (2 ** (retries - 1))  # Exponential backoff
                        logger.info(f"Retrying in {wait_time} seconds...")
                        time.sleep(wait_time)
                    else:
                        logger.error(f"Failed to generate final response after {self.max_retries} attempts: {str(e)}")
                        # Use fallback instead of raising exception
                        return self._create_fallback_response(guide, responses, responses_text, metadata,
                                                             error_msg=f"API error after {self.max_retries} attempts: {str(e)}")
            
            # Final defensive check
            if not response_text:
                logger.error("Failed to get valid response text despite successful API call")
                return self._create_fallback_response(guide, responses, responses_text, metadata,
                                                     error_msg="Empty response from API")
                
            return response_text
        
        except Exception as e:
            logger.error(f"Error generating final response: {str(e)}")
            return f"# Error Generating Final Response\n\nAn error occurred while generating the final response document: {str(e)}\n\nPlease try again or contact support."
    
    def _create_fallback_response(self, guide: Dict[str, Any], responses: Dict[str, Any], 
                           responses_text: str, metadata: Dict[str, Any],
                           error_msg: str = "Error generating response") -> str:
        """
        Create a fallback response when API calls fail
        
        Args:
            guide: The response guide data
            responses: Dictionary of cached responses
            responses_text: Optional pre-formatted markdown responses text
            metadata: Document metadata
            error_msg: Error message to include
            
        Returns:
            Markdown formatted fallback response
        """
        logger.warning(f"Using fallback response generation: {error_msg}")
        
        # Create a simple document with available data
        final_response = f"# Final RFP Response\n\n"
        final_response += f"*Note: This is an automatically generated fallback response.*\n\n"
        
        # Add guide content if available
        if "content" in guide:
            final_response += f"## Response Structure\n{guide['content']}\n\n"
        
        # Add responses if available - prefer markdown text version
        if responses_text:
            final_response += f"## Generated Responses\n{responses_text}"
        elif responses:
            # Format responses from JSON
            final_response += "## Generated Responses\n\n"
            for q_id, resp in responses.items():
                question = resp.get("question_text", "Unknown Question")
                answer = resp.get("response_text", "No response")
                final_response += f"### {question}\n\n{answer}\n\n---\n\n"
        
        return final_response
        
    async def create_document(self, responses: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Create a document from generated responses
        
        Args:
            responses: List of responses to include
            
        Returns:
            Dict containing document information
        """
        logger.info(f"Creating document from {len(responses)} responses")
        
        try:
            # Sort responses by question ID
            logger.info("Sorting responses by question ID")
            sorted_responses = sorted(responses, key=lambda r: r.get("question_id", ""))
            
            # Create document content
            logger.info("Generating document content")
            content = "# RFP Response\n\n"
            
            for response in sorted_responses:
                question_text = response.get('question_text', 'Unknown Question')
                response_text = response.get('response_text', 'No response generated')
                content += f"## {question_text}\n\n"
                content += f"{response_text}\n\n"
                
                # Add sources if available
                sources = response.get('sources', [])
                if sources:
                    content += "### Sources\n\n"
                    for i, source in enumerate(sources):
                        source_name = source.get('source', f"Source {i+1}")
                        score = source.get('score', 0.0)
                        content += f"- **{source_name}** (Relevance: {score:.2f})\n"
                    content += "\n"
            
            # TODO: In a real implementation, we would generate a PDF or DOCX file
            # For this MVP, we'll just return the content
            
            logger.info("Document created successfully")
            return {
                "content": content,
                "format": "markdown"
            }
        except Exception as e:
            logger.error(f"Error creating document: {str(e)}")
            # Return a minimal document with error information
            return {
                "content": "# RFP Response\n\nAn error occurred while creating the document.\n\nPlease try again later.",
                "format": "markdown",
                "error": str(e)
            }

# Create singleton instance
response_service = ResponseService()
