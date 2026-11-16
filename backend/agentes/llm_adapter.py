import os
import time
import logging
from google import genai
from dotenv import load_dotenv

# Configuração de logging
logger = logging.getLogger("ftth_optiroute")

# Carrega explicitamente o .env localizado na raiz (fabrica-ia/.env) a partir da pasta backend
caminho_env = os.path.join(os.path.dirname(__file__), "../.env")
load_dotenv(caminho_env)

# Inicializa o cliente oficial do Google GenAI
api_key = os.getenv("CHAVE_API_GEMINI")
cliente = genai.Client(api_key=api_key)


def consultar_ia(prompt: str, instrucao_sistema: str, max_tentativas: int = 3, espera_inicial: float = 2.0) -> str:
    """
    Envia uma consulta para a IA utilizando o modelo Gemini 3.5 Flash,
    com suporte a retry automático para mitigar erros temporários de indisponibilidade (503/Timeout).
    """
    tentativa = 0
    espera = espera_inicial

    while tentativa < max_tentativas:
        try:
            tentativa += 1
            resposta = cliente.models.generate_content(
                model="gemini-3.5-flash",
                contents=prompt,
                config={
                    "system_instruction": instrucao_sistema,
                    "temperature": 0.2
                }
            )
            return resposta.text
            
        except Exception as e:
            erro_str = str(e)
            # Verifica se é um erro temporário (503, UNAVAILABLE, Timeout ou Rate Limit)
            if any(codigo in erro_str for codigo in ["503", "UNAVAILABLE", "ResourceExhausted", "timeout", "DeadlineExceeded"]):
                if tentativa < max_tentativas:
                    print(f"[AVISO] Tentativa {tentativa}/{max_tentativas} falhou por instabilidade temporária. Tentando novamente em {espera}s...")
                    time.sleep(espera)
                    espera *= 2  # Backoff exponencial (2s, 4s, 8s...)
                    continue
            
            # Se esgotou as tentativas ou for um erro não recuperável, retorna a mensagem formatada
            return f"Erro de comunicação com a IA após {tentativa} tentativas: {erro_str}"
            
    return "Erro de comunicação com a IA: Esgotadas todas as tentativas de reconexão."