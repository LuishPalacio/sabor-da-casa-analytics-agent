# Analytics Agent: Sabor da Casa

Agente de análise de dados via CLI para um restaurante fictício. Você pergunta em português ("qual prato mais vendeu no último trimestre?") e o agente consulta os dados, calcula e responde. Também gera gráficos e faz previsão de faturamento com machine learning.

Projeto irmão do [emporio-da-musica-agent](https://github.com/LuishPalacio/emporio-da-musica-agent), com o mesmo padrão: o LLM (Groq) **só escolhe ferramentas fixas**. Todo o SQL é escrito e parametrizado em Python.

## Arquitetura (custo zero)

A ideia original era usar AWS. Cada serviço foi trocado por um equivalente local e gratuito:

| Papel | Na AWS | Aqui |
|---|---|---|
| Armazenamento dos dados | S3 | Pasta `data/` com CSVs |
| Catálogo e consultas SQL | Glue Data Catalog + Athena | **DuckDB** (SQL direto sobre os CSVs, sem servidor) |
| Dashboards e gráficos | QuickSight | **matplotlib** (PNGs em `outputs/`) |
| Machine learning | SageMaker | **scikit-learn** (previsão de faturamento) |
| Execução | EC2 | Seu computador |
| LLM | Bedrock | **Groq** (`openai/gpt-oss-120b`, plano gratuito) |

```
pergunta ─► Agente (Groq) ─► escolhe ferramenta ─► Python executa SQL fixo no DuckDB
                ▲                                         │
                └──────── resultado em JSON (R$ já formatado) ◄┘
```

## Dados

Gerados por `analytics_agent/gerar_dados.py` com seed fixa (sempre os mesmos números). Cobrem de 01/01/2025 a 31/10/2026, com cerca de 30 mil pedidos e 160 mil itens.

| Tabela | Conteúdo |
|---|---|
| `cardapio` | 27 pratos em 5 categorias, com preço e custo de ingredientes |
| `garcons` | 6 garçons com data de admissão |
| `pedidos` | data e hora, mesa, garçom, canal (salao, delivery, retirada), pagamento, número de pessoas |
| `itens_pedido` | pratos, quantidades e preço de cada pedido |

Os dados têm padrões propositais para o agente descobrir:

- crescimento ao longo do tempo;
- sexta e sábado mais cheios;
- feijoada concentrada em quarta e sábado no almoço;
- picanha forte no jantar de fim de semana;
- dezembro e julho mais fortes;
- restaurante fechado em 25/12 e 01/01;
- um garçom admitido em março de 2026.

## Ferramentas do agente

| Ferramenta | O que responde |
|---|---|
| `resumo_faturamento` | Faturamento, pedidos, pessoas, ticket médio e margem bruta de um período ou canal |
| `ranking_itens` | Itens mais e menos vendidos por quantidade, faturamento ou margem. O padrão considera só pratos de refeição (principais e massas); bebidas, comidas em geral ou o cardápio inteiro entram sob demanda |
| `vendas_por_categoria` | Participação e margem de cada categoria |
| `desempenho_garcons` | Pedidos, pessoas, faturamento e ticket médio por garçom |
| `serie_temporal` | Evolução de faturamento, pedidos, ticket médio ou quantidade por dia, semana, mês, dia da semana ou hora. Pode filtrar por um prato (aceita trecho do nome, como "feijoada") ou por categoria, e gerar gráfico |
| `distribuicao_vendas` | Divisão por canal ou por forma de pagamento |
| `prever_faturamento` | Previsão para até 90 dias (Ridge com tendência, dia da semana e mês), com gráfico opcional |
| `consultar_cardapio` | Preços, custos e margens do cardápio |

## Decisões técnicas

Cada uma veio de um problema real encontrado nos testes com o Groq. O detalhe de cada correção está no [CHANGELOG.md](CHANGELOG.md).

- **O LLM nunca escreve SQL.** Ele só escolhe uma ferramenta e os parâmetros; o Python valida tudo (datas, opções, limites) e devolve `{"erro": ...}` em linguagem simples quando algo está errado.
- **Todo número sai formatado do Python** ("R$ 1.234,50", "8.032"). O modelo só copia, sem fazer contas nem arredondar.
- **"Prato" é refeição.** Rankings consideram pratos principais e massas por padrão. Bebidas, entradas e sobremesas só entram quando a pergunta pedir.
- **Parâmetros opcionais aceitam `null` no schema.** O Groq valida as chamadas de ferramenta, e o modelo às vezes manda `null` em parâmetros opcionais.
- **O histórico guarda só perguntas e respostas finais.** Levar as chamadas de ferramenta e os JSONs de perguntas anteriores fazia o `gpt-oss` gerar lixo ("Oops…", "---", tabelas cortadas). As respostas finais já trazem período e números, o que basta para perguntas de continuação como "e no mês anterior?".
- **A resposta passa por uma limpeza** (`limpar_texto`). O modelo usa espaços Unicode (U+202F, U+00A0) que o terminal do Windows mostra como "?", então eles são trocados por espaço comum, ou por ponto quando separam milhar.
- **Temperatura 0.2.** Num teste comparativo, a temperatura 1 piorou a degeneração.

## Como rodar

Requisitos: Python 3.11+ e uma chave gratuita do Groq ([console.groq.com/keys](https://console.groq.com/keys)).

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt

copy .env.example .env      # depois edite e coloque sua GROQ_API_KEY
python -m analytics_agent.gerar_dados

python -m analytics_agent                 # modo interativo
python -m analytics_agent "qual foi o faturamento de outubro de 2026?"
python -m analytics_agent -v "..."        # mostra as ferramentas chamadas
```

No modo interativo, `/limpar` reinicia a conversa e `sair` encerra.

> **Atenção:** a chave vai no arquivo `.env`, que está no `.gitignore`. Nunca coloque a chave no `.env.example`, porque ele é publicado como modelo.

### Limite do plano gratuito do Groq

O `openai/gpt-oss-120b` no plano gratuito permite **8.000 tokens por minuto**, e cada chamada usa cerca de 2.000. Uma pergunta que chama duas ferramentas faz três chamadas. Na prática, dá para fazer de 1 a 3 perguntas por minuto.

Quando o limite estoura (erro 429), o cliente espera o tempo que o Groq informa e tenta de novo, até 5 vezes. Se mesmo assim não der, a CLI pede para aguardar uns 30 segundos.

### Perguntas de exemplo

- Quanto faturamos em outubro de 2026 comparado a outubro de 2025?
- Qual o prato mais vendido? E a bebida?
- Quais os 5 pratos com maior margem? E os 3 que menos vendem?
- Em que dia da semana a feijoada mais vende?
- Quais as sobremesas do cardápio? → Qual a mais pedida? → Quanto ela faturou em outubro de 2026?
- Qual garçom tem o maior ticket médio em 2026?
- Delivery ou salão: qual tem ticket médio maior?
- Me mostra um gráfico do faturamento mensal.
- Qual a previsão de faturamento para os próximos 30 dias? Gere o gráfico.

## Testes

São 17 testes, e nenhum chama o Groq: eles usam uma base pequena gerada na hora e um cliente LLM falso. Cobrem:
- conferência dos números contra as tabelas brutas;
- validações de entrada;
- ranking com e sem bebidas;
- filtro por prato;
- schemas aceitando `null`;
- limpeza do texto;
- loop do agente e histórico enxuto.

```powershell
pip install -r requirements-dev.txt
pytest
```

## Estrutura

```
analytics_agent/
  gerar_dados.py   geração dos CSVs fictícios
  db.py            carga dos CSVs no DuckDB com tipos explícitos + view "vendas"
  ferramentas.py   ferramentas fixas (SQL parametrizado) e definições para o LLM
  previsao.py      modelo de previsão (scikit-learn)
  graficos.py      gráficos PNG (matplotlib)
  agente.py        loop de function calling, histórico enxuto e limpeza da resposta
  cli.py           interface de linha de comando
tests/             testes das ferramentas e do loop do agente
```

## Limitações

- Os dados são fictícios.
- A margem usa o custo atual dos ingredientes, e não há histórico de mudança de preço.
- A previsão não considera feriados, eventos ou promoções.
- O agente responde apenas o que as ferramentas cobrem; perguntas fora disso são recusadas. Ele é um analista para o dono do restaurante, não um atendente: pedidos como "me recomenda um prato?" são recusados.
- O `gpt-oss` ainda pode, raramente, gerar uma resposta degenerada. Se acontecer, use `/limpar` e repita a pergunta.
- Com o limite gratuito do Groq, conversas longas e rápidas esbarram no limite de tokens por minuto.
