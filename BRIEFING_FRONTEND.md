# Briefing de front-end — Recuperação de transações com estética Pierre

## 1. Resumo executivo

Construir uma interface de recuperação de informação financeira que permita buscar transações em linguagem natural e conferir os resultados com rapidez.

A direção deve combinar:

- **clareza de ferramenta**: busca em primeiro plano, resultados fáceis de escanear e filtros compreensíveis;
- **personalidade Pierre**: fundo quase preto, contraste alto, linguagem direta e coloquial, superfícies arredondadas e um gato preto como assistente;
- **confiança financeira**: interpretação da consulta visível, valores bem formatados, estados previsíveis e nenhuma “mágica” sem explicação.

Hipótese de produto para a V0: o usuário pergunta algo como “quanto gastei com delivery em julho?” e recebe uma lista de transações, total, quantidade de resultados e filtros inferidos.

## 2. O que foi observado na Pierre

### Site

- Base visual em `#09090B`, texto branco e cinzas de baixa saturação.
- Tipografia **Geist**, com títulos de peso médio e entrelinha compacta.
- Botões e navegação em formato pill; bordas brancas/cinzas muito sutis.
- Verde-lima como cor de inteligência/insight, acompanhado ocasionalmente de rosa, amarelo e azul.
- Produto demonstrado por meio de conversa e cartões flutuantes, não por telas densas.
- Voz informal, curta e humana: “sua grana”, “não comigo”, “pra você”.
- Provas de confiança aparecem cedo: bancos conectados, criptografia e Open Finance.

### Instagram

- O gato com óculos funciona como assinatura visual e avatar do assistente.
- A marca alterna peças tipográficas em preto + verde-lima com conteúdo humano e cultural.
- Capas e destaques usam objetos/avatares 3D coloridos sobre fundo escuro.
- A identidade é mais viva que a landing page: verde neon, roxo, azul e elementos de cultura digital.
- O conteúdo reforça quatro territórios: produto, dinheiro, segurança e presença cultural/humana.

### Tradução para este projeto

Manter a estrutura minimalista da landing e usar a energia do Instagram somente em pontos funcionais: estado ativo, insight, destaque de total e microinterações. O gato deve orientar e reagir; não deve preencher a tela como ornamento.

## 3. Usuário, necessidade e tarefa central

Usuário primário: pessoa que quer encontrar e compreender gastos sem lembrar exatamente como eles aparecem no extrato.

Necessidades:

- buscar por intenção, mesmo com termos diferentes dos descritores bancários;
- entender por que cada resultado apareceu;
- refinar período, estabelecimento e faixa de valor;
- conferir total e itens individuais;
- corrigir rapidamente uma interpretação errada.

Tarefa principal:

> Formular uma pergunta → conferir a interpretação → analisar os resultados → refinar ou abrir uma transação.

## 4. Arquitetura de informação da V0

### Cabeçalho

- logo/assinatura Pierre à esquerda;
- nome curto da ferramenta, por exemplo “Busca de transações”;
- ação discreta para ajuda ou exemplos;
- avatar do usuário apenas se houver autenticação real.

### Área de busca

- título: “O que você quer encontrar?”;
- campo grande, de uma linha expansível, com ícone do gato;
- placeholder: “Ex.: gastos com viagem acima de R$ 500 em julho”;
- botão primário “Buscar” ou envio por Enter;
- exemplos clicáveis abaixo do campo.

### Interpretação da consulta

Após a busca, exibir chips editáveis como:

- `Categoria: viagem`
- `Valor: acima de R$ 500`
- `Período: jul/2026`

Adicionar a frase curta “Entendi assim:” para tornar o sistema explicável.

### Resumo

- valor total encontrado como informação principal;
- quantidade de transações;
- período coberto;
- ordenação atual.

Não usar dashboard com muitos gráficos na V0. Um resumo numérico é mais útil para recuperação de informação.

### Resultados

No desktop, tabela enxuta com:

