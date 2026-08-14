# Pierre — busca semântica de transações

Demo: https://pierre-interview.vercel.app

## Arquitetura

- O CSV é validado e processado cronologicamente.
- `gpt-4.1-mini` enriquece cada transação usando casos anteriores relevantes.
- O classificador gera contexto, até três categorias, confiança e explicação.
- Resultados abaixo de `UNKNOWN_CATEGORY_THRESHOLD` viram `desconhecido`.
- `text-embedding-3-small` gera dois vetores separados: dado bancário original
  e contexto enriquecido.
- A consulta é interpretada em intenção, período, valor e estabelecimento.
- O ranking combina similaridade original, enriquecida, categoria e merchant.
- Filtros objetivos são aplicados antes do ranking e resultados abaixo de
  `SEARCH_MIN_SCORE` são removidos.
- Embeddings de consultas possuem cache LRU por instância.

O índice fica em
`data/ai_engineer_semantic_transactions_embeddings.parquet`. O motor exige o
schema enriquecido e não inicia silenciosamente com um índice legado.

## Rodar localmente

```bash
cp .env.example .env
# preencha OPENAI_API_KEY
.venv/bin/python scripts/index_transactions.py
.venv/bin/uvicorn app.main:app --reload
```

## API

- `GET /api/health`
- `POST /api/search`
- `POST /api/feedback`

## Testes

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Na Vercel, `OPENAI_API_KEY` está configurada em Production e Preview. O feedback
é temporário porque o filesystem da Function não é persistente.

## Incidentes

A regressão que substituiu o motor híbrido pela busca de um único embedding está
documentada em
[`docs/incidents/2026-08-14-semantic-search-regression.md`](docs/incidents/2026-08-14-semantic-search-regression.md).
