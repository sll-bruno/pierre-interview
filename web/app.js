const state = {
  allTransactions: [],
  results: [],
  query: "",
  filters: {},
  selected: null,
  interpretation: null,
  backendAvailable: true,
  evaluationReady: false,
  showcaseCases: [],
};

const $ = (selector) => document.querySelector(selector);
const elements = {
  form: $("#searchForm"), query: $("#queryInput"), section: $("#resultsSection"),
  chips: $("#interpretationChips"), filterToggle: $("#filterToggle"), filterPanel: $("#filterPanel"),
  filterCount: $("#filterCount"), clearFilters: $("#clearFilters"), total: $("#resultTotal"),
  count: $("#resultCount"), period: $("#resultPeriod"), subtitle: $("#resultsSubtitle"),
  body: $("#resultsBody"), table: $("#resultsTableWrap"), loading: $("#loadingState"),
  empty: $("#emptyState"), reset: $("#resetSearch"), sort: $("#sortSelect"),
  dialog: $("#transactionDialog"), dialogMerchant: $("#dialogMerchant"), dialogContent: $("#dialogContent"),
  toast: $("#toast"), mode: $("#dataMode"), help: $("#helpDialog"),
  searchTab: $("#searchTab"), evaluationTab: $("#evaluationTab"), searchView: $("#searchView"), evaluationView: $("#evaluationView"),
  evaluationStatus: $("#evaluationStatus"), showcaseCases: $("#showcaseCases"),
};

const money = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
const shortDate = new Intl.DateTimeFormat("pt-BR", { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" });
const longDate = new Intl.DateTimeFormat("pt-BR", { day: "2-digit", month: "long", year: "numeric", timeZone: "UTC" });
const normalize = (text = "") => text.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
const escapeHtml = (text = "") => text.replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char]);

const categories = {
  transporte: ["uber", "99", "corrida", "transporte", "taxi", "combustivel", "posto", "shell"],
  viagem: ["viagem", "viagens", "latam", "tam", "gol", "azul", "hotel", "hospedagem", "localiza", "airbnb"],
  delivery: ["delivery", "ifood", "rappi", "comida", "restaurante", "mcdonald", "outback"],
  mercado: ["mercado", "supermercado", "carrefour", "pao de acucar", "atacadao"],
  casa: ["casa", "moveis", "tok&stok", "tokstok", "leroy"],
  streaming: ["streaming", "netflix", "spotify", "prime", "disney"],
};

