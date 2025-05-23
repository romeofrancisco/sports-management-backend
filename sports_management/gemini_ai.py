import google.generativeai as genai
from django.conf import settings

# Configure the Gemini AI with your API key
genai.configure(api_key=settings.GOOGLE_AI_API_KEY)

# Initialize the model with the latest version
model = genai.GenerativeModel('gemini-2.0-flash')

def generate_response(prompt, **kwargs):
    try:
        response = model.generate_content(prompt, **kwargs)
        return response.text
    except Exception as e:
        return f"Error generating response: {str(e)}"

def generate_chat(messages, **kwargs):
    try:
        chat = model.start_chat()
        for message in messages:
            if message['role'] == 'user':
                response = chat.send_message(message['content'], **kwargs)
        return response.text
    except Exception as e:
        return f"Error generating chat response: {str(e)}"
