import os
from dotenv import load_dotenv
from google import genai

load_dotenv()
chave = os.getenv("CHAVE_API_GEMINI")

print("Consultando...\n")
cliente = genai.Client(api_key=chave)

try:
    print("--- MODELOS AUTORIZADOS ---")
    # Puxa a lista e imprime apenas o nome, sem filtros de método
    for modelo in cliente.models.list():
        print(modelo.name)
    print("---------------------------")
except Exception as e:
    print(f"Erro: {e}")