const monthNames = ["janeiro", "fevereiro", "marco", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"];

async function loadData() {
  try {
    const response = await fetch("/api/ai_engineer_semantic_transactions.csv");
    if (!response.ok) throw new Error("CSV indisponível");
    state.allTransactions = parseCsv(await response.text());
    elements.mode.textContent = `${state.allTransactions.length} transações prontas`;
  } catch {
    elements.mode.textContent = "Base conectada pela API";
  }
}

function parseCsv(csv) {
  const [header, ...lines] = csv.trim().split(/\r?\n/);
  const keys = header.split(",");
  return lines.map((line) => {
    const values = line.match(/("[^"]*(?:""[^"]*)*"|[^,]*)(?:,|$)/g)?.map((value) => value.replace(/,$/, "").replace(/^"|"$/g, "").replace(/""/g, '"')) || [];
    const row = Object.fromEntries(keys.map((key, index) => [key, values[index] || ""]));
    row.amount_brl = Number(row.amount_brl);
    return row;
  });
}

function inferQuery(rawQuery) {
  const query = normalize(rawQuery);
  const inferred = { labels: [], terms: [] };
  const category = Object.entries(categories).find(([name, terms]) => query.includes(name) || terms.some((term) => query.includes(term)));
  if (category) { inferred.category = category[0]; inferred.terms.push(...category[1]); inferred.labels.push(`Categoria: ${category[0]}`); }
  const amount = query.match(/(?:acima|mais|maior)(?: de)?\s*(?:r\$)?\s*([\d.,]+)/);
  if (amount) { inferred.minAmount = parsePtNumber(amount[1]); inferred.labels.push(`Acima de ${money.format(inferred.minAmount)}`); }
  const maxAmount = query.match(/(?:abaixo|menos|menor)(?: de)?\s*(?:r\$)?\s*([\d.,]+)/);
  if (maxAmount) { inferred.maxAmount = parsePtNumber(maxAmount[1]); inferred.labels.push(`Abaixo de ${money.format(inferred.maxAmount)}`); }
  const monthIndex = monthNames.findIndex((month) => query.includes(month));
  if (monthIndex >= 0) { inferred.month = monthIndex; inferred.labels.push(`Período: ${monthNames[monthIndex]}/2026`); }
  const merchant = [...new Set(state.allTransactions.map((item) => item.merchant))].find((name) => query.includes(normalize(name)));
  if (merchant) { inferred.merchant = merchant; inferred.labels.push(`Estabelecimento: ${merchant}`); inferred.terms.push(normalize(merchant)); }
  if (!inferred.labels.length) inferred.labels.push(`Intenção: ${rawQuery}`);
  return inferred;
}

function parsePtNumber(value) {
  const clean = value.trim();
  if (clean.includes(",")) return Number(clean.replace(/\./g, "").replace(",", "."));
  return Number(clean);
}

function getFormFilters() {
  const data = new FormData(elements.filterPanel);
  return Object.fromEntries([...data.entries()].filter(([, value]) => value !== ""));
}

function interpretationLabels(interpretation) {
  if (interpretation.labels) return interpretation.labels;
  const labels = [];
  if (interpretation.semantic_intent) labels.push(`Intenção: ${interpretation.semantic_intent}`);
  if (interpretation.date_from || interpretation.date_to) labels.push(`Período: ${interpretation.date_from || "início"} — ${interpretation.date_to || "hoje"}`);
  if (interpretation.min_amount_brl != null) labels.push(`Acima de ${money.format(interpretation.min_amount_brl)}`);
  if (interpretation.max_amount_brl != null) labels.push(`Abaixo de ${money.format(interpretation.max_amount_brl)}`);
  if (interpretation.merchant) labels.push(`Estabelecimento: ${interpretation.merchant}`);
  return labels;
}

async function performSearch(query, { scroll = true } = {}) {
  if (!query.trim()) return;
  state.query = query.trim();
  state.filters = getFormFilters();
  const inferred = inferQuery(state.query);
  showLoading(inferred);
  if (scroll) elements.section.scrollIntoView({ behavior: "smooth", block: "start" });

  try {
    const apiFilters = {
      date_from: state.filters.dateFrom || undefined,
      date_to: state.filters.dateTo || undefined,
      min_amount_brl: state.filters.minAmount ? Number(state.filters.minAmount) : undefined,
      max_amount_brl: state.filters.maxAmount ? Number(state.filters.maxAmount) : undefined,
      merchant: state.filters.merchant || undefined,
    };
    Object.keys(apiFilters).forEach((key) => apiFilters[key] === undefined && delete apiFilters[key]);
    const response = await fetch("/api/search", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ query: state.query, filters: apiFilters }) });
    if (!response.ok) throw new Error("API indisponível");
    const payload = await response.json();
    state.results = payload.transactions;
    state.interpretation = payload.interpretation;
    state.backendAvailable = true;
    renderResults(payload.interpretation, payload.period);
  } catch {
    state.backendAvailable = false;
    state.interpretation = inferred;
    state.results = localSearch(state.query, inferred);
    await new Promise((resolve) => setTimeout(resolve, 420));
    renderResults(inferred, derivePeriod(state.results));
  }
}

function localSearch(query, inferred) {
  const words = normalize(query).split(/\s+/).filter((word) => word.length > 2 && !["com", "para", "meus", "gastos", "acima", "abaixo"].includes(word));
  return state.allTransactions
    .map((transaction) => {
      const haystack = normalize(`${transaction.merchant} ${transaction.description}`);
      const categoryScore = inferred.terms.filter((term) => haystack.includes(normalize(term))).length * 4;
      const wordScore = words.filter((word) => haystack.includes(word)).length;
      return { ...transaction, _score: categoryScore + wordScore };
    })
    .filter((transaction) => {
      const date = new Date(`${transaction.date}T00:00:00Z`);
      const matchMeaning = transaction._score > 0 || (!inferred.terms.length && words.length === 0);
      return matchMeaning
        && (inferred.minAmount == null || transaction.amount_brl >= inferred.minAmount)
        && (inferred.maxAmount == null || transaction.amount_brl <= inferred.maxAmount)
        && (inferred.month == null || date.getUTCMonth() === inferred.month);
    })
    .filter((transaction) => filterTransaction(transaction))
    .sort((a, b) => b._score - a._score || new Date(b.date) - new Date(a.date));
}

