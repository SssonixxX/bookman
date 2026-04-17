const state = {
  venues: [],
  facets: {},
  dashboard: null,
  followups: [],
  pipeline: { negotiations: [], closed_dates: [] },
  selectedVenueId: null,
  currentView: "dashboard",
};

const elements = {
  navTabs: [...document.querySelectorAll(".nav-tab")],
  views: [...document.querySelectorAll("[data-view-panel]")],
  viewTitle: document.getElementById("viewTitle"),
  statsGrid: document.getElementById("statsGrid"),
  pipelineBars: document.getElementById("pipelineBars"),
  priorityStack: document.getElementById("priorityStack"),
  recentUpdates: document.getElementById("recentUpdates"),
  monthlySummaryDonut: document.getElementById("monthlySummaryDonut"),
  monthlySummaryTotal: document.getElementById("monthlySummaryTotal"),
  monthlySummaryLegend: document.getElementById("monthlySummaryLegend"),
  agentCommissionTotal: document.getElementById("agentCommissionTotal"),
  agentCommissionMeta: document.getElementById("agentCommissionMeta"),
  venuesTableBody: document.getElementById("venuesTableBody"),
  venueForm: document.getElementById("venueForm"),
  detailDrawer: document.getElementById("detailDrawer"),
  detailBody: document.getElementById("detailBody"),
  detailTitle: document.getElementById("detailTitle"),
  closeDrawerButton: document.getElementById("closeDrawerButton"),
  quickCreateButton: document.getElementById("quickCreateButton"),
  clearFormButton: document.getElementById("clearFormButton"),
  deleteFormVenueButton: document.getElementById("deleteFormVenueButton"),
  toggleFiltersButton: document.getElementById("toggleFiltersButton"),
  venuesFilters: document.getElementById("venuesFilters"),
  resetCrmButton: document.getElementById("resetCrmButton"),
  resetFiltersButton: document.getElementById("resetFiltersButton"),
  followupCards: document.getElementById("followupCards"),
  dealCards: document.getElementById("dealCards"),
  closedDateCards: document.getElementById("closedDateCards"),
  toast: document.getElementById("toast"),
};

const formFields = ["venueId", "name", "city", "admin_area", "region", "country", "address", "custom_area", "category", "target_mood", "contact_person", "contact_role", "phone", "whatsapp", "email", "instagram", "website", "seasonality", "status", "priority", "next_action", "follow_up_date", "tags", "notes", "active_events"];
const filters = {
  q: document.getElementById("globalSearch"),
  country: document.getElementById("filterCountry"),
  region: document.getElementById("filterRegion"),
  city: document.getElementById("filterCity"),
  category: document.getElementById("filterCategory"),
  priority: document.getElementById("filterPriority"),
  status: document.getElementById("filterStatus"),
  seasonality: document.getElementById("filterSeasonality"),
  active_events: document.getElementById("filterActiveEvents"),
  custom_area: document.getElementById("filterCustomArea"),
  tag: document.getElementById("filterTag"),
};

const viewTitles = {
  dashboard: "Dashboard booking",
  venues: "Archivio locali",
  newVenue: "Nuovo locale",
  followups: "Follow-up operativi",
  deals: "Trattative e opportunità",
  closedDates: "Date chiuse",
  settings: "Impostazioni e roadmap",
};

const travelRateOptions = [
  { value: 0, label: "Entro 60 km: inclusa" },
  { value: 70, label: "61-150 km: +70 euro" },
  { value: 120, label: "151-250 km: +120 euro" },
  { value: 170, label: "251-350 km: +170 euro" },
  { value: 220, label: "351-450 km: +220 euro" },
  { value: 300, label: "451-600 km: +300 euro" },
];

function showToast(message) {
  elements.toast.textContent = message;
  elements.toast.classList.add("show");
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => elements.toast.classList.remove("show"), 2200);
}

async function fetchJSON(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const raw = await response.text();
  let data = {};
  try {
    data = raw ? JSON.parse(raw) : {};
  } catch (error) {
    throw new Error(response.ok ? "Risposta non valida dal server" : "Sessione scaduta o risposta non valida dal server");
  }
  if (!response.ok) {
    throw new Error(data.error || "Errore inatteso");
  }
  return data;
}

