from datetime import date
from types import SimpleNamespace

import pytest

from analytics_agent.agente import Agente, limpar_texto
from analytics_agent.db import conectar
from analytics_agent.ferramentas import Ferramentas, brl, definicoes_tools, num
from analytics_agent.gerar_dados import gerar


@pytest.fixture(scope="module")
def ferramentas(tmp_path_factory):
    pasta = tmp_path_factory.mktemp("dados")
    gerar(pasta, date(2025, 1, 1), date(2025, 4, 30), seed=1)
    return Ferramentas(conectar(pasta), tmp_path_factory.mktemp("saida"))


def inteiro(texto: str) -> int:
    return int(texto.replace(".", ""))


def test_brl():
    assert brl(1234.5) == "R$ 1.234,50"
    assert brl(0) == "R$ 0,00"
    assert num(8032) == "8.032"
    assert num(12) == "12"


def test_resumo_bate_com_tabelas_brutas(ferramentas):
    esperado = ferramentas.con.execute(
        "SELECT SUM(quantidade * preco_unitario) FROM itens_pedido").fetchone()[0]
    pedidos = ferramentas.con.execute("SELECT COUNT(*) FROM pedidos").fetchone()[0]
    resumo = ferramentas.executar("resumo_faturamento", "{}")
    assert resumo["faturamento"] == brl(esperado)
    assert resumo["pedidos"] == num(pedidos)


def test_resumo_por_canal_soma_o_total(ferramentas):
    total = sum(int(ferramentas.executar("resumo_faturamento", {"canal": c})["pedidos"].replace(".", ""))
                for c in ("salao", "delivery", "retirada"))
    assert num(total) == ferramentas.executar("resumo_faturamento", {})["pedidos"]


def test_categorias_somam_100_porcento(ferramentas):
    resultado = ferramentas.executar("vendas_por_categoria", {})
    soma = sum(float(c["participacao_no_faturamento"].rstrip("%").replace(",", "."))
               for c in resultado["categorias"])
    assert soma == pytest.approx(100, abs=0.5)


def test_ranking_respeita_limite_ordem_e_categoria(ferramentas):
    melhores = ferramentas.executar("ranking_itens", {"limite": 3, "categoria": "sobremesas"})
    assert len(melhores["itens"]) == 3
    assert {p["categoria"] for p in melhores["itens"]} == {"Sobremesas"}
    quantidades = [inteiro(p["quantidade"]) for p in melhores["itens"]]
    assert quantidades == sorted(quantidades, reverse=True)

    piores = ferramentas.executar("ranking_itens", {"limite": 3, "ordem": "piores"})
    assert inteiro(piores["itens"][0]["quantidade"]) <= inteiro(piores["itens"][-1]["quantidade"])


def test_ranking_padrao_so_tem_pratos_de_refeicao(ferramentas):
    padrao = ferramentas.executar("ranking_itens", {"limite": 30})
    assert {p["categoria"] for p in padrao["itens"]} == {"Pratos principais", "Massas"}
    bebidas = ferramentas.executar("ranking_itens", {"tipo": "bebidas"})
    assert bebidas["itens"][0]["item"] == "Refrigerante lata"
    todos = ferramentas.executar("ranking_itens", {"tipo": "todos", "limite": 30})
    assert len(todos["itens"]) == 27


def test_feijoada_concentrada_em_quarta_e_sabado(ferramentas):
    por_dia = dict(ferramentas.con.execute("""
        SELECT isodow(data), SUM(quantidade) FROM vendas
        WHERE prato = 'Feijoada completa' GROUP BY 1""").fetchall())
    assert por_dia[3] > 2 * por_dia[2] and por_dia[6] > 2 * por_dia[2]


def test_serie_por_prato_e_dia_semana(ferramentas):
    resultado = ferramentas.executar("serie_temporal", {"agrupamento": "dia_semana", "metrica": "quantidade",
                                                        "prato": "feijoada"})
    assert resultado["prato"] == "Feijoada completa"
    por_dia = {p["periodo"]: inteiro(p["quantidade"]) for p in resultado["pontos"]}
    assert max(por_dia, key=por_dia.get) in ("quarta", "sábado")
    assert "erro" in ferramentas.executar("serie_temporal", {"prato": "pizza"})
    assert "erro" in ferramentas.executar("serie_temporal", {"prato": "de"})  # ambíguo


def test_serie_mensal_e_grafico(ferramentas):
    resultado = ferramentas.executar("serie_temporal", {"agrupamento": "mes", "gerar_grafico": True})
    assert [p["periodo"] for p in resultado["pontos"]] == ["01/2025", "02/2025", "03/2025", "04/2025"]
    assert resultado["grafico"].endswith(".png")


