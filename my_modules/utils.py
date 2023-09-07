#########################################
def get_user_input(predefined_text=None):
    """Get user input with basic error-checking."""
    while True:
        # Check predefined text
        if predefined_text:
            user_text = predefined_text
            predefined_text = None  # Clear it after using once to ensure next iterations use input
        else:
            user_text = input("Please enter the gpt prompt text here: ")

        # 1. Check for empty input
        if not user_text.strip():
            print("Error: Text input cannot be empty. Please provide valid text.")
            continue

        # 2. Check for maximum length
        max_length = 100
        if len(user_text) > max_length:
            print(f"Error: Your input exceeds the maximum length of {max_length} characters. Please enter a shorter text.")
            continue

        # 3. Check for prohibited characters
        prohibited_chars = ["@", "#", "$", "%", "&", "*", "!"]
        if any(char in user_text for char in prohibited_chars):
            print(f"Error: Your input contains prohibited characters. Please remove them and try again.")
            continue

        # 4. Check if string contains only numbers
        if user_text.isdigit():
            print("Error: Text input should not be only numbers. Please provide a valid text.")
            continue

        # 5. Check for profanities
        profanities = ["idiot", "loser", "asshole"]
        if any(word in user_text.lower() for word in profanities):
            print("Error: Please avoid using inappropriate language.")
            continue
            
        return user_text