function applyUiFilters(transactions, inferred) {
  return transactions.filter((transaction) => {
    const date = new Date(`${transaction.date}T00:00:00Z`);
    return (inferred.month == null || date.getUTCMonth() === inferred.month) && filterTransaction(transaction);
  });
}

function filterTransaction(transaction) {
  const { dateFrom, dateTo, minAmount, maxAmount, merchant } = state.filters;
  return (!dateFrom || transaction.date >= dateFrom) && (!dateTo || transaction.date <= dateTo)
    && (!minAmount || transaction.amount_brl >= Number(minAmount)) && (!maxAmount || transaction.amount_brl <= Number(maxAmount))
    && (!merchant || normalize(transaction.merchant).includes(normalize(merchant)));
}

function derivePeriod(results) {
  const dates = results.map((item) => item.date).sort();
  return dates.length ? { date_from: dates[0], date_to: dates.at(-1), source: "local" } : null;
}

function showLoading(inferred) {
  elements.section.hidden = false; elements.loading.hidden = false; elements.table.hidden = true; elements.empty.hidden = true;
  elements.chips.innerHTML = interpretationLabels(inferred).map((label) => `<span class="chip">${escapeHtml(label)}</span>`).join("");
}

function renderResults(inferred, period) {
  elements.loading.hidden = true;
  elements.chips.innerHTML = interpretationLabels(inferred).map((label) => `<span class="chip">${escapeHtml(label)}</span>`).join("");
  sortAndRenderRows();
  const total = state.results.reduce((sum, item) => sum + Number(item.amount_brl), 0);
  elements.total.textContent = money.format(total); elements.count.textContent = state.results.length;
  elements.subtitle.textContent = state.results.length === 1 ? "1 resultado para a sua busca" : `${state.results.length} resultados para a sua busca`;
  elements.period.textContent = period ? `${longDate.format(new Date(`${period.date_from}T00:00:00Z`))} — ${longDate.format(new Date(`${period.date_to}T00:00:00Z`))}` : "Nenhum período encontrado";
  elements.empty.hidden = state.results.length > 0; elements.table.hidden = state.results.length === 0;
  elements.mode.textContent = state.backendAvailable ? "Busca semântica ativa" : "Modo de demonstração local";
  updateFilterBadge();
}

function sortAndRenderRows() {
  const sorted = [...state.results];
  const mode = elements.sort.value;
  if (mode === "date-desc") sorted.sort((a, b) => new Date(b.date) - new Date(a.date));
  if (mode === "date-asc") sorted.sort((a, b) => new Date(a.date) - new Date(b.date));
  if (mode === "amount-desc") sorted.sort((a, b) => b.amount_brl - a.amount_brl);
  if (mode === "amount-asc") sorted.sort((a, b) => a.amount_brl - b.amount_brl);
  elements.body.innerHTML = sorted.map((item, index) => {
    const colors = ["var(--pink)", "var(--yellow)", "var(--blue)", "var(--lime)"];
    return `<tr>
      <td class="date">${shortDate.format(new Date(`${item.date}T00:00:00Z`))}</td>
      <td><div class="merchant-cell"><span class="merchant-icon" style="--icon-color:${colors[index % colors.length]}">${escapeHtml(item.merchant.slice(0, 2))}</span><span class="merchant-copy"><strong>${escapeHtml(item.merchant)}</strong><small class="transaction-id">${escapeHtml(item.transaction_id)}</small></span></div></td>
      <td class="description">${escapeHtml(item.description)}</td>
      <td class="amount">${money.format(item.amount_brl)}</td>
      <td><button class="row-button" type="button" data-id="${escapeHtml(item.transaction_id)}" aria-label="Ver detalhes de ${escapeHtml(item.merchant)}">→</button></td>
    </tr>`;
  }).join("");
}

function openTransaction(id) {
  const transaction = state.results.find((item) => item.transaction_id === id);
  if (!transaction) return;
  state.selected = transaction; elements.dialogMerchant.textContent = transaction.merchant;
  elements.dialogContent.innerHTML = `
    <div class="detail-row"><span>Valor</span><strong>${money.format(transaction.amount_brl)}</strong></div>
    <div class="detail-row"><span>Data</span><strong>${longDate.format(new Date(`${transaction.date}T00:00:00Z`))}</strong></div>
    <div class="detail-row"><span>Descrição original</span><strong>${escapeHtml(transaction.description)}</strong></div>
    <div class="detail-row"><span>ID da transação</span><strong>${escapeHtml(transaction.transaction_id)}</strong></div>
    ${transaction.category ? `<div class="detail-row"><span>Categoria inferida</span><strong>${escapeHtml(transaction.category)} (${Math.round(transaction.category_confidence * 100)}%)</strong></div>` : ""}
    ${transaction.score != null ? `<div class="detail-row"><span>Relevância</span><strong>${Math.round(transaction.score * 100)}%</strong></div>` : ""}
    <div class="match-explanation">${escapeHtml(transaction.explanation || `Apareceu porque os dados da transação correspondem a “${state.query}”.`)}</div>`;
  elements.dialog.showModal();
}

