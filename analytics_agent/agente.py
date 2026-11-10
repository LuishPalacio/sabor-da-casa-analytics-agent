"""Loop do agente: LLM (Groq) escolhe ferramentas, Python executa e devolve os dados."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from .ferramentas import Ferramentas, data_br, definicoes_tools, para_json

# O gpt-oss costuma trocar espaços e hífens por variantes Unicode (U+202F, U+00A0,
# U+2011...) que muitos terminais Windows exibem como "?".
TROCAS_UNICODE = str.maketrans({
    " ": " ", " ": " ", " ": " ", " ": " ",
    "‐": "-", "‑": "-", "​": None, "﻿": None,
})


def limpar_texto(texto: str) -> str:
    # Separador de milhar trocado pelo modelo: "8 032" -> "8.032".
    texto = re.sub(r"(?<=\d)[   ](?=\d{3}\b)", ".", texto)
    texto = texto.translate(TROCAS_UNICODE)
    texto = re.sub(r"\*\*\s*\*\*", "", texto)    # negrito vazio, sintoma de saída degenerada
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto.strip()

PROMPT_SISTEMA = """Você é o analista de dados do restaurante fictício "Sabor da Casa" e responde em português do Brasil.

Hoje é {hoje}. Os dados de vendas vão de {inicio} a {fim}.
Categorias do cardápio: {categorias}. Canais de venda: salao, delivery, retirada.

Regras:
- Responda somente com números vindos das ferramentas. Nunca invente nem estime valores por conta própria.
- Valores em reais e quantidades já vêm formatados (ex.: "R$ 1.234,50", "8.032"); repita-os exatamente como recebidos, sem refazer contas nem trocar o separador.
- "Prato" significa refeição (pratos principais e massas). Bebidas, entradas e sobremesas não são pratos; inclua-as só quando o usuário pedir.
- Converta períodos relativos ("mês passado", "último trimestre") em datas AAAA-MM-DD considerando que os dados terminam em {fim}. Diga qual período usou.
- Para comparar períodos, chame a ferramenta uma vez para cada período e mostre a variação.
- Só gere gráfico quando o usuário pedir; quando gerar, informe o caminho do arquivo.
- Se a ferramenta devolver "erro" ou "aviso", explique ao usuário em linguagem simples.
- Se a pergunta não puder ser respondida com as ferramentas disponíveis, diga isso claramente.
- Seja direto: comece pela resposta e use tabelas curtas em Markdown quando houver vários itens."""


@dataclass
class Resposta:
    texto: str
    chamadas: list[tuple[str, str]] = field(default_factory=list)


class Agente:
    def __init__(self, ferramentas: Ferramentas, cliente, modelo: str,
                 max_rodadas: int = 8, max_mensagens_historico: int = 20):
        self.ferramentas = ferramentas
        self.cliente = cliente
        self.modelo = modelo
        self.max_rodadas = max_rodadas
        self.max_mensagens_historico = max_mensagens_historico
        self.tools = definicoes_tools(ferramentas.categorias)
        self.historico: list[dict] = []

    def _prompt_sistema(self) -> str:
        return PROMPT_SISTEMA.format(
            hoje=data_br(date.today()), inicio=data_br(self.ferramentas.data_min),
            fim=data_br(self.ferramentas.data_max), categorias=", ".join(self.ferramentas.categorias))

    def limpar(self) -> None:
        self.historico.clear()

    def perguntar(self, pergunta: str) -> Resposta:
        turno: list[dict] = [{"role": "user", "content": pergunta}]
        chamadas: list[tuple[str, str]] = []

        for _ in range(self.max_rodadas):
            mensagens = [{"role": "system", "content": self._prompt_sistema()}, *self.historico, *turno]
            resposta = self.cliente.chat.completions.create(
                model=self.modelo, messages=mensagens, tools=self.tools, tool_choice="auto", temperature=0.2)
            mensagem = resposta.choices[0].message

            if not mensagem.tool_calls:
                texto = limpar_texto(mensagem.content or "") or "Não consegui formular uma resposta."
                self._guardar(pergunta, texto)
                return Resposta(texto, chamadas)

            turno.append({
                "role": "assistant",
                "content": mensagem.content or "",
                "tool_calls": [
                    {"id": c.id, "type": "function",
                     "function": {"name": c.function.name, "arguments": c.function.arguments}}
                    for c in mensagem.tool_calls
                ],
            })
            for chamada in mensagem.tool_calls:
                chamadas.append((chamada.function.name, chamada.function.arguments))
                resultado = self.ferramentas.executar(chamada.function.name, chamada.function.arguments)
                turno.append({"role": "tool", "tool_call_id": chamada.id, "content": para_json(resultado)})

        texto = "Precisei de consultas demais para essa pergunta. Tente dividi-la em partes menores."
        self._guardar(pergunta, texto)
        return Resposta(texto, chamadas)

    def _guardar(self, pergunta: str, resposta: str) -> None:
        # Guarda só a pergunta e a resposta final. Levar as chamadas de ferramenta e os
        # JSONs para as próximas perguntas fazia o gpt-oss degenerar ("Oops…", "---",
        # tabelas cortadas) e gastava tokens do limite por minuto do Groq. A resposta
        # final já traz o período e os números, o que basta para perguntas de continuação.
        self.historico += [{"role": "user", "content": pergunta}, {"role": "assistant", "content": resposta}]
        del self.historico[:-self.max_mensagens_historico]