function switchView(viewName) {
  state.currentView = viewName;
  elements.viewTitle.textContent = viewTitles[viewName] || "Booking Manager";
  elements.navTabs.forEach((button) => button.classList.toggle("active", button.dataset.view === viewName));
  elements.views.forEach((view) => view.classList.toggle("active", view.dataset.viewPanel === viewName));
  if (viewName !== "venues") {
    setFiltersOpen(false);
  }
  if (window.innerWidth <= 980) {
    closeDrawer();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
}

function setFiltersOpen(isOpen) {
  if (!elements.venuesFilters || !elements.toggleFiltersButton) return;
  elements.venuesFilters.classList.toggle("mobile-open", isOpen);
  elements.toggleFiltersButton.setAttribute("aria-expanded", isOpen ? "true" : "false");
  elements.toggleFiltersButton.textContent = isOpen ? "Chiudi filtri" : "Filtri";
}

function badgeForPriority(priority) {
  if (!priority) return `<span class="badge neutral">Non assegnata</span>`;
  return `<span class="badge priority-badge-${priority.toLowerCase()}">Priorità ${priority}</span>`;
}

function badgeForStatus(status) {
  return `<span class="badge status-badge">${status}</span>`;
}

function dueClass(dateText) {
  if (!dateText) return "";
  const today = new Date().toISOString().slice(0, 10);
  if (dateText < today) return "overdue";
  if (dateText === today) return "today";
  return "";
}

function formatCurrency(value) {
  if (value === null || value === undefined || value === "") return "-";
  const numeric = Number(value);
  if (Number.isNaN(numeric)) return "-";
  return `${numeric.toLocaleString("it-IT", { minimumFractionDigits: numeric % 1 === 0 ? 0 : 2, maximumFractionDigits: 2 })} euro`;
}

function renderTravelRateOptions(selectedValue = 0) {
  const normalized = Number(selectedValue || 0);
  return travelRateOptions.map((option) => `
    <option value="${option.value}" ${normalized === option.value ? "selected" : ""}>${option.label}</option>
  `).join("");
}

function renderBookingBudgetEditor(bookingDate, context = "list") {
  if (bookingDate.derived) return "";
  const budgetValue = bookingDate.budget ?? "";
  const checked = bookingDate.radio_package ? "checked" : "";
  const travelFee = Number(bookingDate.travel_fee || 0);
  const totalLabel = bookingDate.total_budget !== null && bookingDate.total_budget !== undefined
    ? formatCurrency(bookingDate.total_budget)
    : "Non impostato";
  return `
    <div class="booking-budget-editor" data-booking-id="${bookingDate.id}" data-context="${context}">
      <div class="booking-budget-grid">
        <label>Budget chiusura
          <input type="number" min="0" step="0.01" data-field="budget" value="${budgetValue}">
        </label>
        <label>Tariffa trasferta
          <select data-field="travel_fee">${renderTravelRateOptions(travelFee)}</select>
        </label>
        <label class="checkbox-field compact-checkbox">Pacchetto radio
          <input type="checkbox" data-field="radio_package" ${checked}>
        </label>
        <div class="budget-total-box">
          <span>Totale</span>
          <strong data-role="total-budget">${totalLabel}</strong>
        </div>
      </div>
      <button class="link-btn booking-save-btn" type="button" data-action="save-booking-budget" data-id="${bookingDate.id}">Salva budget</button>
    </div>
  `;
}

function renderStats() {
  const dashboard = state.dashboard;
  if (!dashboard) return;

  const cards = [
    ["Totale contatti", dashboard.total_contacts],
    ["Da scremare", dashboard.status_counts["da scremare"] || 0],
    ["Priorità A", dashboard.priority_counts.A || 0],
    ["Priorità B", dashboard.priority_counts.B || 0],
    ["Priorità C", dashboard.priority_counts.C || 0],
    ["Da contattare", dashboard.status_counts["da contattare"] || 0],
    ["Contattati", dashboard.status_counts["contattato"] || 0],
    ["In attesa", dashboard.status_counts["in attesa"] || 0],
    ["Interessati", dashboard.status_counts.interessato || 0],
    ["Trattative", dashboard.status_counts.trattativa || 0],
    ["Date chiuse", dashboard.closed_dates || 0],
    ["Non interessati", dashboard.status_counts["non interessato"] || 0],
  ];

  elements.statsGrid.innerHTML = cards.map(([label, value]) => `
      <article class="stat-card">
        <span class="eyebrow">${label}</span>
        <strong>${value}</strong>
      </article>
    `).join("");

  const statusEntries = Object.entries(dashboard.status_counts);
  const maxStatusValue = Math.max(...statusEntries.map(([, value]) => value), 1);
  elements.pipelineBars.innerHTML = statusEntries.map(([status, value]) => `
      <div class="mini-bar">
        <div>
          <strong>${status}</strong>
          <span>${value}</span>
        </div>
        <progress value="${value}" max="${maxStatusValue}"></progress>
      </div>
    `).join("");

  const priorities = ["A", "B", "C"];
  const maxPriorityValue = Math.max(...priorities.map((key) => dashboard.priority_counts[key] || 0), 1);
  elements.priorityStack.innerHTML = priorities.map((priority) => {
    const count = dashboard.priority_counts[priority] || 0;
    const percent = Math.max(12, (count / maxPriorityValue) * 100);
    const color = priority === "A" ? "var(--priority-a)" : priority === "B" ? "var(--priority-b)" : "var(--priority-c)";
    return `
      <div class="priority-item">
        <div>
          <strong>Priorità ${priority}</strong>
          <p>${count} contatti</p>
        </div>
        <div class="priority-meter"><span style="width:${percent}%; background:${color};"></span></div>
      </div>
    `;
  }).join("");

  elements.recentUpdates.innerHTML = dashboard.recent_updates.length
    ? dashboard.recent_updates.map((item) => `
          <div class="timeline-item">
            <strong>${item.title}</strong>
            <p>${item.name}</p>
            <p>${item.details || ""}</p>
            <p>${new Date(item.created_at).toLocaleString("it-IT")}</p>
          </div>
        `).join("")
    : `<div class="empty-state">Nessun aggiornamento registrato.</div>`;

  renderMonthlySummary(dashboard);
  renderAgentCommission(dashboard);
}

function renderAgentCommission(dashboard) {
  const commissionTotal = Number(dashboard.agent_commission_total || 0);
  const grossTotal = Number(dashboard.closed_dates_gross_total || 0);
  const commissionRate = Number(dashboard.agent_commission_rate || 0.15) * 100;
  elements.agentCommissionTotal.textContent = formatCurrency(commissionTotal);
  elements.agentCommissionMeta.textContent = `${commissionRate.toLocaleString("it-IT", { maximumFractionDigits: 0 })}% su ${formatCurrency(grossTotal)}`;
}

function renderMonthlySummary(dashboard) {
  const followups = Number(dashboard.follow_up_summary?.scheduled || 0);
  const pipelineStatuses = ["interessato", "call da fare", "trattativa", "data opzionata"];
  const pipeline = pipelineStatuses.reduce((sum, key) => sum + Number(dashboard.status_counts?.[key] || 0), 0);
  const closed = Number(dashboard.closed_dates || 0);
  const total = followups + pipeline + closed;

  const percent = (value) => (total ? Math.round((value / total) * 100) : 0);
  const followupsPercent = percent(followups);
  const pipelinePercent = percent(pipeline);
  const closedPercent = percent(closed);

  const followupsEnd = `${followupsPercent}%`;
  const pipelineEnd = `${followupsPercent + pipelinePercent}%`;
  const closedEnd = `${Math.min(100, followupsPercent + pipelinePercent + closedPercent)}%`;

  elements.monthlySummaryTotal.textContent = String(total);
  elements.monthlySummaryDonut.style.setProperty("--segment-followups", followupsEnd);
  elements.monthlySummaryDonut.style.setProperty("--segment-pipeline-end", pipelineEnd);
  elements.monthlySummaryDonut.style.setProperty("--segment-closed-end", closedEnd);
  elements.monthlySummaryLegend.innerHTML = `
    <div><strong>${followupsPercent}%</strong><span>Follow-up</span></div>
    <div><strong>${pipelinePercent}%</strong><span>Pipeline</span></div>
    <div><strong>${closedPercent}%</strong><span>Chiuse</span></div>
  `;
}

function fillSelectOptions(select, values, placeholder) {
  const currentValue = select.value;
  select.innerHTML = `<option value="">${placeholder}</option>` + values.map((value) => `<option value="${value}">${value}</option>`).join("");
  select.value = currentValue;
}

function renderVenueTable() {
  elements.venuesTableBody.innerHTML = state.venues.length
    ? state.venues.map((venue) => `
          <tr>
            <td>
              <strong>${venue.name}</strong>
              <div>${venue.contact_person || "Nessun referente"}</div>
            </td>
            <td>${[venue.city, venue.region, venue.country].filter(Boolean).join(", ") || "-"}</td>
            <td>${venue.category || "-"}</td>
            <td>${badgeForStatus(venue.status)}</td>
            <td>${badgeForPriority(venue.priority)}</td>
            <td><span class="${dueClass(venue.follow_up_date)}">${venue.follow_up_date || "-"}</span></td>
            <td>
              <div class="inline-actions">
                <button class="link-btn" data-action="detail" data-id="${venue.id}">Apri</button>
                <button class="link-btn" data-action="edit" data-id="${venue.id}">Modifica</button>
                <button class="link-btn danger-btn" data-action="delete" data-id="${venue.id}">Elimina</button>
              </div>
            </td>
          </tr>
        `).join("")
    : `<tr><td colspan="7"><div class="empty-state">Nessun contatto trovato con i filtri attivi.</div></td></tr>`;
}

function renderCards(container, items, renderer, emptyText) {
  container.innerHTML = items.length ? items.map(renderer).join("") : `<div class="empty-state">${emptyText}</div>`;
}

function renderFollowups() {
  renderCards(
    elements.followupCards,
    state.followups,
    (item) => `
      <article class="card-item">
        <div class="panel-header">
          <h3>${item.name}</h3>
          ${badgeForPriority(item.priority)}
        </div>
        <p>${[item.city, item.country].filter(Boolean).join(", ")}</p>
        <p>${badgeForStatus(item.status)}</p>
        <p class="${dueClass(item.follow_up_date)}">Follow-up: ${item.follow_up_date || "-"}</p>
        <p>Prossima azione: ${item.next_action || "Non definita"}</p>
        <div class="inline-actions">
          <button class="link-btn" data-action="detail" data-id="${item.id}">Apri scheda</button>
        </div>
      </article>
    `,
    "Nessun follow-up pianificato."
  );
}

function renderPipeline() {
  renderCards(
    elements.dealCards,
    state.pipeline.negotiations,
    (item) => `
      <article class="card-item">
        <div class="panel-header">
          <h3>${item.name}</h3>
          ${badgeForStatus(item.status)}
        </div>
        <p>${[item.city, item.country].filter(Boolean).join(", ")}</p>
        <p>${badgeForPriority(item.priority)}</p>
        <p>Prossima azione: ${item.next_action || "Da definire"}</p>
        <p class="${dueClass(item.follow_up_date)}">Follow-up: ${item.follow_up_date || "-"}</p>
        <div class="inline-actions">
          <button class="link-btn" data-action="detail" data-id="${item.id}">Apri scheda</button>
        </div>
      </article>
    `,
    "Nessuna trattativa attiva al momento."
  );

  renderCards(
    elements.closedDateCards,
    state.pipeline.closed_dates,
    (item) => `
      <article class="card-item closed-date-card">
        <div class="closed-date-header">
          <div class="closed-date-title">
            <h3>${item.event_title}</h3>
            <p>${item.venue_name}</p>
          </div>
          <span class="badge neutral">${item.event_date}</span>
        </div>
        <div class="closed-date-meta">
          <p>${[item.city, item.country].filter(Boolean).join(", ")}</p>
          <p>${item.notes || "Nessuna nota evento"}</p>
        </div>
        ${!item.derived ? `<div class="closed-date-finance">${renderBookingBudgetEditor(item, "list")}</div>` : ""}
        <div class="inline-actions closed-date-actions">
          <button class="link-btn" data-action="detail" data-id="${item.venue_id}">Apri scheda</button>
          ${item.derived ? "" : `<button class="link-btn danger-btn" data-action="delete-booking-date" data-id="${item.id}">Elimina data</button>`}
        </div>
      </article>
    `,
    "Nessuna data chiusa registrata."
  );

  [...elements.closedDateCards.querySelectorAll(".booking-budget-editor")].forEach((editor) => {
    bindBookingBudgetEditor(editor);
  });
}

function populateFilters() {
  fillSelectOptions(filters.country, state.facets.countries || [], "Nazione");
  fillSelectOptions(filters.region, state.facets.regions || [], "Regione / area");
  fillSelectOptions(filters.city, state.facets.cities || [], "Città");
  fillSelectOptions(filters.category, state.facets.categories || [], "Categoria");
  fillSelectOptions(filters.priority, state.facets.priorities || [], "Priorità");
  fillSelectOptions(filters.status, state.facets.statuses || [], "Stato");
  fillSelectOptions(filters.seasonality, state.facets.seasonalities || [], "Stagionalità");
  fillSelectOptions(filters.custom_area, state.facets.customAreas || [], "Area personalizzata");
}

function collectFilters() {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, input]) => {
    const value = input.value.trim();
    if (value) params.set(key, value);
  });
  return params.toString();
}

