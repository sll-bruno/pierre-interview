const state = {
  allTransactions: [],
  results: [],
  query: "",
  filters: {},
  selected: null,
  interpretation: null,
  backendAvailable: true,
  evaluationReady: false,
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
  evaluationStatus: $("#evaluationStatus"), runQuality: $("#runQuality"), qualityMessage: $("#qualityMessage"), qualityMetrics: $("#qualityMetrics"),
  runLoad: $("#runLoad"), loadMessage: $("#loadMessage"), loadMetrics: $("#loadMetrics"), loadRequests: $("#loadRequests"), loadConcurrency: $("#loadConcurrency"),
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
    const response = await fetch("/ai_engineer_semantic_transactions.csv");
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
    const response = await fetch("/search", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ query: state.query, filters: apiFilters }) });
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
    const response = await fetch("/feedback", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ query: state.query, transaction_id: state.selected.transaction_id, relevant }) });
    if (!response.ok) throw new Error("Feedback indisponível");
    elements.dialog.close(); showToast("Valeu. Feedback registrado.");
  } catch {
    showToast("Não foi possível registrar o feedback.");
  }
}

function showToast(message) { elements.toast.textContent = message; elements.toast.classList.add("show"); setTimeout(() => elements.toast.classList.remove("show"), 2200); }

function formatPercent(value) { return value == null ? "—" : `${Math.round(value * 100)}%`; }
function formatMs(value) { return value == null ? "—" : `${Math.round(value)} ms`; }

function renderMetrics(container, metrics) {
  container.hidden = false;
  container.innerHTML = metrics.map(({ label, value, neutral = false }) => `<div class="metric"><span>${escapeHtml(label)}</span><strong class="${neutral ? "neutral" : ""}">${escapeHtml(String(value))}</strong></div>`).join("");
}

function setRunMessage(element, message, error = false) {
  element.textContent = message;
  element.classList.toggle("error", error);
}

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
    const response = await fetch("/evaluation/status");
    if (!response.ok) throw new Error("Status indisponível");
    const payload = await response.json();
    state.evaluationReady = Boolean(payload.available);
    elements.runQuality.disabled = !state.evaluationReady;
    elements.runLoad.disabled = !state.evaluationReady;
    if (state.evaluationReady) {
      elements.evaluationStatus.classList.add("ready");
      elements.evaluationStatus.textContent = `${payload.case_count} casos rotulados e ${payload.load_case_count} cenários de carga prontos.`;
    } else {
      elements.evaluationStatus.classList.add("error");
      elements.evaluationStatus.textContent = payload.reason || "Corpus de avaliação indisponível.";
    }
  } catch {
    state.evaluationReady = false;
    elements.runQuality.disabled = true; elements.runLoad.disabled = true;
    elements.evaluationStatus.classList.add("error");
    elements.evaluationStatus.textContent = "Não foi possível verificar o ambiente de avaliação.";
  }
}

function switchView(view) {
  const isEvaluation = view === "evaluation";
  elements.searchView.hidden = isEvaluation; elements.evaluationView.hidden = !isEvaluation;
  elements.searchTab.classList.toggle("active", !isEvaluation); elements.evaluationTab.classList.toggle("active", isEvaluation);
  elements.searchTab.setAttribute("aria-selected", String(!isEvaluation)); elements.evaluationTab.setAttribute("aria-selected", String(isEvaluation));
  if (isEvaluation) refreshEvaluationStatus();
}

async function runQuality() {
  if (!state.evaluationReady) return;
  elements.runQuality.disabled = true; elements.qualityMetrics.hidden = true;
  setRunMessage(elements.qualityMessage, "Rodando os casos rotulados…");
  try {
    const response = await fetch("/evaluation/quality", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ top_k: 10 }) });
    if (!response.ok) throw new Error(await responseError(response));
    const report = await response.json(); const summary = report.summary;
    renderMetrics(elements.qualityMetrics, [
      { label: "Aprovação", value: formatPercent(summary.exact_pass_rate) },
      { label: "Recall @10", value: formatPercent(summary.mean_recall_at_k) },
      { label: "MRR @10", value: formatPercent(summary.mrr_at_k) },
      { label: "p95 interno", value: formatMs(summary.latency_ms?.p95), neutral: true },
      { label: "Casos", value: summary.cases, neutral: true },
      { label: "Status OK", value: formatPercent(summary.status_pass_rate) },
    ]);
    setRunMessage(elements.qualityMessage, `${summary.cases} casos concluídos. Latência medida no motor de busca.`);
  } catch (error) {
    setRunMessage(elements.qualityMessage, error.message || "Falha ao rodar a avaliação.", true);
  } finally { elements.runQuality.disabled = !state.evaluationReady; }
}

