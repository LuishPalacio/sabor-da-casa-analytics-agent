# Histórico de mudanças

Registro de tudo o que foi feito no projeto, em ordem cronológica. Cada correção diz qual problema foi visto, qual era a causa e o que mudou. Este arquivo é atualizado a cada correção ou atualização.

---

## 2026-11-10: Decisão de arquitetura (AWS → local)

**Contexto:** a ideia inicial era construir o agente sobre AWS (EC2, S3, Glue, Athena, QuickSight e SageMaker) sem nenhum custo.

**O que a pesquisa mostrou** (regras do Free Tier para contas criadas a partir de 15/07/2025):
- Só o Glue Data Catalog e o S3 têm uso gratuito permanente.
- Athena, EC2 e SageMaker seriam pagos com os créditos de entrada (US$100 + até US$100).
- O QuickSight só tem teste de 30 dias, e apenas no plano pago, que cobra no cartão quando os créditos acabam.

**Decisão:** não usar AWS. Foram criados os budgets de alerta, mas a conta foi encerrada logo depois, e cada serviço foi trocado por um equivalente local e gratuito:

| AWS | Local |
|---|---|
| S3 | CSVs em `data/` |
| Glue + Athena | DuckDB |
| QuickSight | matplotlib |
| SageMaker | scikit-learn |
| EC2 | computador local |
| Bedrock | Groq (`openai/gpt-oss-120b`) |

---

## 2026-11-10: Versão inicial

- **Gerador de dados fictícios** do restaurante "Sabor da Casa" (`gerar_dados.py`):
  - período de 01/01/2025 a 31/10/2026, com cerca de 30 mil pedidos e 160 mil itens;
  - seed fixa, para os números serem sempre os mesmos;
  - padrões propositais para o agente encontrar: feijoada em quarta e sábado, fim de semana mais cheio, crescimento ao longo do tempo, sazonalidade.
- **Carga dos CSVs no DuckDB** com tipos explícitos (`DECIMAL` para dinheiro) e uma view `vendas`.
- **8 ferramentas fixas** com SQL parametrizado. O LLM só escolhe a ferramenta e os parâmetros.
- **Previsão de faturamento** com Ridge (tendência, dia da semana e mês), com validação nos últimos 28 dias.
- **Gráficos PNG** em `outputs/`.
- **CLI** com modo interativo e pergunta única, e a opção `-v` para mostrar as ferramentas chamadas.
- **12 testes** sem chamar o Groq: base pequena gerada na hora e cliente LLM falso.

**Ajustes feitos durante a validação:**
- A previsão agrupava por semana do calendário, gerando blocos parciais confusos ("semana de 26/10" com um único dia). Passou a usar blocos de 7 dias a partir do início da previsão.
- A saída da CLI passou a ser forçada para UTF-8.

---

## 2026-11-10: Configuração da chave do Groq

- **Problema:** a chave foi colada no `.env.example`, mas a CLI lê o `.env`. Além disso, o `.env.example` não está no `.gitignore` e iria para o GitHub com a chave.
- **Feito:** o `.env` foi criado com a chave, e o README ganhou um aviso.
- **Resolvido depois** (ver "Repositório git"): o `.env.example` voltou para `GROQ_API_KEY=sua_chave_aqui` antes do primeiro commit, então a chave nunca entrou no histórico do git.

---

## 2026-11-10: Correção: pergunta sobre um prato por dia da semana

- **Problema:** para "em que dia da semana a feijoada mais vende?", o agente respondeu que não havia ferramenta para isso. Era uma das perguntas de exemplo do README.
- **Causa:** a `serie_temporal` não filtrava por prato.
- **Correção:** a `serie_temporal` ganhou:
  - os filtros `prato` e `categoria`; o prato aceita trecho do nome ("feijoada" encontra "Feijoada completa") e recusa trechos ambíguos;
  - a métrica `quantidade`.

  A média por dia da semana passou a considerar também os dias em que o prato não saiu.
- **Validação:** o agente respondeu "sábado" usando o filtro novo. Foi adicionado um teste.

---

## 2026-11-10: Correção: erro 400 com parâmetro `null`

- **Problema:** `Error code: 400 - Tool call validation failed: /categoria: expected string, but got null`, ao perguntar "gostaria de almoçar, tem algum prato para me recomendar?".
- **Causa:** o modelo enviou `null` num parâmetro opcional. O Groq valida as chamadas contra o schema e rejeitou, porque o schema só aceitava string.
- **Correção:** todo parâmetro opcional passou a aceitar `null` no schema (`"type": ["string", "null"]`, e `null` nos enums). O Python já tratava `None` como "usar o padrão". Foi adicionado um teste que verifica isso em todas as ferramentas.
- **Observação:** a pergunta de recomendação agora é recusada de forma educada, porque o agente é um analista para o dono, não um atendente. Ficou em aberto se ele deve recomendar pratos por popularidade e turno.

---

## 2026-11-10: Correção: refrigerante aparecia como "prato mais vendido"

- **Problema:** "qual o prato mais vendido?" respondia "Refrigerante lata".
- **Causa:** o ranking considerava o cardápio inteiro, e bebidas saem em quase todo pedido.
- **Correção:**
  - `ranking_pratos` passou a se chamar `ranking_itens` e ganhou o parâmetro `tipo`:
    - `pratos` (padrão): pratos principais e massas;
    - `comidas`: tudo menos bebidas;
    - `bebidas`;
    - `todos`: o cardápio inteiro.

    Se a pergunta citar uma categoria, ela tem prioridade sobre o tipo.
  - O prompt passou a definir que "prato" quer dizer refeição.