- data;
- estabelecimento;
- descrição original;
- valor alinhado à direita;
- indicador discreto do motivo do match, quando semântico.

No mobile, cards em lista com estabelecimento e valor na primeira linha e data/descrição na segunda.

Ao selecionar uma linha, abrir drawer lateral com todos os dados da transação e uma explicação curta: “Apareceu porque ‘LATAM’ foi associado a viagem”.

### Filtros

- desktop: barra horizontal acima dos resultados;
- mobile: bottom sheet acionado por “Filtrar”;
- mostrar filtros ativos como chips removíveis;
- oferecer “Limpar tudo”, sem esconder o estado aplicado.

## 5. Wireframe conceitual

```text
┌────────────────────────────────────────────────────────────┐
│ Pierre / Busca de transações                 Ajuda    ◉     │
├────────────────────────────────────────────────────────────┤
│                                                            │
│  🐈‍⬛  O que você quer encontrar?                           │
│  ┌──────────────────────────────────────────────┬────────┐ │
│  │ gastos com delivery em julho                │ Buscar │ │
│  └──────────────────────────────────────────────┴────────┘ │
│  Experimente: [viagens > R$500] [compras no Carrefour]     │
│                                                            │
│  Entendi assim: [delivery ×] [jul/2026 ×]                  │
│                                                            │
│  R$ 240,91                    3 transações                  │
│  ────────────────────────────────────────────────────────  │
│  Data       Estabelecimento      Descrição         Valor   │
│  14 jul     iFood                IFOOD *REST...    119,25  │
│  24 mai     Rappi                RAPPI BRASIL      121,66  │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

## 6. Direção visual

### Tokens iniciais

```css
:root {
  --bg: #09090b;
  --surface: #111114;
  --surface-raised: #18181b;
  --border: rgba(255, 255, 255, 0.10);
  --border-strong: rgba(255, 255, 255, 0.18);
  --text: #ffffff;
  --text-muted: rgba(255, 255, 255, 0.70);
  --text-subtle: rgba(255, 255, 255, 0.48);
  --lime: #cfff04;
  --lime-soft: #95ff48;
  --pink: #fc94a6;
  --yellow: #ffec7e;
  --blue: #a3bfff;
  --danger: #ff6b7a;
  --radius-sm: 10px;
  --radius-md: 16px;
  --radius-pill: 999px;
}
```

### Tipografia

- Geist como primeira opção; fallback `Arial, sans-serif`.
- Título principal: 40–48 px desktop, 32–36 px mobile, peso 500.
- Texto base: 16–18 px, entrelinha de 1.45 a 1.55.
- Dados tabulares: usar números tabulares (`font-variant-numeric: tabular-nums`).
- Evitar excesso de caixa alta; usar apenas em pequenos labels.

### Composição

- largura útil entre 1120 e 1240 px;
- grid de 8 px;
- muito espaço vazio no estado inicial;
- densidade aumenta somente depois que há resultados;
- bordas sutis em vez de sombras pesadas;
- um único destaque cromático por bloco.

### Gato preto

Usar três níveis de presença:

1. **assinatura**: ícone line-art no cabeçalho;
2. **assistente**: pequena cabeça/olhos junto da busca e das mensagens de estado;
3. **reação**: variações discretas para vazio, carregando, sem resultado e erro.

Regras:

- manter silhueta simples e reconhecível em 24–48 px;
- preferir SVG próprio ou asset oficial autorizado;
- não usar emojis como identidade final;
- animação curta de piscar/orelhas apenas no carregamento, respeitando `prefers-reduced-motion`;
- não espalhar patas, bigodes e orelhas por todos os componentes.

## 7. Linguagem e microcopy

Tom: direto, próximo, seguro e levemente espirituoso.

Exemplos:

- vazio inicial: “Me conta o que você procura.”
- carregando: “Tô procurando no seu extrato…”
- sucesso: “Achei 8 transações que combinam com isso.”
- sem resultado: “Não encontrei nada com esses critérios. Quer ampliar o período?”
- erro: “Não consegui buscar agora. Seus filtros continuam aqui.”
- interpretação: “Entendi assim:”

Evitar piadas em mensagens de erro, segurança ou dinheiro perdido.

## 8. Estados obrigatórios

- inicial com exemplos de consulta;
- digitando;
- carregando com skeleton, sem deslocar o layout;
- resultados;
- nenhum resultado com sugestão útil;
- erro recuperável com ação “Tentar novamente”;
- consulta inválida ou vaga;
- filtro ativo;
- drawer de detalhe;
- conexão/API indisponível.

## 9. Usabilidade e acessibilidade

- Enter executa a busca; `Esc` fecha drawer/modal.
- Foco visível em lime com contraste suficiente.
- Alvos interativos de pelo menos 44 × 44 px.
- Tabela navegável por teclado e com cabeçalhos semânticos.
- Não depender somente de cor para explicar status ou match.
- Usar `aria-live="polite"` para quantidade de resultados.
- Preservar a consulta e os filtros ao ocorrer erro.
- Formatar moeda e data com `pt-BR`.
- Confirmar a interpretação sem obrigar uma etapa extra.
- Em resultados semânticos, diferenciar “descrição original” de “interpretação do sistema”.

## 10. Responsividade

- **≥ 1024 px:** tabela, filtros inline e drawer lateral.
- **768–1023 px:** tabela simplificada; filtros em painel.
- **< 768 px:** cards, campo de busca fixado no topo após a primeira consulta e filtros em bottom sheet.
- Evitar scroll horizontal em transações; ocultar ou reorganizar colunas secundárias.

## 11. Escopo recomendado da V0

Incluir:

- busca em linguagem natural;
- exemplos clicáveis;
- chips da interpretação;
- resumo com total e contagem;
- lista/tabela responsiva;
- filtro por período, estabelecimento e faixa de valor;
- ordenação por data e valor;
- estados de loading, vazio e erro;
- detalhe da transação;
- identidade visual e microinterações essenciais.

Deixar para depois:

- gráficos complexos;
- personalização profunda de dashboard;
- múltiplos agentes/personas;
- exportação avançada;
- gamificação;
- animações 3D pesadas.

## 12. Critérios de sucesso da primeira versão

- A função principal é compreendida em até 5 segundos.
- Uma busca pode ser iniciada sem conhecer sintaxe ou filtros.
- O usuário consegue explicar quais critérios foram aplicados.
- Resultados e valores são escaneáveis no desktop e no mobile.
- É possível corrigir um filtro sem refazer a pergunta inteira.
- A interface parece Pierre mesmo sem depender de grandes ilustrações.
- Todos os estados principais existem e não quebram o layout.

## 13. Riscos a evitar

- copiar a landing literalmente e acabar com uma página de marketing, não uma ferramenta;
- fundo totalmente preto com cinzas de contraste insuficiente;
- neon em excesso, reduzindo a sensação de confiança;
- gato usado como enfeite repetitivo ou infantil;
- busca “mágica” sem mostrar o que o sistema entendeu;
- tabela densa demais no primeiro contato;
- esconder a descrição bancária original;
- criar dashboard antes de validar a recuperação de informação.

## 14. Referências analisadas

- [Landing page da Pierre](https://lp.pierre.finance/lp/home-3)
- [Instagram @pierre.finance.ai](https://www.instagram.com/pierre.finance.ai/)
- [Site do produto](https://www.pierre.finance/)
- [Aplicativo na App Store](https://apps.apple.com/br/app/pierre-controle-de-gastos-ia/id6749781755)

## 15. Próxima etapa quando a V0 chegar

1. mapear a stack e os componentes existentes;
2. rodar a aplicação e revisar desktop/mobile;
3. comparar a implementação com este briefing;
4. corrigir primeiro arquitetura, hierarquia e estados;
5. aplicar tokens, componentes e personalidade do gato;
6. verificar acessibilidade, responsividade e comportamento real da busca.
