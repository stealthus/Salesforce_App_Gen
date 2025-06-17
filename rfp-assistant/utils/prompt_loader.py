"""
Prompt loader utility for loading prompts from YAML files.
"""
import os
import yaml
from typing import Dict, Any, Optional

class PromptLoader:
    """
    Utility for loading prompts from YAML files in the prompts directory.
    """
    def __init__(self, prompts_dir: str = None):
        """
        Initialize the prompt loader with the prompts directory.
        
        Args:
            prompts_dir: Directory containing prompt YAML files
        """
        if prompts_dir is None:
            # Default to the prompts directory in the project root
            self.prompts_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "prompts"
            )
        else:
            self.prompts_dir = prompts_dir
            
        self.prompts = {}
        self._load_prompts()
    
    def _load_prompts(self):
        """Load all prompt files from the prompts directory."""
        prompt_files = [f for f in os.listdir(self.prompts_dir) if f.endswith(".yaml")]
        
        for filename in prompt_files:
            file_path = os.path.join(self.prompts_dir, filename)
            with open(file_path, "r") as f:
                try:
                    # Load prompts from YAML file
                    prompts_data = yaml.safe_load(f)
                    
                    # Add to prompts dictionary
                    for key, value in prompts_data.items():
                        self.prompts[key] = value
                except yaml.YAMLError as e:
                    print(f"Error loading prompt file {filename}: {e}")
    
    def get_prompt(self, prompt_id: str) -> Optional[Dict[str, str]]:
        """
        Get a prompt by its ID.
        
        Args:
            prompt_id: The ID of the prompt to retrieve
            
        Returns:
            Dict containing the prompt system and user messages
        """
        return self.prompts.get(prompt_id)
    
    def fill_template(self, template: str, **kwargs) -> str:
        """
        Fill template variables in a prompt string.
        
        Args:
            template: The template string with variables in {{variable}} format
            **kwargs: Variables to substitute in the template
            
        Returns:
            The filled template string
        """
        filled = template
        for key, value in kwargs.items():
            placeholder = f"{{{{{key}}}}}"
            filled = filled.replace(placeholder, str(value))
        return filled
    
    def get_filled_prompt(self, prompt_id: str, **kwargs) -> Optional[Dict[str, str]]:
        """
        Get a prompt with template variables filled.
        
        Args:
            prompt_id: The ID of the prompt to retrieve
            **kwargs: Variables to substitute in the template
            
        Returns:
            Dict containing the filled prompt system and user messages
        """
        prompt = self.get_prompt(prompt_id)
        if not prompt:
            print(f"No prompt found with ID: {prompt_id}")
            print(f"Available prompt IDs: {list(self.prompts.keys())}")
            return None
            
        filled_prompt = {}
        for key, value in prompt.items():
            if isinstance(value, str):
                filled_prompt[key] = self.fill_template(value, **kwargs)
            else:
                filled_prompt[key] = value
                
        return filled_prompt


# Create singleton instance
prompt_loader = PromptLoader()
