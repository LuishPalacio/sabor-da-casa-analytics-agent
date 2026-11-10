"""Carrega os CSVs no DuckDB (o "Athena local") com tipos explícitos."""

from __future__ import annotations

from pathlib import Path

import duckdb

ESQUEMA = {
    "cardapio": {"prato_id": "INTEGER", "nome": "VARCHAR", "categoria": "VARCHAR",
                 "preco": "DECIMAL(10,2)", "custo": "DECIMAL(10,2)"},
    "garcons": {"garcom_id": "INTEGER", "nome": "VARCHAR", "data_admissao": "DATE"},
    "pedidos": {"pedido_id": "INTEGER", "data_hora": "TIMESTAMP", "mesa": "INTEGER", "garcom_id": "INTEGER",
                "canal": "VARCHAR", "forma_pagamento": "VARCHAR", "num_pessoas": "INTEGER"},
    "itens_pedido": {"item_id": "INTEGER", "pedido_id": "INTEGER", "prato_id": "INTEGER",
                     "quantidade": "INTEGER", "preco_unitario": "DECIMAL(10,2)"},
}

VIEW_VENDAS = """
CREATE VIEW vendas AS
SELECT i.pedido_id, p.data_hora, p.data, p.canal, p.forma_pagamento, p.garcom_id,
       i.prato_id, c.nome AS prato, c.categoria, i.quantidade,
       i.quantidade * i.preco_unitario AS receita,
       i.quantidade * c.custo AS custo
FROM itens_pedido i
JOIN pedidos p USING (pedido_id)
JOIN cardapio c USING (prato_id)
"""


def conectar(pasta_dados: Path) -> duckdb.DuckDBPyConnection:
    faltando = [f"{t}.csv" for t in ESQUEMA if not (pasta_dados / f"{t}.csv").exists()]
    if faltando:
        raise FileNotFoundError(
            f"Arquivos não encontrados em {pasta_dados}: {', '.join(faltando)}. "
            "Gere os dados com: python -m analytics_agent.gerar_dados"
        )
    con = duckdb.connect(":memory:")
    for tabela, colunas in ESQUEMA.items():
        caminho = (pasta_dados / f"{tabela}.csv").as_posix().replace("'", "''")
        tipos = ", ".join(f"'{nome}': '{tipo}'" for nome, tipo in colunas.items())
        extra = ", CAST(data_hora AS DATE) AS data" if tabela == "pedidos" else ""
        con.execute(f"CREATE TABLE {tabela} AS SELECT *{extra} "
                    f"FROM read_csv('{caminho}', header = true, columns = {{{tipos}}})")
    con.execute(VIEW_VENDAS)
    return con
