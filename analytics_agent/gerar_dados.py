"""Gera dados fictícios de vendas do restaurante "Sabor da Casa".

Uso: python -m analytics_agent.gerar_dados [--inicio AAAA-MM-DD] [--fim AAAA-MM-DD] [--seed N]

Os dados têm padrões propositais para o agente encontrar: crescimento ao longo do
tempo, sexta e sábado mais cheios, feijoada concentrada em quarta e sábado,
dezembro e julho mais fortes, restaurante fechado em 25/12 e 01/01.
"""

from __future__ import annotations

import argparse
import csv
import random
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

PASTA_PADRAO = Path(__file__).resolve().parent.parent / "data"

# (categoria, [(nome, preço, popularidade)])
CARDAPIO = [
    ("Entradas", [
        ("Bolinho de bacalhau (6 un.)", "38.90", 1.4),
        ("Pão de alho", "19.90", 1.2),
        ("Carpaccio", "44.90", 0.6),
        ("Bruschetta de tomate", "29.90", 0.8),
        ("Mandioca frita", "24.90", 1.3),
    ]),
    ("Pratos principais", [
        ("Picanha na brasa", "119.90", 1.5),
        ("Filé à parmegiana", "79.90", 1.8),
        ("Moqueca de peixe", "98.90", 0.7),
        ("Frango grelhado com legumes", "54.90", 1.1),
        ("Feijoada completa", "69.90", 1.0),
        ("Risoto de cogumelos", "64.90", 0.6),
        ("Salmão ao molho de maracujá", "89.90", 0.8),
        ("Strogonoff de carne", "59.90", 1.3),
    ]),
    ("Massas", [
        ("Espaguete à carbonara", "58.90", 1.1),
        ("Lasanha à bolonhesa", "56.90", 1.2),
        ("Nhoque ao sugo", "49.90", 0.7),
        ("Fettuccine ao pesto", "54.90", 0.5),
    ]),
    ("Sobremesas", [
        ("Pudim de leite", "18.90", 1.5),
        ("Petit gâteau", "29.90", 1.3),
        ("Mousse de maracujá", "17.90", 0.9),
        ("Cheesecake de frutas vermelhas", "26.90", 0.7),
    ]),
    ("Bebidas", [
        ("Refrigerante lata", "7.90", 1.6),
        ("Suco natural", "12.90", 1.3),
        ("Água mineral", "5.90", 1.0),
        ("Cerveja long neck", "14.90", 1.2),
        ("Caipirinha", "24.90", 0.8),
        ("Taça de vinho tinto", "32.90", 0.5),
    ]),
]

# (nome, data de admissão)
GARCONS = [
    ("Ana Souza", date(2023, 5, 2)),
    ("Bruno Lima", date(2024, 1, 15)),
    ("Carla Mendes", date(2022, 9, 1)),
    ("Diego Rocha", date(2024, 8, 5)),
    ("Elisa Martins", date(2025, 6, 2)),
    ("Felipe Nunes", date(2026, 3, 2)),
]

FATOR_DIA_SEMANA = {0: 0.70, 1: 0.80, 2: 0.95, 3: 1.00, 4: 1.35, 5: 1.50, 6: 1.25}
FATOR_MES = {1: 0.90, 2: 0.92, 3: 0.97, 4: 1.00, 5: 1.05, 6: 1.05,
             7: 1.12, 8: 1.00, 9: 0.98, 10: 1.02, 11: 1.05, 12: 1.20}
FECHADO = {(12, 25), (1, 1)}
PEDIDOS_BASE_DIA = 38


def _escolher(rng: random.Random, opcoes: dict[str, float]) -> str:
    return rng.choices(list(opcoes), weights=list(opcoes.values()))[0]