def test_serie_diaria_longa_vira_erro(ferramentas):
    resultado = ferramentas.executar("serie_temporal", {"agrupamento": "dia"})
    assert "erro" in resultado


def test_validacoes(ferramentas):
    assert "erro" in ferramentas.executar("resumo_faturamento", {"data_inicio": "01/02/2025"})
    assert "erro" in ferramentas.executar("resumo_faturamento", {"canal": "drive-thru"})
    assert "erro" in ferramentas.executar("resumo_faturamento",
                                          {"data_inicio": "2025-03-01", "data_fim": "2025-02-01"})
    assert "erro" in ferramentas.executar("ranking_itens", {"limite": 500})
    assert "erro" in ferramentas.executar("ranking_itens", {"tipo": "lanches"})
    assert "erro" in ferramentas.executar("ferramenta_inexistente", {})
    assert "erro" in ferramentas.executar("resumo_faturamento", "não é json")
    assert "aviso" in ferramentas.executar("resumo_faturamento",
                                           {"data_inicio": "2030-01-01", "data_fim": "2030-01-31"})


def test_garcons_so_salao_e_admissao(ferramentas):
    nomes = {g["garcom"] for g in ferramentas.executar("desempenho_garcons", {})["garcons"]}
    assert "Felipe Nunes" not in nomes  # admitido em 2026
    assert "Ana Souza" in nomes


def test_previsao(ferramentas):
    resultado = ferramentas.executar("prever_faturamento", {"dias": 14, "gerar_grafico": True})
    assert resultado["periodo_previsto"] == {"inicio": "01/05/2025", "fim": "14/05/2025"}
    assert resultado["grafico"].endswith(".png")


def test_parametros_opcionais_aceitam_null(ferramentas):
    for tool in definicoes_tools(ferramentas.categorias):
        parametros = tool["function"]["parameters"]
        for nome, prop in parametros["properties"].items():
            if nome not in parametros["required"]:
                assert "null" in prop["type"], (tool["function"]["name"], nome)
                assert "enum" not in prop or None in prop["enum"]
    assert "pratos" in ferramentas.executar("consultar_cardapio", {"categoria": None})


def test_limpar_texto_remove_unicode_e_lixo():
    bruto = "**\xa0\xa0**\n\n\n\n**Bebida:** Refrigerante ‑ R$ 184.480,80"
    assert limpar_texto(bruto) == "**Bebida:** Refrigerante - R$ 184.480,80"
    assert limpar_texto("Pudim (8 032 unidades, 12 345 678 no total)") == \
        "Pudim (8.032 unidades, 12.345.678 no total)"


def _mensagem(conteudo=None, chamadas=None):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=conteudo, tool_calls=chamadas))])


class ClienteFalso:
    """Simula o Groq: primeiro pede uma ferramenta, depois responde com texto."""

    def __init__(self):
        self.requisicoes = []
        chamada = SimpleNamespace(id="c1", function=SimpleNamespace(
            name="resumo_faturamento", arguments='{"data_inicio": "2025-03-01", "data_fim": "2025-03-31"}'))
        self.respostas = [_mensagem(chamadas=[chamada]), _mensagem("Faturamento de março: ...")]
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._criar))

    def _criar(self, **kwargs):
        self.requisicoes.append(kwargs)
        return self.respostas.pop(0)


def test_agente_executa_ferramenta_e_guarda_historico(ferramentas):
    cliente = ClienteFalso()
    agente = Agente(ferramentas, cliente, "modelo-teste")
    resposta = agente.perguntar("Quanto faturamos em março?")

    assert resposta.texto == "Faturamento de março: ..."
    assert resposta.chamadas[0][0] == "resumo_faturamento"
    resultado_tool = cliente.requisicoes[1]["messages"][-1]
    assert resultado_tool["role"] == "tool" and '"faturamento"' in resultado_tool["content"]
    # Dentro da pergunta o modelo recebe o resultado da ferramenta, mas o histórico
    # guardado para as próximas perguntas tem só a pergunta e a resposta final.
    assert agente.historico == [{"role": "user", "content": "Quanto faturamos em março?"},
                                {"role": "assistant", "content": "Faturamento de março: ..."}]


def test_historico_limitado():
    agente = Agente.__new__(Agente)
    agente.historico, agente.max_mensagens_historico = [], 4
    for i in range(5):
        agente._guardar(f"p{i}", f"r{i}")
    assert [m["content"] for m in agente.historico] == ["p3", "r3", "p4", "r4"]