async function loadDashboard() {
  state.dashboard = await fetchJSON("/api/dashboard");
  renderStats();
}

async function loadVenues() {
  const query = collectFilters();
  const url = query ? `/api/venues?${query}` : "/api/venues";
  const data = await fetchJSON(url);
  state.venues = data.items;
  state.facets = data.facets;
  populateFilters();
  renderVenueTable();
}

async function loadFollowups() {
  state.followups = await fetchJSON("/api/followups");
  renderFollowups();
}

async function loadPipeline() {
  state.pipeline = await fetchJSON("/api/pipeline");
  renderPipeline();
}

function setFormData(venue = null) {
  elements.venueForm.reset();
  const nextActionField = document.getElementById("next_action");
  [...nextActionField.querySelectorAll("option[data-custom='true']")].forEach((option) => option.remove());
  formFields.forEach((fieldId) => {
    const field = document.getElementById(fieldId);
    if (!field) return;
    if (!venue) {
      if (field.type === "checkbox") field.checked = false;
      else field.value = "";
      return;
    }
    if (field.type === "checkbox") field.checked = Boolean(venue[fieldId]);
    else if (fieldId === "venueId") field.value = venue.id || "";
    else if (fieldId === "tags") field.value = (venue.tags || []).join(", ");
    else field.value = venue[fieldId] ?? "";
  });
  if (venue?.next_action && nextActionField && ![...nextActionField.options].some((option) => option.value === venue.next_action)) {
    const customOption = document.createElement("option");
    customOption.dataset.custom = "true";
    customOption.value = venue.next_action;
    customOption.textContent = `${venue.next_action} (attuale)`;
    nextActionField.appendChild(customOption);
  }
  document.getElementById("status").value = venue?.status || "da scremare";
  document.getElementById("priority").value = venue?.priority || "";
  document.getElementById("formTitle").textContent = venue ? `Modifica scheda: ${venue.name}` : "Inserimento rapido locale";
  elements.deleteFormVenueButton.classList.toggle("hidden", !venue?.id);
  elements.deleteFormVenueButton.dataset.id = venue?.id || "";
}

