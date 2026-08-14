# Pierre — busca semântica de transações

## Rodar a aplicação

```bash
.venv/bin/uvicorn app.main:app --reload
```

Acesse `http://localhost:8000`. O front usa a API semântica quando o índice está
disponível e recorre automaticamente à busca local no CSV para demonstração.

O índice é construído em duas etapas:

1. `gpt-4.1-mini` enriquece cada transação e sugere de uma a três categorias
   curtas com score e explicação. Os casos são processados por data; cada novo
   caso recebe somente exemplos anteriores relevantes.
2. O texto original e o enriquecimento geram embeddings separados com
   `text-embedding-3-small`. A explicação do classificador não entra no ranking.
3. A consulta é interpretada no backend em um schema estruturado e recebe um
   score híbrido com componentes de texto original, enriquecimento, categoria e
   estabelecimento.

Somente resultados acima de `SEARCH_MIN_SCORE` são retornados. O padrão 0.28 é
deliberadamente permissivo para priorizar recall.

Se a melhor categoria ficar abaixo de `UNKNOWN_CATEGORY_THRESHOLD` (0.62 por
padrão), a classificação final é `desconhecido`; a hipótese de baixa confiança
continua preservada entre as alternativas para auditoria.

## Gerar o índice

```bash
cp .env.example .env
# preencha OPENAI_API_KEY
.venv/bin/python scripts/index_transactions.py
```

O Parquet de saída preserva, além do embedding:

- `enriched_context`
- `category`, `category_confidence` e `category_explanation`
- `category_candidates` (JSON com até três hipóteses)
- `raw_semantic_text` e `enriched_semantic_text`
- `raw_embedding` e `enriched_embedding`

O cache de enriquecimento é invalidado automaticamente quando a entrada, o
histórico relevante, o modelo, o limiar ou o system prompt mudam.

## Testes

```bash
.venv/bin/python -m unittest discover -s tests -v
```

## Avaliação e carga

Há um corpus sintético, rotulado e isolado em
[`data/evaluation/`](data/evaluation/README.md). Ele contém casos de aliases,
ambiguidade, estornos, valores extremos e buscas que devem retornar vazio.

Depois de indexá-lo em caminhos próprios, execute a avaliação quantitativa:

```bash
.venv/bin/python scripts/evaluate_search.py --base-url http://127.0.0.1:8001
```

E, para testar concorrência e latência da API:

```bash
.venv/bin/python scripts/load_search.py --base-url http://127.0.0.1:8001 \
  --requests 500 --concurrency 20
```

Veja o guia do corpus para a configuração completa e o significado das métricas.
