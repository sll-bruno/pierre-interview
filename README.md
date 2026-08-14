# Pierre — busca semântica de transações

Demo: https://pierre-interview.vercel.app

## Arquitetura V1

- CSV validado e convertido para Parquet.
- Um embedding `text-embedding-3-small` por transação, gerado a partir de `merchant` + `description`.
- Busca por similaridade cosseno em memória, com filtros de período, valor e estabelecimento.
- Cache LRU de embeddings de queries por instância.
- Período padrão: os últimos 15 dias relativos à transação mais recente da base.

O índice é armazenado em `data/ai_engineer_semantic_transactions_embeddings.parquet` e contém os campos da transação, `semantic_text`, `record_hash` e `embedding`.

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

Na Vercel, `OPENAI_API_KEY` está configurada em Production e Preview. O feedback é temporário na V1 porque o filesystem da Function não é persistente.