function collectFormData() {
  return {
    name: document.getElementById("name").value,
    city: document.getElementById("city").value,
    admin_area: document.getElementById("admin_area").value,
    region: document.getElementById("region").value,
    country: document.getElementById("country").value,
    address: document.getElementById("address").value,
    custom_area: document.getElementById("custom_area").value,
    category: document.getElementById("category").value,
    target_mood: document.getElementById("target_mood").value,
    contact_person: document.getElementById("contact_person").value,
    contact_role: document.getElementById("contact_role").value,
    phone: document.getElementById("phone").value,
    whatsapp: document.getElementById("whatsapp").value,
    email: document.getElementById("email").value,
    instagram: document.getElementById("instagram").value,
    website: document.getElementById("website").value,
    seasonality: document.getElementById("seasonality").value,
    status: document.getElementById("status").value,
    priority: document.getElementById("priority").value,
    next_action: document.getElementById("next_action").value,
    follow_up_date: document.getElementById("follow_up_date").value,
    tags: document.getElementById("tags").value,
    notes: document.getElementById("notes").value,
    active_events: document.getElementById("active_events").checked,
  };
}

async function submitVenueForm(event) {
  event.preventDefault();
  const venueId = document.getElementById("venueId").value;
  const payload = collectFormData();
  const method = venueId ? "PUT" : "POST";
  const url = venueId ? `/api/venues/${venueId}` : "/api/venues";

  try {
    const result = await fetchJSON(url, { method, body: JSON.stringify(payload) });
    const baseMessage = venueId ? "Scheda aggiornata" : "Locale inserito";
    showToast(result.auto_created_booking_date ? `${baseMessage} e data chiusa registrata` : baseMessage);
    setFormData(null);
    switchView("venues");
    await Promise.all([loadDashboard(), loadVenues(), loadFollowups(), loadPipeline()]);
  } catch (error) {
    showToast(error.message);
  }
}

