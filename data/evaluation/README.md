# Corpus de avaliação

`production_queries.jsonl` é o golden set padrão da aplicação: seus rótulos
referenciam os IDs `tx_*` do índice que vai para produção. Por isso a aba
**Avaliação** funciona no mesmo deploy, inclusive depois de um cold start; ela
apenas relê o Parquet versionado e executa as consultas rotuladas.

`queries.jsonl` e `transactions.csv` formam um segundo corpus, independente,
com IDs `bench_*`. Ele continua sendo usado para regressões isoladas e deve ser
selecionado explicitamente via `EVALUATION_SUITE` junto dos Parquets de teste.

Este corpus é independente da base de demonstração. Ele simula lançamentos de
cartão/conta brasileiros, mas introduz aliases, descrições truncadas, valores
extremos, recorrência, estornos, valores negativos e transferências ambíguas.
O arquivo `queries.jsonl` é o *golden set* isolado: cada linha contém a requisição para
`POST /api/search`, o status esperado e os IDs relevantes conhecidos.

Os rótulos de relevância são deliberadamente conservadores: não assumem que
todo resultado fora da lista é irrelevante. Assim, o avaliador mede recall,
MRR e taxa de acerto, sem reportar uma precisão artificial.

## Preparar um ambiente de avaliação

```bash
export TRANSACTIONS_CSV=data/evaluation/transactions.csv
export TRANSACTIONS_PARQUET=data/evaluation/transactions.parquet
export EMBEDDINGS_PARQUET=data/evaluation/transactions_embeddings.parquet
export EVALUATION_SUITE=data/evaluation/queries.jsonl
.venv/bin/python scripts/index_transactions.py
.venv/bin/uvicorn app.main:app --port 8001
```

O primeiro comando de indexação chama os modelos de enriquecimento e embeddings.
Os Parquets gerados são ignorados pelo Git e podem ser regenerados.

Com a aplicação iniciada nessa configuração, a aba **Avaliação** fica habilitada
automaticamente. Ela executa o golden set e permite rodar carga HTTP no próprio
navegador, exibindo as métricas sem precisar usar o terminal.

## Qualidade e desempenho

Com a API em execução, rode:

```bash
.venv/bin/python scripts/evaluate_search.py --base-url http://127.0.0.1:8001
```

O resultado agrega `recall@10`, `MRR@10`, taxa de sucesso de casos e latências.
Sem `--suite`, o script usa o golden set de produção (`production_queries.jsonl`).
Para preservar um relatório comparável, salve o JSON:

```bash
.venv/bin/python scripts/evaluate_search.py --base-url http://127.0.0.1:8001 \
  --output data/evaluation/latest-quality-report.json
```

## Carga

O gerador de carga não possui dependências extras e reutiliza os payloads
rotulados com tag `load`:

```bash
.venv/bin/python scripts/load_search.py --base-url http://127.0.0.1:8001 \
  --requests 500 --concurrency 20
```

Comece com baixa concorrência e aumente gradualmente. Como cada busca pode
chamar modelos externos, os limites e a latência desses provedores fazem parte
do teste; monitore `429`, `5xx` e p95/p99. Para exercitar também os casos sem
resultado, acrescente `--tag empty`.
