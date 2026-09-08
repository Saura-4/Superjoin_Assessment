import os
from dotenv import load_dotenv
from cerebras.cloud.sdk import Cerebras

load_dotenv()

api_key = os.getenv("CEREBRAS_API_KEY")

print("API key loaded:", bool(api_key))

client = Cerebras(api_key=api_key)

response = client.chat.completions.create(
    model="qwen-3.8-27b",
    messages=[
        {
            "role": "user",
            "content": "Hello"
        }
    ],
)

print(response.choices[0].message.content)