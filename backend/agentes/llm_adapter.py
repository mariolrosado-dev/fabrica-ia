import os
import time
import logging
import requests
from dotenv import load_dotenv

# Configuração de logging padronizada para a plataforma autônoma
logger = logging.getLogger("fabrica_ia")

# Carrega explicitamente o .env da raiz a partir da pasta backend
caminho_env = os.path.join(os.path.dirname(__file__), "../.env")
load_dotenv(caminho_env)

# URL padrão do Ollama rodando localmente
OLLAMA_URL = os.getenv("OLLAMA_HOST", "http://localhost:11434/v1/chat/completions")
MODELO_LOCAL = "qwen2.5:3b"

def consultar_ia(prompt: str, instrucao_sistema: str, max_tentativas: int = 3, espera_inicial: float = 2.0) -> str:
    """
    Envia uma consulta para a IA utilizando o modelo local Qwen 2.5 (3B) via Ollama,
    com suporte a retry automático para estabilidade de processo local.
    """
    tentativa = 0
    espera = espera_inicial
    ultimo_erro = None

    headers = {
        "Content-Type": "application/json"
    }

    payload = {
        "model": MODELO_LOCAL,
        "messages": [
            {"role": "system", "content": instrucao_sistema},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.2,
        "stream": False
    }

    while tentativa < max_tentativas:
        try:
            tentativa += 1
            response = requests.post(OLLAMA_URL, json=payload, headers=headers, timeout=120)
            
            if response.status_code != 200:
                raise RuntimeError(f"Ollama retornou status HTTP {response.status_code}: {response.text}")

            dados = response.json()
            resposta_texto = dados.get("choices", [{}])[0].get("message", {}).get("content", "")

            if not resposta_texto:
                raise ValueError("O modelo local retornou uma resposta vazia.")
            
            return resposta_texto
            
        except Exception as e:
            ultimo_erro = str(e)
            print(f"[AVISO] Tentativa {tentativa}/{max_tentativas} falhou localmente. Erro: {ultimo_erro}")
            
            if tentativa < max_tentativas:
                print(f"Aguardando {espera}s para nova tentativa no Ollama...")
                time.sleep(espera)
                espera *= 2
                continue
            break

    raise RuntimeError(f"Falha crítica na comunicação com o Ollama local ({MODELO_LOCAL}) após {tentativa} tentativas. Erro original: {ultimo_erro}")