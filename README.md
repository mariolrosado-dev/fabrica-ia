# 🏭 Fábrica de IA (`fabrica-ia`)

Plataforma autônoma de engenharia de software assistida por inteligência artificial, projetada para orquestrar o ciclo de vida completo de desenvolvimento: desde a concepção da ideia até a especificação de arquitetura, geração de código em Python/FastAPI e validação automatizada por QA.

---

## 🚀 Arquitetura e Componentes

O ecossistema da Fábrica opera através de agentes especializados guiados pelo **Prompt Mestre V2.0**:
1. **Agente Arquiteto Sênior:** Converte requisitos em especificações técnicas estruturadas e contratos JSON.
2. **Agente Programador Sênior:** Produz e limpa o código-fonte de forma otimizada.
3. **Agente QA Sênior:** Gera suítes de testes automatizados e valida a estabilidade com `pytest` (20/20 validados).

---

## 🛠️ Tecnologias Utilizadas
* **Python** / **FastAPI**
* **Google GenAI SDK** (`gemini-2.5-flash`)
* **Pytest** para automação de testes
* **Git & GitHub** para versionamento de código

---

## 📦 Como Executar o Projeto Localmente

1. Clone o repositório:
   ```bash
   git clone [https://github.com/mariolrosado-dev/fabrica-ia.git](https://github.com/mariolrosado-dev/fabrica-ia.git)
   cd fabrica-ia