def gerar(pasta: Path = PASTA_PADRAO, inicio: date = date(2025, 1, 1),
          fim: date = date(2026, 10, 31), seed: int = 42) -> dict[str, int]:
    """Gera os CSVs em `pasta` e devolve a quantidade de linhas de cada um."""
    rng = random.Random(seed)
    pasta.mkdir(parents=True, exist_ok=True)

    cardapio = []  # (prato_id, nome, categoria, preco, custo, popularidade)
    for categoria, itens in CARDAPIO:
        for nome, preco, popularidade in itens:
            custo = round(float(preco) * rng.uniform(0.28, 0.45), 2)
            cardapio.append((len(cardapio) + 1, nome, categoria, preco, f"{custo:.2f}", popularidade))
    por_categoria: dict[str, list[tuple]] = {}
    for prato in cardapio:
        por_categoria.setdefault(prato[2], []).append(prato)
    principais = por_categoria["Pratos principais"] + por_categoria["Massas"]

    def sortear(opcoes: list[tuple], dia: date, jantar: bool) -> tuple:
        pesos = []
        for prato in opcoes:
            peso = prato[5]
            if prato[1] == "Feijoada completa":
                peso *= 4.0 if dia.weekday() in (2, 5) and not jantar else 0.25
            elif prato[1] == "Picanha na brasa" and jantar and dia.weekday() >= 4:
                peso *= 1.8
            elif prato[1] in ("Caipirinha", "Cerveja long neck", "Taça de vinho tinto") and not jantar:
                peso *= 0.4
            pesos.append(peso)
        return rng.choices(opcoes, weights=pesos)[0]

    pedidos, itens_pedido = [], []
    total_dias = (fim - inicio).days + 1
    for n in range(total_dias):
        dia = inicio + timedelta(days=n)
        if (dia.month, dia.day) in FECHADO:
            continue
        crescimento = 1 + 0.18 * n / total_dias
        media = PEDIDOS_BASE_DIA * crescimento * FATOR_DIA_SEMANA[dia.weekday()] * FATOR_MES[dia.month]
        quantidade = max(0, round(rng.gauss(media, media * 0.10)))
        ativos = [i + 1 for i, (_, admissao) in enumerate(GARCONS) if admissao <= dia]

        for _ in range(quantidade):
            jantar = rng.random() < (0.62 if dia.weekday() >= 4 else 0.50)
            hora = rng.choice([18, 19, 19, 20, 20, 21, 22]) if jantar else rng.choice([11, 12, 12, 13, 13, 14])
            momento = datetime(dia.year, dia.month, dia.day, hora, rng.randrange(60))
            canal = _escolher(rng, {"salao": 0.65, "delivery": 0.25, "retirada": 0.10})
            if canal == "salao":
                pessoas = rng.choices([1, 2, 3, 4, 5, 6], weights=[8, 35, 20, 22, 8, 7])[0]
                mesa, garcom = rng.randint(1, 25), rng.choice(ativos)
                pagamento = _escolher(rng, {"pix": 0.30, "credito": 0.38, "debito": 0.22, "dinheiro": 0.10})
            else:
                pessoas = rng.choices([1, 2, 3], weights=[45, 40, 15])[0]
                mesa, garcom = "", ""
                pagamento = _escolher(rng, {"pix": 0.45, "credito": 0.40, "debito": 0.12, "dinheiro": 0.03})

            pratos: Counter = Counter()
            for _ in range(pessoas):
                if rng.random() < 0.92:
                    pratos[sortear(principais, dia, jantar)] += 1
                for _ in range(rng.choices([0, 1, 2], weights=[15, 65, 20])[0]):
                    pratos[sortear(por_categoria["Bebidas"], dia, jantar)] += 1
                if rng.random() < 0.30:
                    pratos[sortear(por_categoria["Sobremesas"], dia, jantar)] += 1
            if rng.random() < (0.45 if canal == "salao" else 0.20):
                pratos[sortear(por_categoria["Entradas"], dia, jantar)] += 1
            if not pratos:
                pratos[sortear(principais, dia, jantar)] += 1

            pedido_id = len(pedidos) + 1
            pedidos.append((pedido_id, momento.isoformat(sep=" ", timespec="minutes"),
                            mesa, garcom, canal, pagamento, pessoas))
            for prato, qtd in pratos.items():
                itens_pedido.append((len(itens_pedido) + 1, pedido_id, prato[0], qtd, prato[3]))

    tabelas = {
        "cardapio": (["prato_id", "nome", "categoria", "preco", "custo"], [p[:5] for p in cardapio]),
        "garcons": (["garcom_id", "nome", "data_admissao"],
                    [(i + 1, nome, adm.isoformat()) for i, (nome, adm) in enumerate(GARCONS)]),
        "pedidos": (["pedido_id", "data_hora", "mesa", "garcom_id", "canal", "forma_pagamento", "num_pessoas"],
                    pedidos),
        "itens_pedido": (["item_id", "pedido_id", "prato_id", "quantidade", "preco_unitario"], itens_pedido),
    }
    for nome, (cabecalho, linhas) in tabelas.items():
        with open(pasta / f"{nome}.csv", "w", newline="", encoding="utf-8") as arquivo:
            escritor = csv.writer(arquivo)
            escritor.writerow(cabecalho)
            escritor.writerows(linhas)
    return {nome: len(linhas) for nome, (_, linhas) in tabelas.items()}


def main() -> None:
    parser = argparse.ArgumentParser(description="Gera os CSVs fictícios do restaurante.")
    parser.add_argument("--pasta", type=Path, default=PASTA_PADRAO)
    parser.add_argument("--inicio", type=date.fromisoformat, default=date(2025, 1, 1))
    parser.add_argument("--fim", type=date.fromisoformat, default=date(2026, 10, 31))
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    contagem = gerar(args.pasta, args.inicio, args.fim, args.seed)
    for nome, linhas in contagem.items():
        print(f"{nome}.csv: {linhas} linhas")
    print(f"Arquivos gravados em {args.pasta}")


if __name__ == "__main__":
    main()