function percentile(values, fraction) {
  if (!values.length) return null;
  const sorted = [...values].sort((left, right) => left - right);
  return sorted[Math.max(0, Math.ceil(sorted.length * fraction) - 1)];
}

async function runLoad() {
  if (!state.evaluationReady) return;
  const requests = Math.max(1, Math.min(5000, Number(elements.loadRequests.value) || 100));
  const concurrency = Math.max(1, Math.min(100, Number(elements.loadConcurrency.value) || 10));
  elements.loadRequests.value = requests; elements.loadConcurrency.value = concurrency;
  elements.runLoad.disabled = true; elements.loadMetrics.hidden = true;
  setRunMessage(elements.loadMessage, `Enviando ${requests} requisições com concorrência ${concurrency}…`);
  try {
    const casesResponse = await fetch("/evaluation/cases?tag=load");
    if (!casesResponse.ok) throw new Error(await responseError(casesResponse));
    const { cases } = await casesResponse.json();
    if (!cases.length) throw new Error("Não há cenários de carga disponíveis.");
    const workload = Array.from({ length: requests }, (_, index) => cases[index % cases.length]);
    const latencies = []; const statuses = {}; let cursor = 0;
    const started = performance.now();
    const worker = async () => {
      while (cursor < workload.length) {
        const current = workload[cursor++]; const requestStarted = performance.now();
        let status = 0;
        try {
          const response = await fetch("/search", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ query: current.query, filters: current.filters }) });
          status = response.status; await response.text();
        } catch { status = 0; }
        latencies.push(performance.now() - requestStarted); statuses[status] = (statuses[status] || 0) + 1;
      }
    };
    await Promise.all(Array.from({ length: Math.min(concurrency, requests) }, worker));
    const elapsed = performance.now() - started;
    const failed = latencies.length - (statuses[200] || 0);
    renderMetrics(elements.loadMetrics, [
      { label: "Throughput", value: `${(requests / (elapsed / 1000)).toFixed(1)} req/s` },
      { label: "p50 HTTP", value: formatMs(percentile(latencies, .50)), neutral: true },
      { label: "p95 HTTP", value: formatMs(percentile(latencies, .95)), neutral: true },
      { label: "p99 HTTP", value: formatMs(percentile(latencies, .99)), neutral: true },
      { label: "Falhas", value: formatPercent(failed / requests) },
      { label: "Sucessos", value: `${statuses[200] || 0}/${requests}`, neutral: true },
    ]);
    setRunMessage(elements.loadMessage, `${requests} requisições concluídas em ${(elapsed / 1000).toFixed(2)} s.`);
  } catch (error) {
    setRunMessage(elements.loadMessage, error.message || "Falha ao rodar a carga.", true);
  } finally { elements.runLoad.disabled = !state.evaluationReady; }
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
elements.runQuality.addEventListener("click", runQuality);
elements.runLoad.addEventListener("click", runLoad);
elements.body.addEventListener("click", (event) => { const button = event.target.closest("[data-id]"); if (button) openTransaction(button.dataset.id); });
$("#closeDialog").addEventListener("click", () => elements.dialog.close());
document.querySelectorAll("[data-feedback]").forEach((button) => button.addEventListener("click", () => sendFeedback(button.dataset.feedback === "true")));
$("#helpButton").addEventListener("click", () => elements.help.showModal());
$("#closeHelp").addEventListener("click", () => elements.help.close());
[elements.dialog, elements.help].forEach((dialog) => dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); }));

loadData();
