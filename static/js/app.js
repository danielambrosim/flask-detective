(() => {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  const USERNAME_RE = /^[A-Za-z0-9_][A-Za-z0-9._-]{0,49}$/;
  const POLL_MS = 1000;

  const form = $("#search-form");
  const input = $("#username");
  const submitBtn = $("#submit-btn");
  const errorBox = $("#form-error");
  const picker = $("#site-picker");
  const siteFilter = $("#site-filter");
  const siteList = $("#site-list");
  const emptyFilter = $("#empty-filter");
  const selectedCount = $("#selected-count");
  const maxSites = Number(picker.dataset.max) || 60;

  const section = $("#resultados");
  const grid = $("#result-grid");
  const resultsFilter = $("#results-filter");

  let state = { job: null, timer: null, rendered: new Set(), found: [] };

  // ---------------- utilidades ----------------
  function showError(msg) {
    errorBox.textContent = msg;
    errorBox.hidden = !msg;
    input.setAttribute("aria-invalid", msg ? "true" : "false");
  }

  let toastTimer;
  function toast(msg) {
    const el = $("#toast");
    el.textContent = msg;
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (el.hidden = true), 2600);
  }

  function setLoading(on) {
    submitBtn.disabled = on;
    submitBtn.classList.toggle("is-loading", on);
    $(".btn-label", submitBtn).textContent = on ? "Buscando…" : "Pesquisar";
  }

  function mode() {
    return ($('input[name="mode"]:checked') || {}).value || "all";
  }

  function selectedSites() {
    return $$('input[name="sites"]:checked', siteList).map((el) => el.value);
  }

  // ---------------- seletor de sites ----------------
  function syncPicker() {
    picker.hidden = mode() !== "custom";
  }

  function syncSelection() {
    const chosen = new Set(selectedSites());
    selectedCount.textContent = chosen.size;
    $$(".chip").forEach((chip) => chip.setAttribute("aria-pressed", String(chosen.has(chip.dataset.site))));
  }

  function checkboxFor(site) {
    return $$('input[name="sites"]', siteList).find((el) => el.value === site);
  }

  $$('input[name="mode"]').forEach((r) => r.addEventListener("change", () => { syncPicker(); showError(""); }));

  $("#popular-chips").addEventListener("click", (e) => {
    const chip = e.target.closest(".chip");
    if (!chip) return;
    const cb = checkboxFor(chip.dataset.site);
    if (!cb) return;
    if (!cb.checked && selectedSites().length >= maxSites) return toast(`Máximo de ${maxSites} sites.`);
    cb.checked = !cb.checked;
    syncSelection();
  });

  siteList.addEventListener("change", (e) => {
    if (e.target.checked && selectedSites().length > maxSites) {
      e.target.checked = false;
      toast(`Máximo de ${maxSites} sites.`);
    }
    syncSelection();
  });

  $("#clear-sites").addEventListener("click", () => {
    $$('input[name="sites"]', siteList).forEach((el) => (el.checked = false));
    syncSelection();
  });

  siteFilter.addEventListener("input", () => {
    const q = siteFilter.value.trim().toLowerCase();
    let visible = 0;
    $$(".site-option", siteList).forEach((el) => {
      const show = !q || el.dataset.name.includes(q);
      el.hidden = !show;
      if (show) visible++;
    });
    emptyFilter.hidden = visible > 0;
  });

  // ---------------- busca ----------------
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (state.job && state.timer) return; // já existe busca em andamento

    const username = input.value.trim().replace(/^@+/, "");
    if (!username) return showError("Digite um nome de usuário."), input.focus();
    if (!USERNAME_RE.test(username)) {
      showError("Usuário inválido. Use letras, números, ponto, hífen e underline (sem começar com ponto ou hífen).");
      return input.focus();
    }
    const payload = { username, mode: mode() };
    if (payload.mode === "custom") {
      payload.sites = selectedSites();
      if (!payload.sites.length) return showError("Selecione pelo menos um site.");
    }

    showError("");
    setLoading(true);
    try {
      const res = await fetch("/api/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || "Não foi possível iniciar a busca.");
      startResults(data);
    } catch (err) {
      setLoading(false);
      showError(err.message || "Falha de conexão. Tente novamente.");
    }
  });

  function startResults(job) {
    state = { job, timer: null, rendered: new Set(), found: [] };
    grid.replaceChildren();
    resultsFilter.value = "";
    $("#results-user").textContent = "@" + job.username;
    $("#empty-state").hidden = true;
    $("#results-actions").hidden = true;
    $("#results-toolbar").hidden = true;
    $("#progress").classList.remove("is-done", "is-error");
    section.hidden = false;
    section.scrollIntoView({ behavior: "smooth", block: "start" });
    render(job);
    poll();
  }

  async function poll() {
    try {
      const res = await fetch(`/api/search/${encodeURIComponent(state.job.id)}`, { cache: "no-store" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || "Erro ao consultar a busca.");
      state.job = data;
      render(data);
      if (data.status === "done" || data.status === "error") return finish(data);
    } catch (err) {
      return finish({ ...state.job, status: "error", error: err.message });
    }
    state.timer = setTimeout(poll, POLL_MS);
  }

  function finish(job) {
    clearTimeout(state.timer);
    state.timer = null;
    setLoading(false);
    render(job);
  }

  function render(job) {
    const done = job.status === "done";
    const failed = job.status === "error";
    const pct = done ? 100 : job.progress || 0;
    const bar = $("#progress");
    $("#progress-bar").style.width = pct + "%";
    bar.setAttribute("aria-valuenow", String(pct));
    bar.classList.toggle("is-done", done);
    bar.classList.toggle("is-error", failed);

    $("#results-eyebrow").textContent = done ? "Busca concluída" : failed ? "Busca interrompida" : "Buscando…";
    $("#progress-text").textContent = failed
      ? job.error || "A busca falhou."
      : done
        ? `${job.found.length} perfil(is) encontrado(s) em ${job.total} site(s).`
        : `${job.checked} de ${job.total} sites verificados…`;

    $("#stat-found").textContent = job.found.length;
    $("#stat-checked").textContent = `${job.checked}/${job.total}`;
    $("#stat-failed").textContent = job.failed;
    $("#stat-time").textContent = `${Math.round(job.elapsed || 0)}s`;

    job.found.forEach((r) => {
      if (state.rendered.has(r.url)) return;
      state.rendered.add(r.url);
      state.found.push(r);
      grid.appendChild(card(r));
    });
    // mantém a grade em ordem alfabética
    if (done) {
      const items = $$(".result-item", grid).sort((a, b) => a.dataset.name.localeCompare(b.dataset.name));
      grid.replaceChildren(...items);
    }

    const hasResults = state.found.length > 0;
    $("#results-actions").hidden = !hasResults;
    $("#results-toolbar").hidden = !hasResults;
    $("#empty-state").hidden = !(done && !hasResults);
  }

  function safeHttpUrl(u) {
    try {
      const url = new URL(u);
      return url.protocol === "http:" || url.protocol === "https:" ? url : null;
    } catch {
      return null;
    }
  }

  function card(r) {
    const li = document.createElement("li");
    li.className = "result-item";
    li.dataset.name = r.site.toLowerCase();

    const url = safeHttpUrl(r.url);
    const article = document.createElement("article");
    article.className = "result-card";

    const top = document.createElement("div");
    top.className = "result-top";
    const fav = document.createElement("span");
    fav.className = "favicon";
    fav.textContent = r.site.charAt(0).toUpperCase();
    const home = safeHttpUrl(r.home) || url;
    if (home) {
      const img = document.createElement("img");
      img.alt = "";
      // Sem loading="lazy": a imagem só entra no DOM depois de carregar.
      img.referrerPolicy = "no-referrer";
      img.src = `https://www.google.com/s2/favicons?sz=64&domain=${encodeURIComponent(home.hostname)}`;
      img.addEventListener("load", () => fav.replaceChildren(img), { once: true });
    }
    const meta = document.createElement("div");
    meta.style.minWidth = "0";
    const name = document.createElement("h3");
    name.className = "result-name";
    name.textContent = r.site;
    const link = document.createElement("span");
    link.className = "result-url";
    link.textContent = url ? url.host + url.pathname : r.url;
    link.title = r.url;
    meta.append(name, link);
    top.append(fav, meta);
    article.append(top);

    if (url) {
      const a = document.createElement("a");
      a.className = "btn btn-outline btn-sm";
      a.href = url.href;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      a.textContent = "Abrir perfil";
      a.setAttribute("aria-label", `Abrir perfil no ${r.site}`);
      article.append(a);
    }
    li.append(article);
    return li;
  }

  resultsFilter.addEventListener("input", () => {
    const q = resultsFilter.value.trim().toLowerCase();
    $$(".result-item", grid).forEach((li) => (li.hidden = q && !li.dataset.name.includes(q)));
  });

  // ---------------- exportação ----------------
  $("#copy-links").addEventListener("click", async () => {
    const text = state.found.map((r) => r.url).join("\n");
    try {
      await navigator.clipboard.writeText(text);
      toast(`${state.found.length} link(s) copiado(s).`);
    } catch {
      toast("Não foi possível copiar.");
    }
  });

  $("#download-csv").addEventListener("click", () => {
    const esc = (v) => {
      let s = String(v ?? "");
      if (/^[=+\-@\t\r]/.test(s)) s = "'" + s; // evita injeção de fórmulas no Excel
      return `"${s.replace(/"/g, '""')}"`;
    };
    const rows = [["site", "url", "tempo_resposta_s"], ...state.found.map((r) => [r.site, r.url, r.time ?? ""])];
    const csv = "﻿" + rows.map((row) => row.map(esc).join(",")).join("\r\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    a.download = `detective-${state.job.username}.csv`;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 0);
  });

  // ---------------- header ----------------
  const header = $(".site-header");
  const onScroll = () => header.classList.toggle("is-scrolled", window.scrollY > 4);
  window.addEventListener("scroll", onScroll, { passive: true });

  // Ao voltar pelo histórico (bfcache), garante o botão no estado certo.
  window.addEventListener("pageshow", () => { if (!state.timer) setLoading(false); });

  onScroll();
  syncPicker();
  syncSelection();
})();