async function openVenueDetail(venueId) {
  try {
    const data = await fetchJSON(`/api/venues/${venueId}`);
    state.selectedVenueId = venueId;
    elements.detailTitle.textContent = data.venue.name;
    elements.detailBody.innerHTML = `
      <section class="detail-grid">
        <div class="detail-box">
          <strong>Localizzazione</strong>
          <p>${[data.venue.address, data.venue.city, data.venue.region, data.venue.country].filter(Boolean).join(", ") || "-"}</p>
        </div>
        <div class="detail-box">
          <strong>Categoria e mood</strong>
          <p>${data.venue.category || "-"}</p>
          <p>${data.venue.target_mood || "Nessuna nota mood"}</p>
        </div>
        <div class="detail-box">
          <strong>Referente</strong>
          <p>${data.venue.contact_person || "-"}</p>
          <p>${data.venue.contact_role || ""}</p>
        </div>
        <div class="detail-box">
          <strong>Contatti</strong>
          <p>${data.venue.phone || "-"}</p>
          <p>${data.venue.email || "-"}</p>
          <p>${data.venue.whatsapp || "-"}</p>
        </div>
      </section>
      <section class="detail-box">
        <div class="panel-header">
          <h3>Stato operativo</h3>
          ${badgeForStatus(data.venue.status)}
        </div>
        <p>${badgeForPriority(data.venue.priority)}</p>
        <p>Prossima azione: ${data.venue.next_action || "Non definita"}</p>
        <p class="${dueClass(data.venue.follow_up_date)}">Follow-up: ${data.venue.follow_up_date || "-"}</p>
        <p>Tag: ${(data.venue.tags || []).join(", ") || "-"}</p>
        <p>Eventi attivi: ${data.venue.active_events ? "Sì" : "No"}</p>
      </section>
      <section class="detail-box">
        <div class="panel-header">
          <h3>Note interne</h3>
          <button class="link-btn" id="editCurrentVenue">Modifica</button>
        </div>
        <p>${data.venue.notes || "Nessuna nota disponibile."}</p>
      </section>
      <section class="detail-box">
        <div class="panel-header">
          <h3>Storico attività</h3>
        </div>
        <div class="timeline">
          ${data.activities.length ? data.activities.map((activity) => `
                <div class="timeline-item">
                  <strong>${activity.title}</strong>
                  <p>${activity.details || ""}</p>
                  <p>${new Date(activity.created_at).toLocaleString("it-IT")}</p>
                </div>
              `).join("") : `<div class="empty-state">Nessuna attività registrata.</div>`}
        </div>
      </section>
        <section class="detail-box">
          <div class="panel-header">
            <h3>Date chiuse</h3>
          </div>
          <div class="timeline">
          ${data.booking_dates.length ? data.booking_dates.map((bookingDate) => `
                <div class="timeline-item">
                  <div class="panel-header">
                    <strong>${bookingDate.event_title}</strong>
                    ${bookingDate.derived
                      ? `<span class="badge neutral">Derivata</span>`
                      : `<button class="link-btn danger-btn" type="button" data-action="delete-booking-date" data-id="${bookingDate.id}">Elimina data</button>`}
                  </div>
                  <p>${bookingDate.event_date}</p>
                  <p>${bookingDate.notes || ""}</p>
                  ${!bookingDate.derived ? `<p>Budget: ${formatCurrency(bookingDate.total_budget)}</p>` : ""}
                  ${renderBookingBudgetEditor(bookingDate, "drawer")}
                  ${bookingDate.derived ? `<p>Questa voce arriva dallo stato del locale, non da un evento salvato.</p>` : ""}
                </div>
              `).join("") : `<div class="empty-state">Nessuna data registrata.</div>`}
          </div>
        </section>
      <section class="detail-box">
        <div class="panel-header">
          <h3>Aggiungi nota rapida</h3>
        </div>
        <form id="activityForm">
          <label>Titolo<input name="title" required placeholder="Es. Chiamata iniziale"></label>
          <label>Dettagli<textarea name="details" rows="3" placeholder="Esito, impressioni, prossimi passi"></textarea></label>
          <div class="form-actions">
            <button class="primary-btn" type="submit">Salva attività</button>
          </div>
        </form>
      </section>
      <section class="detail-box">
        <div class="panel-header">
          <h3>Registra data chiusa</h3>
        </div>
        <form id="bookingDateForm">
          <label>Titolo evento<input name="event_title" required placeholder="Es. Summer Live Night"></label>
          <label>Data evento<input name="event_date" type="date" required></label>
          <label>Budget chiusura<input name="budget" type="number" min="0" step="0.01" placeholder="Es. 800"></label>
          <label>Tariffa trasferta
            <select name="travel_fee">
              ${renderTravelRateOptions(0)}
            </select>
          </label>
          <label class="checkbox-field compact-checkbox">Pacchetto radio
            <input name="radio_package" type="checkbox">
          </label>
          <p class="budget-preview" id="bookingDateFormTotal">Totale: Non impostato</p>
          <label>Note<textarea name="notes" rows="2" placeholder="Dettagli accordo, cachet, orari"></textarea></label>
          <div class="form-actions">
            <button class="primary-btn" type="submit">Registra data</button>
            <button class="secondary-btn" type="button" id="deleteVenueButton">Elimina contatto</button>
          </div>
        </form>
      </section>
    `;

    elements.detailDrawer.classList.add("open");
    elements.detailDrawer.setAttribute("aria-hidden", "false");
    document.getElementById("editCurrentVenue").addEventListener("click", () => {
      editVenue(venueId);
      closeDrawer();
    });
    document.getElementById("activityForm").addEventListener("submit", submitActivityForm);
    document.getElementById("bookingDateForm").addEventListener("submit", submitBookingDateForm);
    document.getElementById("deleteVenueButton").addEventListener("click", () => deleteVenue(venueId));
    bindBookingDateFormPreview(document.getElementById("bookingDateForm"));
    [...elements.detailBody.querySelectorAll("button[data-action='delete-booking-date']")].forEach((button) => {
      button.addEventListener("click", () => deleteBookingDate(button.dataset.id));
    });
    [...elements.detailBody.querySelectorAll("button[data-action='save-booking-budget']")].forEach((button) => {
      button.addEventListener("click", () => saveBookingBudget(button.dataset.id, button.closest(".booking-budget-editor")));
    });
    [...elements.detailBody.querySelectorAll(".booking-budget-editor")].forEach((editor) => {
      bindBookingBudgetEditor(editor);
    });
  } catch (error) {
    showToast(error.message);
  }
}

