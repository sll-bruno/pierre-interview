# Regressão da busca semântica — 14 de agosto de 2026

## Resumo

O merge `19e8767` (`merge: retain V1 core over superseded hybrid experiment`)
manteve o núcleo simplificado do commit de deploy `4342025` e descartou o motor
híbrido presente em `84d6223`.

A aplicação continuou respondendo HTTP 200 e os testes continuaram passando,
mas a busca deixou de usar enriquecimento, categorias e os dois canais de
embedding. Consultas por conceitos passaram a ser ranqueadas somente contra
`merchant + description`.

## Evidências

- O índice caiu de aproximadamente 1,76 MB para 829 KB.
- O schema ativo continha somente `semantic_text`, `record_hash` e `embedding`.
- As colunas `category`, `category_confidence`, `raw_embedding` e
  `enriched_embedding` desapareceram.
- A busca por `restaurantes acima de R$ 200` retornou Localiza, Booking.com,
  Carrefour e LATAM antes de qualquer restaurante.
- O `ScoreBreakdown` expunha apenas `raw_similarity` e `final_score`.
- O script de avaliação chamava `/search`, embora a rota de produção tivesse
  sido movida para `/api/search`, fazendo todos os casos retornarem 404.
- O golden set usa IDs `bench_*`, enquanto o índice de demonstração usa `tx_*`;
  portanto, os dois artefatos não podem ser avaliados como se fossem o mesmo
  corpus.

## Causa raiz

O conflito foi resolvido preservando a implementação V1 para viabilizar o
deploy. Essa resolução também substituiu o schema do índice e os testes do motor,
mas não falhou no startup porque a versão V1 aceitava explicitamente o schema
legado de um único embedding.

## Correção

1. Restaurar interpretação híbrida da consulta com fallback determinístico.
2. Restaurar embeddings separados para dado original e contexto enriquecido.
3. Restaurar categoria, confiança, score híbrido e limiar mínimo.
4. Regenerar o índice com o schema enriquecido.
5. Atualizar ferramentas HTTP para `/api/search`.
6. Avaliar apenas um índice construído a partir do corpus correspondente ao
   golden set.

## Prevenção

- O motor exige as colunas do schema enriquecido e recusa iniciar com índice
  legado.
- O teste de busca verifica categoria, decomposição do score e remoção de
  resultados fracos.
- O pipeline usa fingerprints de entrada, histórico, modelo, prompt e limiar.
- Mudanças de rota devem atualizar frontend, scripts de qualidade e carga no
  mesmo commit.
- Um índice binário novo deve ser inspecionado pelo schema antes do merge.

