# interconnect/config/config.py

import os
from dotenv import dotenv_values
from types import SimpleNamespace

def get_env_data(custom_dotenv_path):
    """
    Loads a .env file from the given custom path and returns its values as an object.

    Args:
        custom_dotenv_path (str): The specific path to the .env file.

    Returns:
        SimpleNamespace: An object with attributes corresponding to the .env variables.
                         Returns None if the file is not found, is empty, or an error occurs.
    """
    if not custom_dotenv_path:
        print("Error: No .env file path provided.")
        return None

    if not os.path.exists(custom_dotenv_path):
        print(f"Error: .env file not found at '{custom_dotenv_path}'")
        return None

    try:
        env_vars_dict = dotenv_values(custom_dotenv_path)

        if not env_vars_dict:
            print(f"Warning: No variables found in '{custom_dotenv_path}' or the file is empty.")
            return SimpleNamespace() # Return an empty namespace to avoid None checks if preferred

        # Convert the dictionary to a SimpleNamespace object
        # This allows accessing keys as attributes (e.g., config.DB_HOST)
        # This version assumes the keys in your .env file are exactly as you want to access them
        # (e.g., if .env has 'database_name', you use .database_name)
        # If .env has 'DATABASE_NAME' and you want .database_name, you'd do:
        # processed_env_vars = {key.lower(): value for key, value in env_vars_dict.items()}
        # return SimpleNamespace(**processed_env_vars)
        return SimpleNamespace(**env_vars_dict)

    except Exception as e:
        print(f"Error loading or processing .env file at '{custom_dotenv_path}': {e}")
        return None