# Corpus de avaliação

Este corpus é independente da base de demonstração. Ele simula lançamentos de
cartão/conta brasileiros, mas introduz aliases, descrições truncadas, valores
extremos, recorrência, estornos, valores negativos e transferências ambíguas.
O arquivo `queries.jsonl` é o *golden set*: cada linha contém a requisição para
`POST /search`, o status esperado e os IDs relevantes conhecidos.

Os rótulos de relevância são deliberadamente conservadores: não assumem que
todo resultado fora da lista é irrelevante. Assim, o avaliador mede recall,
MRR e taxa de acerto, sem reportar uma precisão artificial.

## Preparar um ambiente de avaliação

```bash
export TRANSACTIONS_CSV=data/evaluation/transactions.csv
export TRANSACTIONS_PARQUET=data/evaluation/transactions.parquet
export EMBEDDINGS_PARQUET=data/evaluation/transactions_embeddings.parquet
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