function closeDrawer() {
  elements.detailDrawer.classList.remove("open");
  elements.detailDrawer.setAttribute("aria-hidden", "true");
  state.selectedVenueId = null;
}

function editVenue(venueId) {
  const venue = state.venues.find((item) => item.id === Number(venueId));
  if (!venue) return;
  setFormData(venue);
  switchView("newVenue");
}

async function submitActivityForm(event) {
  event.preventDefault();
  const formData = new FormData(event.currentTarget);
  try {
    await fetchJSON(`/api/venues/${state.selectedVenueId}/activities`, {
      method: "POST",
      body: JSON.stringify({
        title: formData.get("title"),
        details: formData.get("details"),
        activity_type: "manual",
      }),
    });
    showToast("Attività salvata");
    await Promise.all([loadDashboard(), loadVenues(), loadFollowups(), loadPipeline(), openVenueDetail(state.selectedVenueId)]);
  } catch (error) {
    showToast(error.message);
  }
}

async function submitBookingDateForm(event) {
  event.preventDefault();
  const formData = new FormData(event.currentTarget);
  try {
    await fetchJSON(`/api/venues/${state.selectedVenueId}/booking-dates`, {
      method: "POST",
      body: JSON.stringify({
        event_title: formData.get("event_title"),
        event_date: formData.get("event_date"),
        budget: formData.get("budget"),
        travel_fee: formData.get("travel_fee"),
        radio_package: formData.get("radio_package") === "on",
        notes: formData.get("notes"),
      }),
    });
    showToast("Data registrata");
    await Promise.all([loadDashboard(), loadVenues(), loadFollowups(), loadPipeline(), openVenueDetail(state.selectedVenueId)]);
  } catch (error) {
    showToast(error.message);
  }
}