function updateFilterBadge() {
  const count = Object.keys(state.filters).length;
  elements.filterCount.hidden = count === 0; elements.filterCount.textContent = count;
}

async function sendFeedback(relevant) {
  if (!state.selected) return;
  try {
    const response = await fetch("/api/feedback", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ query: state.query, transaction_id: state.selected.transaction_id, relevant }) });
    if (!response.ok) throw new Error("Feedback indisponível");
    elements.dialog.close(); showToast("Valeu. Feedback registrado.");
  } catch {
    showToast("Não foi possível registrar o feedback.");
  }
}

function showToast(message) { elements.toast.textContent = message; elements.toast.classList.add("show"); setTimeout(() => elements.toast.classList.remove("show"), 2200); }

function formatPercent(value) { return value == null ? "—" : `${Math.round(value * 100)}%`; }
function formatMs(value) { return value == null ? "—" : `${Math.round(value)} ms`; }

async function responseError(response) {
  try {
    const body = await response.json();
    return body.detail || "Não foi possível executar o teste.";
  } catch { return "Não foi possível executar o teste."; }
}

async function refreshEvaluationStatus() {
  elements.evaluationStatus.className = "evaluation-status";
  elements.evaluationStatus.textContent = "Verificando corpus…";
  try {
    const response = await fetch("/api/evaluation/status");
    if (!response.ok) throw new Error("Status indisponível");
    const payload = await response.json();
    state.evaluationReady = Boolean(payload.available);
    if (state.evaluationReady) {
      elements.evaluationStatus.classList.add("ready");
      const showcaseResponse = await fetch("/api/evaluation/showcase");
      if (!showcaseResponse.ok) throw new Error(await responseError(showcaseResponse));
      const showcase = await showcaseResponse.json();
      state.showcaseCases = showcase.cases;
      renderShowcaseCases();
      elements.evaluationStatus.textContent = `${state.showcaseCases.length} casos selecionados para demonstração.`;
    } else {
      elements.evaluationStatus.classList.add("error");
      elements.evaluationStatus.textContent = payload.reason || "Corpus de avaliação indisponível.";
      elements.showcaseCases.innerHTML = "";
    }
  } catch {
    state.evaluationReady = false;
    elements.evaluationStatus.classList.add("error");
    elements.evaluationStatus.textContent = "Não foi possível verificar o ambiente de avaliação.";
    elements.showcaseCases.innerHTML = "";
  }
}

function switchView(view) {
  const isEvaluation = view === "evaluation";
  elements.searchView.hidden = isEvaluation; elements.evaluationView.hidden = !isEvaluation;
  elements.searchTab.classList.toggle("active", !isEvaluation); elements.evaluationTab.classList.toggle("active", isEvaluation);
  elements.searchTab.setAttribute("aria-selected", String(!isEvaluation)); elements.evaluationTab.setAttribute("aria-selected", String(isEvaluation));
  if (isEvaluation) refreshEvaluationStatus();
}

function showcaseTransactions(transactions) {
  if (!transactions.length) return '<li class="showcase-empty">Nenhuma transação esperada.</li>';
  return transactions.map((transaction) => `<li><strong>${escapeHtml(transaction.merchant)}</strong><span>${money.format(transaction.amount_brl)} · ${escapeHtml(transaction.category)}</span></li>`).join("");
}

function renderShowcaseCases() {
  elements.showcaseCases.innerHTML = state.showcaseCases.map((item) => {
    const truth = item.ground_truth.transactions;
    return `<article class="showcase-card" data-showcase-id="${escapeHtml(item.id)}">
      <div class="showcase-heading"><span class="run-badge">${escapeHtml(item.label)}</span><span class="showcase-count">${truth.length} esperado${truth.length === 1 ? "" : "s"}</span></div>
      <h2>${escapeHtml(item.scenario)}</h2>
      <div class="showcase-query"><span>Query</span><code>${escapeHtml(item.query)}</code></div>
      <div class="showcase-truth"><span>Ground truth</span><ul>${showcaseTransactions(truth)}</ul></div>
      <button class="apply-button showcase-run" type="button" data-run-showcase="${escapeHtml(item.id)}">Rodar modelo ao vivo</button>
      <div class="showcase-output" hidden></div>
    </article>`;
  }).join("");
}

