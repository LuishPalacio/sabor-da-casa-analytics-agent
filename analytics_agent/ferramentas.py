"""Ferramentas fixas do agente.

Todo o SQL fica aqui, parametrizado. O LLM só escolhe qual ferramenta chamar e
com quais parâmetros; ele nunca escreve SQL. Valores monetários saem já
formatados em reais para o modelo não precisar fazer contas nem arredondar.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

import duckdb

from . import graficos
from .previsao import prever_faturamento_diario

CANAIS = ("salao", "delivery", "retirada")
DIAS_SEMANA = {1: "segunda", 2: "terça", 3: "quarta", 4: "quinta", 5: "sexta", 6: "sábado", 7: "domingo"}
MAX_DIAS_SERIE_DIARIA = 93

AGRUPAMENTOS = {
    "dia": "data",
    "semana": "CAST(date_trunc('week', data) AS DATE)",
    "mes": "CAST(date_trunc('month', data) AS DATE)",
    "dia_semana": "isodow(data)",
    "hora": "hour(data_hora)",
}
METRICAS = {
    "faturamento": "SUM(receita)",
    "pedidos": "COUNT(DISTINCT pedido_id)",
    "ticket_medio": "SUM(receita) / COUNT(DISTINCT pedido_id)",
    "quantidade": "SUM(quantidade)",
}
METRICAS_INTEIRAS = ("pedidos", "quantidade")
# Posição da coluna no SELECT do ranking (evita ambiguidade entre alias e coluna da view).
ORDENACOES = {
    "quantidade": "3",
    "faturamento": "4",
    "margem": "5",
}
DIMENSOES = {"canal": "canal", "forma_pagamento": "forma_pagamento"}
# "prato" no uso comum é refeição: não inclui bebida, entrada nem sobremesa.
TIPOS_ITEM = {
    "pratos": ["Pratos principais", "Massas"],
    "comidas": ["Entradas", "Pratos principais", "Massas", "Sobremesas"],
    "bebidas": ["Bebidas"],
    "todos": [],
}


def brl(valor: Any) -> str:
    v = Decimal(str(valor)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def num(valor: Any) -> str:
    """Inteiro com separador de milhar brasileiro: 8032 -> "8.032"."""
    return f"{round(valor):,}".replace(",", ".")


def pct(parte: Any, total: Any) -> str:
    if not total:
        return "0,0%"
    return f"{float(parte) / float(total) * 100:.1f}%".replace(".", ",")


def data_br(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def _data(valor: Any, campo: str) -> date | None:
    if valor in (None, ""):
        return None
    try:
        return date.fromisoformat(str(valor))
    except ValueError:
        raise ValueError(f"{campo} deve estar no formato AAAA-MM-DD (recebido: {valor!r}).") from None


def _opcao(valor: Any, opcoes, campo: str, padrao: str | None = None) -> str | None:
    if valor in (None, ""):
        return padrao
    if valor not in opcoes:
        raise ValueError(f"{campo} inválido: {valor!r}. Opções: {', '.join(opcoes)}.")
    return valor


def _inteiro(valor: Any, campo: str, minimo: int, maximo: int, padrao: int) -> int:
    if valor in (None, ""):
        return padrao
    try:
        numero = int(valor)
    except (TypeError, ValueError):
        raise ValueError(f"{campo} deve ser um número inteiro.") from None
    if not minimo <= numero <= maximo:
        raise ValueError(f"{campo} deve estar entre {minimo} e {maximo}.")
    return numero


def _booleano(valor: Any) -> bool:
    if isinstance(valor, str):
        return valor.strip().lower() in ("true", "1", "sim")
    return bool(valor)


class Ferramentas:
    def __init__(self, con: duckdb.DuckDBPyConnection, pasta_saida: Path):
        self.con = con
        self.pasta_saida = pasta_saida
        self.data_min, self.data_max = con.execute("SELECT MIN(data), MAX(data) FROM pedidos").fetchone()
        self.categorias = [r[0] for r in con.execute(
            "SELECT DISTINCT categoria FROM cardapio ORDER BY categoria").fetchall()]
        self.pratos = [r[0] for r in con.execute("SELECT nome FROM cardapio ORDER BY nome").fetchall()]
        self._registro = {
            "resumo_faturamento": self.resumo_faturamento,
            "ranking_itens": self.ranking_itens,
            "vendas_por_categoria": self.vendas_por_categoria,
            "desempenho_garcons": self.desempenho_garcons,
            "serie_temporal": self.serie_temporal,
            "distribuicao_vendas": self.distribuicao_vendas,
            "prever_faturamento": self.prever_faturamento,
            "consultar_cardapio": self.consultar_cardapio,
        }

    # ------------------------------------------------------------------ infra

    def executar(self, nome: str, argumentos: str | dict | None) -> dict:
        funcao = self._registro.get(nome)
        if funcao is None:
            return {"erro": f"Ferramenta desconhecida: {nome}."}
        try:
            args = json.loads(argumentos or "{}") if isinstance(argumentos, str) else (argumentos or {})
        except json.JSONDecodeError:
            return {"erro": "Os argumentos da ferramenta não são um JSON válido."}
        if not isinstance(args, dict):
            return {"erro": "Os argumentos da ferramenta devem ser um objeto JSON."}
        try:
            return funcao(**args)
        except TypeError as exc:
            return {"erro": f"Parâmetros inválidos para {nome}: {exc}"}
        except ValueError as exc:
            return {"erro": str(exc)}

    def _periodo(self, data_inicio: Any, data_fim: Any) -> tuple[date, date]:
        inicio = _data(data_inicio, "data_inicio") or self.data_min
        fim = _data(data_fim, "data_fim") or self.data_max
        if inicio > fim:
            raise ValueError("data_inicio é posterior a data_fim.")
        return inicio, fim

    def _cabecalho(self, inicio: date, fim: date) -> dict:
        cabecalho = {"periodo": {"inicio": data_br(inicio), "fim": data_br(fim)}}
        if fim < self.data_min or inicio > self.data_max:
            cabecalho["aviso"] = (f"Não há dados nesse período. Os dados vão de {data_br(self.data_min)} "
                                  f"a {data_br(self.data_max)}.")
        return cabecalho

    def _categoria(self, valor: Any) -> str | None:
        if valor in (None, ""):
            return None
        for categoria in self.categorias:
            if categoria.lower() == str(valor).strip().lower():
                return categoria
        raise ValueError(f"Categoria inválida: {valor!r}. Opções: {', '.join(self.categorias)}.")

    def _prato(self, valor: Any) -> str | None:
        """Aceita o nome exato ou um trecho único dele ("feijoada" -> "Feijoada completa")."""
        if valor in (None, ""):
            return None
        busca = str(valor).strip().lower()
        exatos = [p for p in self.pratos if p.lower() == busca]
        parciais = [p for p in self.pratos if busca in p.lower()]
        if exatos or len(parciais) == 1:
            return (exatos or parciais)[0]
        if parciais:
            raise ValueError(f"Prato ambíguo: {valor!r}. Pode ser: {', '.join(parciais)}.")
        raise ValueError(f"Prato não encontrado: {valor!r}. Use consultar_cardapio para ver os nomes.")

    # ------------------------------------------------------------- ferramentas

    def resumo_faturamento(self, data_inicio=None, data_fim=None, canal=None) -> dict:
        inicio, fim = self._periodo(data_inicio, data_fim)
        canal = _opcao(canal, CANAIS, "canal")
        filtro, params = "data BETWEEN ? AND ?", [inicio, fim]
        if canal:
            filtro += " AND canal = ?"
            params.append(canal)

        faturamento, custo, itens = self.con.execute(
            f"SELECT COALESCE(SUM(receita), 0), COALESCE(SUM(custo), 0), COALESCE(SUM(quantidade), 0) "
            f"FROM vendas WHERE {filtro}", params).fetchone()
        pedidos, pessoas = self.con.execute(
            f"SELECT COUNT(*), COALESCE(SUM(num_pessoas), 0) FROM pedidos WHERE {filtro}", params).fetchone()
        dias = (fim - inicio).days + 1

        return {
            **self._cabecalho(inicio, fim),
            "canal": canal or "todos",
            "pedidos": num(pedidos),
            "pessoas_atendidas": num(pessoas),
            "itens_vendidos": num(itens),
            "faturamento": brl(faturamento),
            "custo_ingredientes": brl(custo),
            "margem_bruta": brl(faturamento - custo),
            "margem_bruta_percentual": pct(faturamento - custo, faturamento),
            "ticket_medio_por_pedido": brl(faturamento / pedidos if pedidos else 0),
            "faturamento_medio_por_dia": brl(faturamento / dias),
        }

    def ranking_itens(self, data_inicio=None, data_fim=None, tipo=None, ordenar_por=None, ordem=None,
                      categoria=None, limite=None) -> dict:
        inicio, fim = self._periodo(data_inicio, data_fim)
        tipo = _opcao(tipo, TIPOS_ITEM, "tipo", "pratos")
        ordenar_por = _opcao(ordenar_por, ORDENACOES, "ordenar_por", "quantidade")
        ordem = _opcao(ordem, ("melhores", "piores"), "ordem", "melhores")
        categoria = self._categoria(categoria)
        limite = _inteiro(limite, "limite", 1, 30, 10)

        # Categoria explícita tem prioridade sobre o tipo.
        categorias = [categoria] if categoria else TIPOS_ITEM[tipo]
        params: list = [inicio, fim]
        filtro_categoria = ""
        if categorias:
            filtro_categoria = f"WHERE c.categoria IN ({', '.join('?' * len(categorias))})"
            params.extend(categorias)
        params.append(limite)
        direcao = "DESC" if ordem == "melhores" else "ASC"

        linhas = self.con.execute(f"""
            SELECT c.nome, c.categoria,
                   COALESCE(SUM(v.quantidade), 0) AS quantidade,
                   COALESCE(SUM(v.receita), 0) AS faturamento,
                   COALESCE(SUM(v.receita) - SUM(v.custo), 0) AS margem
            FROM cardapio c
            LEFT JOIN vendas v ON v.prato_id = c.prato_id AND v.data BETWEEN ? AND ?
            {filtro_categoria}
            GROUP BY c.nome, c.categoria
            ORDER BY {ORDENACOES[ordenar_por]} {direcao}, c.nome
            LIMIT ?""", params).fetchall()

        return {
            **self._cabecalho(inicio, fim),
            "criterio": f"{ordem} por {ordenar_por}",
            "itens_considerados": categoria or f"{tipo} ({', '.join(TIPOS_ITEM[tipo]) or 'cardápio inteiro'})",
            "itens": [
                {"posicao": i, "item": nome, "categoria": cat, "quantidade": num(qtd),
                 "faturamento": brl(fat), "margem_bruta": brl(margem)}
                for i, (nome, cat, qtd, fat, margem) in enumerate(linhas, start=1)
            ],
        }

    def vendas_por_categoria(self, data_inicio=None, data_fim=None) -> dict:
        inicio, fim = self._periodo(data_inicio, data_fim)
        linhas = self.con.execute("""
            SELECT categoria, SUM(quantidade), SUM(receita), SUM(receita) - SUM(custo)
            FROM vendas WHERE data BETWEEN ? AND ?
            GROUP BY categoria ORDER BY SUM(receita) DESC""", [inicio, fim]).fetchall()
        total = sum(linha[2] for linha in linhas)
        return {
            **self._cabecalho(inicio, fim),
            "faturamento_total": brl(total),
            "categorias": [
                {"categoria": cat, "itens_vendidos": num(qtd), "faturamento": brl(fat),
                 "participacao_no_faturamento": pct(fat, total),
                 "margem_bruta": brl(margem), "margem_bruta_percentual": pct(margem, fat)}
                for cat, qtd, fat, margem in linhas
            ],
        }

    def desempenho_garcons(self, data_inicio=None, data_fim=None) -> dict:
        inicio, fim = self._periodo(data_inicio, data_fim)
        linhas = self.con.execute("""
            WITH totais AS (
                SELECT pedido_id, SUM(receita) AS valor FROM vendas
                WHERE data BETWEEN ? AND ? AND canal = 'salao' GROUP BY pedido_id)
            SELECT g.nome, g.data_admissao, COUNT(*), SUM(t.valor), SUM(p.num_pessoas)
            FROM totais t
            JOIN pedidos p USING (pedido_id)
            JOIN garcons g USING (garcom_id)
            GROUP BY g.nome, g.data_admissao
            ORDER BY SUM(t.valor) DESC""", [inicio, fim]).fetchall()
        return {
            **self._cabecalho(inicio, fim),
            "observacao": "Considera apenas pedidos do salão (delivery e retirada não têm garçom).",
            "garcons": [
                {"garcom": nome, "admitido_em": data_br(admissao), "pedidos_atendidos": num(pedidos),
                 "pessoas_atendidas": num(pessoas), "faturamento": brl(fat),
                 "ticket_medio_por_pedido": brl(fat / pedidos)}
                for nome, admissao, pedidos, fat, pessoas in linhas
            ],
        }

    def serie_temporal(self, metrica=None, agrupamento=None, data_inicio=None, data_fim=None,
                       prato=None, categoria=None, gerar_grafico=False) -> dict:
        inicio, fim = self._periodo(data_inicio, data_fim)
        metrica = _opcao(metrica, METRICAS, "metrica", "faturamento")
        agrupamento = _opcao(agrupamento, AGRUPAMENTOS, "agrupamento", "mes")
        prato = self._prato(prato)
        categoria = self._categoria(categoria)
        if agrupamento == "dia" and (fim - inicio).days + 1 > MAX_DIAS_SERIE_DIARIA:
            raise ValueError(f"Agrupamento por dia aceita no máximo {MAX_DIAS_SERIE_DIARIA} dias. "
                             "Reduza o período ou use agrupamento 'semana' ou 'mes'.")

        filtro, params = "data BETWEEN ? AND ?", [inicio, fim]
        if prato:
            filtro += " AND prato = ?"
            params.append(prato)
        if categoria:
            filtro += " AND categoria = ?"
            params.append(categoria)
        # Dias com venda contam a partir de todos os pedidos, para a média por dia
        # da semana de um prato considerar também os dias em que ele não saiu.
        linhas = self.con.execute(f"""
            WITH dias AS (
                SELECT {AGRUPAMENTOS[agrupamento]} AS grupo, COUNT(DISTINCT data) AS dias
                FROM pedidos WHERE data BETWEEN ? AND ? GROUP BY grupo)
            SELECT v.grupo, v.valor, d.dias
            FROM (SELECT {AGRUPAMENTOS[agrupamento]} AS grupo, {METRICAS[metrica]} AS valor
                  FROM vendas WHERE {filtro} GROUP BY grupo) v
            JOIN dias d USING (grupo)
            ORDER BY v.grupo""", [inicio, fim, *params]).fetchall()

        def rotulo(grupo) -> str:
            if agrupamento == "dia":
                return data_br(grupo)
            if agrupamento == "semana":
                return f"semana de {data_br(grupo)}"
            if agrupamento == "mes":
                return grupo.strftime("%m/%Y")
            if agrupamento == "dia_semana":
                return DIAS_SEMANA[grupo]
            return f"{grupo:02d}h"

        formatar = num if metrica in METRICAS_INTEIRAS else brl
        pontos = []
        for grupo, valor, dias in linhas:
            ponto = {"periodo": rotulo(grupo), metrica: formatar(valor)}
            if agrupamento == "dia_semana" and metrica != "ticket_medio":
                ponto["media_por_dia"] = formatar(Decimal(str(valor)) / dias)
                ponto["dias_no_periodo"] = dias
            pontos.append(ponto)

        resultado = {**self._cabecalho(inicio, fim), "metrica": metrica, "agrupamento": agrupamento,
                     "prato": prato or "todos", "categoria": categoria or "todas", "pontos": pontos}
        if agrupamento in ("dia_semana", "hora"):
            resultado["observacao"] = "Os valores de cada grupo são somados no período inteiro."
        if _booleano(gerar_grafico) and linhas:
            resultado["grafico"] = graficos.grafico_serie(
                self.pasta_saida, f"{metrica}_por_{agrupamento}",
                f"{metrica.replace('_', ' ').capitalize()} por {agrupamento.replace('_', ' ')}"
                f"{f' - {prato}' if prato else ''}{f' - {categoria}' if categoria else ''} "
                f"({data_br(inicio)} a {data_br(fim)})",
                [p["periodo"] for p in pontos], [float(linha[1]) for linha in linhas],
                metrica if metrica in METRICAS_INTEIRAS else "R$",
                linha=agrupamento in ("dia", "semana", "mes"))
        return resultado

    def distribuicao_vendas(self, dimensao=None, data_inicio=None, data_fim=None) -> dict:
        inicio, fim = self._periodo(data_inicio, data_fim)
        dimensao = _opcao(dimensao, DIMENSOES, "dimensao", "canal")
        coluna = DIMENSOES[dimensao]
        linhas = self.con.execute(f"""
            SELECT {coluna}, COUNT(DISTINCT pedido_id), SUM(receita)
            FROM vendas WHERE data BETWEEN ? AND ?
            GROUP BY {coluna} ORDER BY SUM(receita) DESC""", [inicio, fim]).fetchall()
        total = sum(linha[2] for linha in linhas)
        return {
            **self._cabecalho(inicio, fim),
            "dimensao": dimensao,
            "grupos": [
                {dimensao: valor, "pedidos": num(pedidos), "faturamento": brl(fat),
                 "participacao_no_faturamento": pct(fat, total), "ticket_medio_por_pedido": brl(fat / pedidos)}
                for valor, pedidos, fat in linhas
            ],
        }

    def prever_faturamento(self, dias=None, gerar_grafico=False) -> dict:
        dias = _inteiro(dias, "dias", 1, 90, 30)
        historico = {d: float(v) for d, v in self.con.execute(
            "SELECT data, SUM(receita) FROM vendas GROUP BY data").fetchall()}
        previsao = prever_faturamento_diario(historico, dias)

        # Blocos de 7 dias a partir do início da previsão (o último pode ser menor).
        blocos: dict[int, list[tuple[date, float]]] = defaultdict(list)
        for i, (d, valor) in enumerate(zip(previsao.datas, previsao.valores)):
            blocos[i // 7].append((d, valor))

        resultado = {
            "historico_usado": {"inicio": data_br(self.data_min), "fim": data_br(self.data_max)},
            "periodo_previsto": {"inicio": data_br(previsao.datas[0]), "fim": data_br(previsao.datas[-1])},
            "faturamento_previsto_total": brl(sum(previsao.valores)),
            "faturamento_previsto_medio_por_dia": brl(sum(previsao.valores) / dias),
            "por_semana": [
                {"periodo": f"{data_br(bloco[0][0])} a {data_br(bloco[-1][0])}",
                 "faturamento_previsto": brl(sum(v for _, v in bloco))}
                for bloco in blocos.values()
            ],
            "erro_medio_na_validacao": pct(previsao.erro_medio_validacao, 1),
            "metodo": ("Regressão linear (Ridge) com tendência, dia da semana e mês, treinada no histórico "
                       "diário. O erro de validação foi medido nos últimos 28 dias do histórico. "
                       "Não considera feriados, eventos ou promoções."),
        }
        if _booleano(gerar_grafico):
            corte = self.data_max - timedelta(days=89)
            recentes = sorted((d, v) for d, v in historico.items() if d >= corte)
            resultado["grafico"] = graficos.grafico_previsao(
                self.pasta_saida, [d for d, _ in recentes], [v for _, v in recentes],
                previsao.datas, previsao.valores)
        return resultado

    def consultar_cardapio(self, categoria=None) -> dict:
        categoria = self._categoria(categoria)
        sql = "SELECT nome, categoria, preco, custo FROM cardapio"
        params: list = []
        if categoria:
            sql += " WHERE categoria = ?"
            params.append(categoria)
        linhas = self.con.execute(sql + " ORDER BY categoria, nome", params).fetchall()
        return {
            "pratos": [
                {"prato": nome, "categoria": cat, "preco": brl(preco), "custo_ingredientes": brl(custo),
                 "margem_percentual": pct(preco - custo, preco)}
                for nome, cat, preco, custo in linhas
            ],
        }


def _periodo_props() -> dict:
    return {
        "data_inicio": {"type": "string", "description": "Data inicial no formato AAAA-MM-DD. Omita para usar o início dos dados."},
        "data_fim": {"type": "string", "description": "Data final no formato AAAA-MM-DD (inclusiva). Omita para usar o fim dos dados."},
    }


def _tool(nome: str, descricao: str, propriedades: dict, obrigatorios: list[str] | None = None) -> dict:
    obrigatorios = obrigatorios or []
    # O modelo às vezes envia null em parâmetros opcionais, e o Groq rejeita a chamada
    # se o schema não permitir. O Python já trata None como "usar o padrão".
    for nome_param, prop in propriedades.items():
        if nome_param not in obrigatorios:
            prop["type"] = [prop["type"], "null"]
            if "enum" in prop:
                prop["enum"] = [*prop["enum"], None]
    return {"type": "function", "function": {
        "name": nome, "description": descricao,
        "parameters": {"type": "object", "properties": propriedades, "required": obrigatorios},
    }}


def definicoes_tools(categorias: list[str]) -> list[dict]:
    return [
        _tool("resumo_faturamento",
              "Faturamento, número de pedidos, pessoas atendidas, ticket médio e margem bruta de um período. "
              "Use também para comparar dois períodos (chame uma vez para cada).",
              {**_periodo_props(),
               "canal": {"type": "string", "enum": list(CANAIS), "description": "Filtra por canal de venda. Omita para todos."}}),
        _tool("ranking_itens",
              "Ranking dos itens do cardápio mais (ou menos) vendidos por quantidade, faturamento ou margem.",
              {**_periodo_props(),
               "tipo": {"type": "string", "enum": list(TIPOS_ITEM),
                        "description": "'pratos' = pratos principais e massas (padrão; use quando o usuário "
                                       "disser 'prato'). 'comidas' = tudo menos bebidas. 'bebidas'. "
                                       "'todos' = cardápio inteiro. Ignorado se 'categoria' for informada."},
               "ordenar_por": {"type": "string", "enum": list(ORDENACOES)},
               "ordem": {"type": "string", "enum": ["melhores", "piores"]},
               "categoria": {"type": "string", "enum": categorias},
               "limite": {"type": "integer", "minimum": 1, "maximum": 30}}),
        _tool("vendas_por_categoria",
              "Faturamento, itens vendidos, participação e margem por categoria do cardápio.",
              _periodo_props()),
        _tool("desempenho_garcons",
              "Pedidos atendidos, pessoas, faturamento e ticket médio por garçom (somente salão).",
              _periodo_props()),
        _tool("serie_temporal",
              "Evolução de uma métrica agrupada por dia, semana, mês, dia da semana ou hora, "
              "opcionalmente filtrada por um prato ou uma categoria (ex.: em que dia da semana um prato "
              "mais vende, vendas de bebidas por hora). Pode gerar um gráfico PNG.",
              {**_periodo_props(),
               "metrica": {"type": "string", "enum": list(METRICAS),
                           "description": "'quantidade' = itens vendidos; a mais indicada ao filtrar por prato."},
               "prato": {"type": "string",
                         "description": "Nome do prato ou trecho único dele (ex.: 'feijoada')."},
               "categoria": {"type": "string", "enum": categorias},
               "agrupamento": {"type": "string", "enum": list(AGRUPAMENTOS),
                               "description": f"'dia' aceita no máximo {MAX_DIAS_SERIE_DIARIA} dias."},
               "gerar_grafico": {"type": "boolean", "description": "true somente se o usuário pedir gráfico."}}),
        _tool("distribuicao_vendas",
              "Divisão de pedidos e faturamento por canal (salao, delivery, retirada) ou por forma de pagamento.",
              {**_periodo_props(),
               "dimensao": {"type": "string", "enum": list(DIMENSOES)}},
              ["dimensao"]),
        _tool("prever_faturamento",
              "Previsão do faturamento dos próximos dias após o fim dos dados, com modelo de machine learning.",
              {"dias": {"type": "integer", "minimum": 1, "maximum": 90},
               "gerar_grafico": {"type": "boolean", "description": "true somente se o usuário pedir gráfico."}}),
        _tool("consultar_cardapio",
              "Lista pratos do cardápio com preço atual, custo de ingredientes e margem.",
              {"categoria": {"type": "string", "enum": categorias}}),
    ]


def para_json(resultado: dict) -> str:
    return json.dumps(resultado, ensure_ascii=False, default=lambda o: o.isoformat()
                      if isinstance(o, (date, datetime)) else str(o))