async function deleteBookingDate(bookingDateId) {
  const confirmed = window.confirm("Vuoi eliminare questa data chiusa?");
  if (!confirmed) return;
  try {
    const result = await fetchJSON(`/api/booking-dates/${bookingDateId}`, { method: "DELETE" });
    showToast(result.reopened_venue ? "Data chiusa eliminata e locale riaperto" : "Data chiusa eliminata");
    await Promise.all([loadDashboard(), loadVenues(), loadFollowups(), loadPipeline()]);
    if (state.selectedVenueId) {
      await openVenueDetail(state.selectedVenueId);
    }
  } catch (error) {
    showToast(error.message);
  }
}

function updateBookingBudgetPreview(editor) {
  if (!editor) return;
  const budgetInput = editor.querySelector("[data-field='budget']");
  const travelSelect = editor.querySelector("[data-field='travel_fee']");
  const radioCheckbox = editor.querySelector("[data-field='radio_package']");
  const totalLabel = editor.querySelector("[data-role='total-budget']");
  const baseBudget = Number(budgetInput?.value || 0);
  const travelFee = Number(travelSelect?.value || 0);
  const hasBudget = budgetInput?.value !== "";
  const hasExtras = Boolean(travelFee || radioCheckbox?.checked);
  const total = hasBudget || hasExtras ? baseBudget + travelFee + (radioCheckbox?.checked ? 200 : 0) : null;
  totalLabel.textContent = total === null || Number.isNaN(total) ? "Non impostato" : formatCurrency(total);
}

function bindBookingBudgetEditor(editor) {
  if (!editor) return;
  const budgetInput = editor.querySelector("[data-field='budget']");
  const travelSelect = editor.querySelector("[data-field='travel_fee']");
  const radioCheckbox = editor.querySelector("[data-field='radio_package']");
  if (budgetInput) {
    budgetInput.addEventListener("input", () => updateBookingBudgetPreview(editor));
  }
  if (travelSelect) {
    travelSelect.addEventListener("change", () => updateBookingBudgetPreview(editor));
  }
  if (radioCheckbox) {
    radioCheckbox.addEventListener("change", () => updateBookingBudgetPreview(editor));
  }
  updateBookingBudgetPreview(editor);
}

function bindBookingDateFormPreview(form) {
  if (!form) return;
  const budgetInput = form.querySelector("input[name='budget']");
  const travelSelect = form.querySelector("select[name='travel_fee']");
  const radioCheckbox = form.querySelector("input[name='radio_package']");
  const totalLabel = form.querySelector("#bookingDateFormTotal");
  const render = () => {
    const baseBudget = Number(budgetInput?.value || 0);
    const travelFee = Number(travelSelect?.value || 0);
    const hasBudget = budgetInput?.value !== "";
    const hasExtras = Boolean(travelFee || radioCheckbox?.checked);
    const total = hasBudget || hasExtras ? baseBudget + travelFee + (radioCheckbox?.checked ? 200 : 0) : null;
    totalLabel.textContent = `Totale: ${total === null || Number.isNaN(total) ? "Non impostato" : formatCurrency(total)}`;
  };
  budgetInput?.addEventListener("input", render);
  travelSelect?.addEventListener("change", render);
  radioCheckbox?.addEventListener("change", render);
  render();
}

