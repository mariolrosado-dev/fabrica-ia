import os
import json
import re
from datetime import datetime
from typing import Optional, Dict, Any

def salvar_arquitetura(plano_json: Dict[str, Any], nome_sugerido: Optional[str] = None) -> str:
    """
    Recebe o JSON do Arquiteto, extrai inteligentemente o nome do projeto (ou usa o sugerido),
    cria a pasta limpa no HD e salva o documento.
    Retorna o caminho físico de onde o arquivo foi salvo.
    """
    metadata = plano_json.get("metadata", {})
    
    # 1. Varredura inteligente de chaves: tenta encontrar o nome no JSON da IA em vários formatos comuns
    nome_cru = (
        plano_json.get("nome_projeto") or 
        plano_json.get("nome") or 
        plano_json.get("titulo") or 
        plano_json.get("title") or 
        metadata.get("nome_projeto") or 
        metadata.get("nome") or
        nome_sugerido or 
        "Projeto_IA"
    )
    
    # Garantia caso a IA alucine e retorne um objeto não-string na chave do nome
    if not isinstance(nome_cru, str):
        nome_cru = "Projeto_IA"
    
    # 2. Limpeza rigorosa: Remove acentos, espaços e caracteres especiais para o Windows
    nome_pasta = re.sub(r'[^A-Za-z0-9]', '_', nome_cru)
    nome_pasta = re.sub(r'_+', '_', nome_pasta).strip('_').lower()
    
    # Fallback final de segurança caso o slug fique vazio
    if not nome_pasta:
        nome_pasta = "projeto_ia"
    
    # Limita o tamanho do nome da pasta para evitar caminhos longos demais no Windows
    nome_pasta = nome_pasta[:40]
    
    # 3. Define onde a Fábrica vai salvar os projetos
    caminho_base = os.path.join(os.getcwd(), "projetos_gerados", nome_pasta)
    
    # 4. Cria a pasta física no Windows
    os.makedirs(caminho_base, exist_ok=True)
    
    # 5. Define o nome do arquivo com Timestamp para versionamento
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    nome_arquivo = f"01_arquitetura_{timestamp}.json"
    caminho_completo = os.path.join(caminho_base, nome_arquivo)
    
    # 6. Grava fisicamente no HD
    with open(caminho_completo, "w", encoding="utf-8") as arquivo:
        json.dump(plano_json, arquivo, indent=4, ensure_ascii=False)
        
    return caminho_completo