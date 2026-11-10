"""Interface de linha de comando.

Uso:
    python -m analytics_agent                      # modo interativo
    python -m analytics_agent "qual foi o faturamento de outubro?"
    python -m analytics_agent -v "..."             # mostra as ferramentas chamadas
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI, OpenAIError, RateLimitError

from .agente import Agente
from .db import conectar
from .ferramentas import Ferramentas

RAIZ = Path(__file__).resolve().parent.parent
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
MODELO_PADRAO = "openai/gpt-oss-120b"


def _responder(agente: Agente, pergunta: str, verbose: bool) -> None:
    try:
        resposta = agente.perguntar(pergunta)
    except RateLimitError:
        print("\n[limite do Groq] O plano gratuito permite poucas chamadas por minuto e as novas tentativas "
              "automáticas não bastaram. Aguarde uns 30 segundos e pergunte de novo.\n", file=sys.stderr)
        return
    except OpenAIError as exc:
        print(f"\n[erro na API do Groq] {exc}\n", file=sys.stderr)
        return
    if verbose:
        for nome, argumentos in resposta.chamadas:
            print(f"  -> {nome}({argumentos})")
    print(f"\n{resposta.texto}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m analytics_agent",
                                     description="Agente de análise de dados do restaurante Sabor da Casa.")
    parser.add_argument("pergunta", nargs="?", help="Pergunta única. Sem ela, abre o modo interativo.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Mostra as ferramentas chamadas.")
    args = parser.parse_args(argv)
    for fluxo in (sys.stdout, sys.stderr):
        fluxo.reconfigure(encoding="utf-8")

    load_dotenv(RAIZ / ".env")
    chave = os.getenv("GROQ_API_KEY")
    if not chave:
        print("Defina GROQ_API_KEY no arquivo .env (crie a chave em https://console.groq.com/keys).",
              file=sys.stderr)
        return 1

    pasta_dados = Path(os.getenv("PASTA_DADOS", RAIZ / "data"))
    pasta_saida = Path(os.getenv("PASTA_SAIDA", RAIZ / "outputs"))
    try:
        ferramentas = Ferramentas(conectar(pasta_dados), pasta_saida)
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 1

    # O plano gratuito do Groq limita tokens por minuto; o SDK repete a chamada
    # respeitando o tempo de espera que o Groq informa no erro 429.
    cliente = OpenAI(api_key=chave, base_url=GROQ_BASE_URL, max_retries=5)
    agente = Agente(ferramentas, cliente, os.getenv("GROQ_MODEL", MODELO_PADRAO))

    if args.pergunta:
        _responder(agente, args.pergunta, args.verbose)
        return 0

    print("Analista do Sabor da Casa. Digite sua pergunta, '/limpar' para nova conversa ou 'sair'.\n")
    while True:
        try:
            pergunta = input("você> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not pergunta:
            continue
        if pergunta.lower() in ("sair", "exit", "quit"):
            return 0
        if pergunta == "/limpar":
            agente.limpar()
            print("Conversa reiniciada.\n")
            continue
        _responder(agente, pergunta, args.verbose)