async function saveBookingBudget(bookingDateId, editor) {
  if (!editor) return;
  const budgetInput = editor.querySelector("[data-field='budget']");
  const travelSelect = editor.querySelector("[data-field='travel_fee']");
  const radioCheckbox = editor.querySelector("[data-field='radio_package']");
  try {
    const result = await fetchJSON(`/api/booking-dates/${bookingDateId}`, {
      method: "PATCH",
      body: JSON.stringify({
        budget: budgetInput?.value || "",
        travel_fee: travelSelect?.value || "0",
        radio_package: Boolean(radioCheckbox?.checked),
      }),
    });
    showToast(`Budget salvato: ${result.total_budget !== null && result.total_budget !== undefined ? formatCurrency(result.total_budget) : "nessun totale"}`);
    await Promise.all([loadDashboard(), loadVenues(), loadFollowups(), loadPipeline()]);
    if (state.selectedVenueId) {
      await openVenueDetail(state.selectedVenueId);
    }
  } catch (error) {
    showToast(error.message);
  }
}

async function deleteVenue(venueId) {
  const confirmed = window.confirm("Vuoi eliminare questo contatto?");
  if (!confirmed) return;
  try {
    await fetchJSON(`/api/venues/${venueId}`, { method: "DELETE" });
    showToast("Contatto eliminato");
    closeDrawer();
    setFormData(null);
    await Promise.all([loadDashboard(), loadVenues(), loadFollowups(), loadPipeline()]);
  } catch (error) {
    showToast(error.message);
  }
}

function delegateDetailButtons(event) {
  const button = event.target.closest("button[data-action='detail']");
  if (!button) return;
  openVenueDetail(button.dataset.id);
}

function delegateClosedDateButtons(event) {
  const actionButton = event.target.closest("button[data-action]");
  if (!actionButton) return;
  if (actionButton.dataset.action === "detail") {
    openVenueDetail(actionButton.dataset.id);
    return;
  }
  if (actionButton.dataset.action === "delete-booking-date") {
    deleteBookingDate(actionButton.dataset.id);
    return;
  }
  if (actionButton.dataset.action === "save-booking-budget") {
    saveBookingBudget(actionButton.dataset.id, actionButton.closest(".booking-budget-editor"));
  }
}

async function resetCrm() {
  const confirmed = window.confirm("Vuoi resettare completamente il CRM? Tutti i locali, le attivita e le date chiuse verranno eliminati.");
  if (!confirmed) return;
  try {
    await fetchJSON("/api/reset-crm", { method: "POST" });
    closeDrawer();
    setFormData(null);
    showToast("CRM resettato");
    switchView("dashboard");
    await Promise.all([loadDashboard(), loadVenues(), loadFollowups(), loadPipeline()]);
  } catch (error) {
    showToast(error.message);
  }
}

function attachEvents() {
  elements.navTabs.forEach((button) => {
    button.addEventListener("click", () => switchView(button.dataset.view));
  });

  Object.values(filters).forEach((input) => {
    input.addEventListener("input", () => loadVenues().catch((error) => showToast(error.message)));
    input.addEventListener("change", () => loadVenues().catch((error) => showToast(error.message)));
  });

  elements.venueForm.addEventListener("submit", submitVenueForm);
  elements.venuesTableBody.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-action]");
    if (!button) return;
    const venueId = button.dataset.id;
    if (button.dataset.action === "detail") openVenueDetail(venueId);
    if (button.dataset.action === "edit") editVenue(venueId);
    if (button.dataset.action === "delete") deleteVenue(venueId);
  });
  elements.followupCards.addEventListener("click", delegateDetailButtons);
  elements.dealCards.addEventListener("click", delegateDetailButtons);
  elements.closedDateCards.addEventListener("click", delegateClosedDateButtons);
  elements.quickCreateButton.addEventListener("click", () => {
    setFormData(null);
    switchView("newVenue");
  });
  elements.clearFormButton.addEventListener("click", () => setFormData(null));
  elements.deleteFormVenueButton.addEventListener("click", () => {
    const venueId = elements.deleteFormVenueButton.dataset.id;
    if (!venueId) return;
    deleteVenue(venueId);
  });
  if (elements.resetCrmButton) {
    elements.resetCrmButton.addEventListener("click", resetCrm);
  }
  if (elements.toggleFiltersButton) {
    elements.toggleFiltersButton.addEventListener("click", () => {
      const isOpen = elements.venuesFilters?.classList.contains("mobile-open");
      setFiltersOpen(!isOpen);
    });
  }
  elements.closeDrawerButton.addEventListener("click", closeDrawer);
  elements.resetFiltersButton.addEventListener("click", () => {
    Object.values(filters).forEach((input) => {
      input.value = "";
    });
    setFiltersOpen(false);
    loadVenues().catch((error) => showToast(error.message));
  });
}

async function bootstrap() {
  attachEvents();
  setFormData(null);
  setFiltersOpen(false);
  try {
    await Promise.all([loadDashboard(), loadVenues(), loadFollowups(), loadPipeline()]);
  } catch (error) {
    showToast(error.message);
  }
}

bootstrap();