function setsEqual(left, right) {
  return left.size === right.size && [...left].every((value) => right.has(value));
}

function renderShowcaseOutput(card, item, response, status) {
  const output = card.querySelector(".showcase-output");
  const expected = new Set(item.ground_truth.transactions.map((transaction) => transaction.transaction_id));
  const found = new Set((response?.transactions || []).map((transaction) => transaction.transaction_id));
  const exact = status === item.expected_status && setsEqual(expected, found);
  const matched = [...expected].filter((id) => found.has(id)).length;
  const results = response?.transactions || [];
  const explanations = [...new Set(results.map((result) => result.explanation).filter(Boolean))];
  output.hidden = false;
  output.innerHTML = `<div class="showcase-verdict ${exact ? "pass" : "review"}"><strong>${exact ? "Confere com o ground truth" : "Revisar resultado"}</strong><span>${matched}/${expected.size} transações esperadas encontradas</span></div>
    <div class="showcase-result-block"><span>Saída ao vivo</span><ul>${showcaseTransactions(results)}</ul></div>
    <div class="showcase-reason"><span>Justificativa do modelo</span><p>${escapeHtml(explanations.join(" ") || "Não houve resultados para justificar.")}</p></div>`;
}

async function runShowcaseCase(id) {
  const item = state.showcaseCases.find((candidate) => candidate.id === id);
  const card = elements.showcaseCases.querySelector(`[data-showcase-id="${CSS.escape(id)}"]`);
  if (!item || !card) return;
  const button = card.querySelector("[data-run-showcase]");
  button.disabled = true; button.textContent = "Rodando ao vivo…";
  try {
    const response = await fetch("/api/search", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ query: item.query, filters: item.filters }) });
    const payload = response.ok ? await response.json() : null;
    renderShowcaseOutput(card, item, payload, response.status);
  } catch {
    renderShowcaseOutput(card, item, null, 0);
  } finally {
    button.disabled = false; button.textContent = "Rodar modelo ao vivo";
  }
}

elements.form.addEventListener("submit", (event) => { event.preventDefault(); performSearch(elements.query.value); });
elements.query.addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); elements.form.requestSubmit(); } });
elements.query.addEventListener("input", () => { elements.query.style.height = "auto"; elements.query.style.height = `${Math.min(elements.query.scrollHeight, 96)}px`; });
document.querySelectorAll("[data-query]").forEach((button) => button.addEventListener("click", () => { elements.query.value = button.dataset.query; performSearch(button.dataset.query); }));
elements.filterToggle.addEventListener("click", () => { const open = elements.filterPanel.hidden; elements.filterPanel.hidden = !open; elements.filterToggle.setAttribute("aria-expanded", String(open)); });
elements.filterPanel.addEventListener("submit", (event) => { event.preventDefault(); performSearch(state.query, { scroll: false }); });
elements.clearFilters.addEventListener("click", () => { elements.filterPanel.reset(); state.filters = {}; updateFilterBadge(); if (state.query) performSearch(state.query, { scroll: false }); });
elements.reset.addEventListener("click", () => { elements.filterPanel.reset(); state.filters = {}; performSearch(state.query, { scroll: false }); });
elements.sort.addEventListener("change", sortAndRenderRows);
elements.searchTab.addEventListener("click", () => switchView("search"));
elements.evaluationTab.addEventListener("click", () => switchView("evaluation"));
elements.showcaseCases.addEventListener("click", (event) => { const button = event.target.closest("[data-run-showcase]"); if (button) runShowcaseCase(button.dataset.runShowcase); });
elements.body.addEventListener("click", (event) => { const button = event.target.closest("[data-id]"); if (button) openTransaction(button.dataset.id); });
$("#closeDialog").addEventListener("click", () => elements.dialog.close());
document.querySelectorAll("[data-feedback]").forEach((button) => button.addEventListener("click", () => sendFeedback(button.dataset.feedback === "true")));
$("#helpButton").addEventListener("click", () => elements.help.showModal());
$("#closeHelp").addEventListener("click", () => elements.help.close());
[elements.dialog, elements.help].forEach((dialog) => dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); }));

loadData();