- **Validação:** "prato mais vendido" → Picanha na brasa; "bebida mais vendida" → Refrigerante lata.

---

## 2026-11-10: Correção: respostas com lixo e "?" no terminal

- **Problema:** depois de algumas perguntas, a resposta vinha corrompida antes do texto certo, por exemplo `Pudim de de t ? ? ? ?`, ou trechos como "Oops…", "Sorry…" e "---" repetidos.
- **Investigação:** foram feitas sondas automáticas contra o Groq, inspecionando cada caractere da resposta.
  1. O modelo troca espaços por variantes Unicode (U+202F e U+00A0) até dentro de valores que a ferramenta entregou com espaço comum. O terminal do Windows mostra esses caracteres como "?".
  2. A degeneração só aparecia **a partir da segunda pergunta da conversa**. Comparativo com 2 a 3 tentativas por configuração:

     | Configuração | 2ª pergunta certa |
     |---|---|
     | Histórico completo, temperatura 1 | 0 de 3 |
     | Histórico completo, temperatura 0.2 | 1 de 2 |
     | Histórico só com perguntas e respostas finais, temperatura 0.2 | 2 de 2 |
     | Histórico só com perguntas e respostas finais, temperatura 1 | 2 de 2 |

  3. A primeira hipótese, de que a temperatura baixa causava o problema, foi **descartada pelos testes**: a temperatura 1 piorou.
- **Causa:** levar para as próximas perguntas as mensagens de chamada de ferramenta e os JSONs de resultado das perguntas anteriores.
- **Correções:**
  - O histórico guarda só a pergunta e a resposta final de cada interação, até 20 mensagens. Dentro de uma mesma pergunta, o modelo continua recebendo os resultados das ferramentas normalmente.
  - Nova função `limpar_texto` na resposta final:
    - espaços Unicode viram espaço comum, ou ponto quando separam milhar ("8 032" → "8.032");
    - hífens especiais viram "-";
    - negrito vazio e quebras de linha em excesso são removidos.
  - As quantidades inteiras também passaram a sair formatadas do Python ("8.032"), como já acontecia com os valores em reais, e o prompt manda copiar sem trocar o separador.
  - O schema do parâmetro `prato` deixou de listar os 27 nomes, o que economiza tokens. O Python já faz a busca por trecho do nome.
  - A temperatura continua em 0.2.
- **Validação:** duas conversas de três perguntas encadeadas ("quais as sobremesas?" → "qual a mais pedida?" → "quanto ela faturou em outubro de 2026?"): **6 de 6 respostas corretas**, com o contexto preservado entre as perguntas.

---

## 2026-11-10: Limite de taxa do Groq

- **Problema:** as sondas receberam o erro `429 Rate limit reached ... tokens per minute (TPM): Limit 8000`.
- **Causa:** o plano gratuito do `gpt-oss-120b` permite 8.000 tokens por minuto, e cada chamada usa cerca de 2.000.
- **Correções:**
  - O cliente OpenAI usa `max_retries=5`, esperando o tempo que o Groq informa.
  - A CLI mostra uma mensagem clara quando as tentativas se esgotam.
  - O histórico enxuto e o schema menor reduzem os tokens por chamada.
- **Documentação:** o README ganhou a seção "Limite do plano gratuito do Groq".

---

## 2026-11-10: Repositório git

- O `.env.example` voltou para o valor de exemplo (`GROQ_API_KEY=sua_chave_aqui`). A chave real fica só no `.env`.
- O repositório git foi criado com o commit inicial.
- **Conferido antes do commit:** nenhum arquivo versionado contém uma chave do Groq (busca pelo padrão `gsk_` seguido de 20 ou mais caracteres), e o `.gitignore` exclui:
  - `.env` e `.venv/`;
  - os CSVs gerados (`data/*.csv`), que são recriados com `python -m analytics_agent.gerar_dados`;
  - `outputs/`, os caches do Python e do pytest;
  - `.vscode/`, que é configuração pessoal do editor.

---

## 2026-11-10: Publicação no GitHub

- Repositório público: [github.com/LuishPalacio/sabor-da-casa-analytics-agent](https://github.com/LuishPalacio/sabor-da-casa-analytics-agent), com o nome no mesmo padrão do `emporio-da-musica-agent`.
- **Conferido depois do push:** o `.env.example` publicado contém só `GROQ_API_KEY=sua_chave_aqui`, e `.env`, `.venv/`, `data/*.csv`, `outputs/` e `.vscode/` não foram enviados.

---

## Estado atual

- 17 testes passando.
- **Pendências:**
  - login por PIN e permissões por perfil (gerente e garçom): proposta feita, aguardando confirmação;
  - ajustes de transparência: descrever as capacidades com exemplos de perguntas em vez de nomes internos, e dizer que sabe só a data, não a hora;
  - decidir se o agente deve recomendar pratos (filtro por turno de almoço e jantar);
  - gerar uma chave nova do Groq e revogar a antiga (recomendação de segurança, porque a chave chegou a aparecer na conversa com o assistente).
