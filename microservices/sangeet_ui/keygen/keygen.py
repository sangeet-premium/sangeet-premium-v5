import secrets
import string

def generate_secret_key(length=64):
    # Define the character pool: letters, digits, and special characters
    characters = string.ascii_letters + string.digits + "!@#$%^&*()_+-=[]{}|;:,.<>?"
    # Generate a secure random key
    secret_key = ''.join(secrets.choice(characters) for _ in range(length))
    return secret_key

# Generate and print the secret key
if __name__ == "__main__":
    key = generate_secret_key()
    print("Your super secure Flask secret key is:")
    print(key)