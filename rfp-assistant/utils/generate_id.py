import random
import string

def generate_id():
    """
    Generate a simple 5-character ID that starts with a letter.
    
    Returns:
        str: A random 5-character ID
    """
    # First character must be a letter
    first_char = random.choice(string.ascii_letters)
    
    # Remaining 4 characters can be letters or digits
    remaining_chars = ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(4))
    
    # Combine to form the 5-character ID
    return first_char + remaining_chars
