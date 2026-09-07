const state = {
    installed: [],
    config: null,
    issues: null,
    currentLookup: null,
    updates: [],
    searchMeta: null,
    portalSearch: {
        sort: "last_updated_at",
        query: "",
        page: 1,
        pageSize: 20,
        categories: new Set(),
        excludeCategories: new Set(["internal"]),
        tags: new Set(),
        excludeTags: new Set(),
        expansions: new Set(),
        excludeExpansions: new Set(),
        showDeprecated: false,
    },
};

const $ = id => document.getElementById(id);

function escapeHTML(v) {
    return String(v ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function toast(message, kind = "ok") {
    const el = $("toast");
    el.textContent = message;
    el.className = `toast ${kind}`;
    setTimeout(() => { el.className = ""; el.textContent = ""; }, 4500);
}

async function api(url, options = {}) {
    const res = await fetch(url, {
        headers: { "Content-Type": "application/json", ...(options.headers || {}) },
        ...options,
    });
    let data;
    try { data = await res.json(); }
    catch (_) { data = { ok: false, error: `HTTP ${res.status}` }; }
    if (!res.ok || !data.ok) throw new Error(data.error || `HTTP ${res.status}`);
    return data;
}

function busy(button, active, text = "Working...") {
    if (!button) return;
    if (active) {
        button.dataset.oldText = button.textContent;
        button.disabled = true;
        button.textContent = text;
    } else {
        button.disabled = false;
        button.textContent = button.dataset.oldText || button.textContent;
    }
}

function switchView(name) {
    document.querySelectorAll(".view").forEach(v => v.classList.remove("active"));
    document.querySelectorAll(".nav-item").forEach(v => v.classList.remove("active"));
    $(`view-${name}`).classList.add("active");
    document.querySelector(`.nav-item[data-view="${name}"]`).classList.add("active");
    const titles = {
        installed: "Installed Mods",
        discover: "Search Mods",
        updates: "Updates",
        profiles: "Profiles",
        settings: "Settings",
    };
    $("pageTitle").textContent = titles[name] || "Factorio Mod Manager";
    if (name === "discover") ensurePortalSearch();
    if (name === "updates") renderUpdates();
    if (name === "profiles") loadProfiles();
    if (name === "settings") loadDiagnostics();
}

async function loadConfig() {
    const data = await api("/api/config");
    state.config = data.config;
    $("modsDir").value = state.config.mods_dir || "";
    $("factorioVersion").value = state.config.factorio_version || "2.0";
    $("installDeps").checked = !!state.config.install_dependencies;
    $("factorioExecutable").value = state.config.factorio_executable || "";
    $("launchArgs").value = state.config.launch_args || "";
    $("modListPath").textContent = `mod-list.json: ${state.config.mod_list_path}`;
}

async function loadInstalled() {
    const data = await api("/api/installed");
    state.installed = data.mods || [];
    state.issues = data.issues || { missing: [], wrong_version: [], incompatible: [] };
    renderInstalled();
}

function totalIssues() {
    if (!state.issues) return 0;
    return state.issues.missing.length + state.issues.wrong_version.length + state.issues.incompatible.length;
}

function renderIssues() {
    const panel = $("issuePanel");
    const count = totalIssues();
    if (!count) { panel.classList.add("hidden"); panel.innerHTML = ""; return; }
    const rows = [];
    for (const issue of state.issues.missing) rows.push(`<div class="issue"><strong>Missing</strong> ${escapeHTML(issue.mod)} → ${escapeHTML(issue.requirement)}</div>`);
    for (const issue of state.issues.wrong_version) rows.push(`<div class="issue"><strong>Version</strong> ${escapeHTML(issue.mod)} → ${escapeHTML(issue.requirement)} (installed ${escapeHTML(issue.installed)})</div>`);
    for (const issue of state.issues.incompatible) rows.push(`<div class="issue"><strong>Conflict</strong> ${escapeHTML(issue.mod)} ↔ ${escapeHTML(issue.dependency)}</div>`);
    panel.innerHTML = `<h3>Dependency problems</h3>${rows.join("")}`;
    panel.classList.remove("hidden");
}

function renderInstalled() {
    const query = $("installedFilter").value.trim().toLowerCase();
    const mods = state.installed.filter(mod => `${mod.name} ${mod.title} ${mod.version}`.toLowerCase().includes(query));
    $("installedCount").textContent = state.installed.length;
    $("enabledCount").textContent = state.installed.filter(m => m.enabled).length;
    $("issueCount").textContent = totalIssues();
    renderIssues();
    if (!mods.length) { $("installedList").innerHTML = `<div class="empty">No installed mods found.</div>`; return; }
    $("installedList").innerHTML = mods.map(mod => `
        <article class="mod-row">
            <div class="mod-main">
                <div class="mod-icon">${escapeHTML((mod.title || mod.name).slice(0, 2).toUpperCase())}</div>
                <div><h3>${escapeHTML(mod.title)}</h3><p>${escapeHTML(mod.name)} · ${escapeHTML(mod.version)} · Factorio ${escapeHTML(mod.factorio_version || "?")}</p><span class="file">${escapeHTML(mod.file)}</span></div>
            </div>
            <div class="row-actions">
                <label class="switch" title="Enable/disable"><input type="checkbox" data-enable="${escapeHTML(mod.name)}" ${mod.enabled ? "checked" : ""}><span></span></label>
                <button class="ghost small" data-mod-settings="${escapeHTML(mod.name)}">⚙ Settings</button>
                <button class="ghost small" data-update="${escapeHTML(mod.name)}">Update</button>
                <button class="danger small" data-remove="${escapeHTML(mod.name)}">Remove</button>
            </div>
        </article>`).join("");
    document.querySelectorAll("[data-enable]").forEach(el => el.addEventListener("change", async () => {
        try { await api("/api/enable", {method:"POST", body:JSON.stringify({mod:el.dataset.enable, enabled:el.checked})}); await loadInstalled(); toast(`${el.dataset.enable} ${el.checked ? "enabled" : "disabled"}.`); }
        catch(err) { el.checked = !el.checked; toast(err.message, "error"); }
    }));
    document.querySelectorAll("[data-mod-settings]").forEach(el => el.addEventListener("click", () => openModSettings(el.dataset.modSettings)));
    document.querySelectorAll("[data-update]").forEach(el => el.addEventListener("click", () => updateOne(el.dataset.update, el)));
    document.querySelectorAll("[data-remove]").forEach(el => el.addEventListener("click", () => removeMod(el.dataset.remove, el)));
}

function closeModal() {
    $("modal").classList.add("hidden");
    $("modalBody").innerHTML = "";
}

function openModSettings(name) {
    const mod = state.installed.find(item => item.name === name);
    if (!mod) { toast(`Mod ${name} not found.`, "error"); return; }
    const deps = (mod.dependencies || []).map(dep => `<div class="mod-setting-dep">• ${escapeHTML(dep.raw || dep.name || "")}</div>`).join("") || `<div class="hint">No declared dependencies.</div>`;
    $("modalBody").innerHTML = `
        <div class="mod-settings-head"><div class="mod-icon">${escapeHTML((mod.title || mod.name).slice(0,2).toUpperCase())}</div><div><h2>${escapeHTML(mod.title || mod.name)}</h2><p>${escapeHTML(mod.name)} · v${escapeHTML(mod.version)} · Factorio ${escapeHTML(mod.factorio_version || "?")}</p></div></div>
        <div class="mod-settings-grid">
            <div><span>Author</span><strong>${escapeHTML(mod.author || "?")}</strong></div>
            <div><span>Type</span><strong>${escapeHTML(mod.kind || "?")}</strong></div>
            <div><span>In-game settings</span><strong>${mod.has_settings ? "settings.lua detected" : "None declared"}</strong></div>
            <div><span>File</span><strong>${escapeHTML(mod.file || "?")}</strong></div>
        </div>
        <label class="checkbox-row"><input type="checkbox" id="modalModEnabled" ${mod.enabled ? "checked" : ""}><span>Enabled</span></label>
        <div class="dependency-preview"><strong>Dependencies</strong>${deps}</div>
        ${mod.has_settings ? `<p class="hint good-note">Gameplay values are configured in Factorio → Settings → Mod settings.</p>` : ""}
        <div class="actions mod-settings-actions">
            <button class="ghost" id="modalOpenFolder">Open Folder</button>
            <button class="ghost" id="modalOpenPortal">Mod Portal</button>
            <button id="modalUpdateMod">Check / Update</button>
        </div>
        <p class="hint" id="modalModStatus"></p>`;
    $("modal").classList.remove("hidden");

    $("modalModEnabled").addEventListener("change", async e => {
        try { await api("/api/enable", {method:"POST", body:JSON.stringify({mod:name, enabled:e.target.checked})}); mod.enabled=e.target.checked; $("modalModStatus").textContent=`${name} ${e.target.checked ? "enabled" : "disabled"}.`; await loadInstalled(); }
        catch(err){ e.target.checked=!e.target.checked; $("modalModStatus").textContent=err.message; }
    });
    $("modalOpenFolder").addEventListener("click", async () => {
        try { const data=await api("/api/mod/open-location", {method:"POST", body:JSON.stringify({mod:name})}); $("modalModStatus").textContent=`Opened ${data.result.path}`; }
        catch(err){ $("modalModStatus").textContent=err.message; }
    });
    $("modalOpenPortal").addEventListener("click", () => window.open(`https://mods.factorio.com/mod/${encodeURIComponent(name)}`, "_blank", "noopener"));
    $("modalUpdateMod").addEventListener("click", async e => {
        busy(e.currentTarget,true,"Updating...");
        try { const data=await api("/api/update", {method:"POST", body:JSON.stringify({mod:name})}); $("modalModStatus").textContent=data.result.updated ? `${name}: ${data.result.from} → ${data.result.to}` : `${name} already current.`; await loadInstalled(); }
        catch(err){ $("modalModStatus").textContent=err.message; }
        finally{ busy(e.currentTarget,false); }
    });
}

// ---------- Factorio-style Mod Portal browser ----------
async function ensurePortalSearch() {
    try {
        if (!state.searchMeta) {
            const data = await api("/api/search-meta");
            state.searchMeta = data.meta;
            renderPortalTabs();
            renderPortalFilters();
        }
        await searchPortal(false);
    } catch (err) {
        $("portalResults").innerHTML = `<div class="panel error-box">${escapeHTML(err.message)}</div>`;
    }
}

function renderPortalTabs() {
    const target = $("portalTabs");
    target.innerHTML = state.searchMeta.sort_modes.map(mode => `
        <button class="portal-tab ${state.portalSearch.sort === mode.id ? "active" : ""}" data-portal-sort="${escapeHTML(mode.id)}">${escapeHTML(mode.label)}</button>
    `).join("");
    target.querySelectorAll("[data-portal-sort]").forEach(btn => btn.addEventListener("click", async () => {
        state.portalSearch.sort = btn.dataset.portalSort;
        state.portalSearch.page = 1;
        renderPortalTabs();
        await searchPortal(false);
    }));
}

function filterRowHTML(group, item) {
    return `<div class="portal-filter-row">
        <label><input type="checkbox" data-filter-include="${group}:${escapeHTML(item.id)}"><span>${escapeHTML(item.label)}</span></label>
        <button class="filter-ban" data-filter-exclude="${group}:${escapeHTML(item.id)}" title="Exclude ${escapeHTML(item.label)}">⊘</button>
    </div>`;
}

function renderPortalFilters() {
    $("expansionFilters").innerHTML = state.searchMeta.expansions.map(x => filterRowHTML("expansion", x)).join("");
    $("categoryFilters").innerHTML = state.searchMeta.categories.map(x => filterRowHTML("category", x)).join("");
    $("tagFilters").innerHTML = state.searchMeta.tags.map(x => filterRowHTML("tag", x)).join("");
    syncPortalFilterControls();

    document.querySelectorAll("[data-filter-include]").forEach(input => input.addEventListener("change", async () => {
        const [group, id] = input.dataset.filterInclude.split(":");
        const include = group === "category" ? state.portalSearch.categories : group === "tag" ? state.portalSearch.tags : state.portalSearch.expansions;
        const exclude = group === "category" ? state.portalSearch.excludeCategories : group === "tag" ? state.portalSearch.excludeTags : state.portalSearch.excludeExpansions;
        if (input.checked) { include.add(id); exclude.delete(id); } else include.delete(id);
        state.portalSearch.page = 1;
        syncPortalFilterControls();
        await searchPortal(false);
    }));

    document.querySelectorAll("[data-filter-exclude]").forEach(btn => btn.addEventListener("click", async () => {
        const [group, id] = btn.dataset.filterExclude.split(":");
        const include = group === "category" ? state.portalSearch.categories : group === "tag" ? state.portalSearch.tags : state.portalSearch.expansions;
        const exclude = group === "category" ? state.portalSearch.excludeCategories : group === "tag" ? state.portalSearch.excludeTags : state.portalSearch.excludeExpansions;
        include.delete(id);
        if (exclude.has(id)) exclude.delete(id); else exclude.add(id);
        state.portalSearch.page = 1;
        syncPortalFilterControls();
        await searchPortal(false);
    }));
}

function syncPortalFilterControls() {
    document.querySelectorAll("[data-filter-include]").forEach(input => {
        const [group, id] = input.dataset.filterInclude.split(":");
        const set = group === "category" ? state.portalSearch.categories : group === "tag" ? state.portalSearch.tags : state.portalSearch.expansions;
        input.checked = set.has(id);
    });
    document.querySelectorAll("[data-filter-exclude]").forEach(btn => {
        const [group, id] = btn.dataset.filterExclude.split(":");
        const set = group === "category" ? state.portalSearch.excludeCategories : group === "tag" ? state.portalSearch.excludeTags : state.portalSearch.excludeExpansions;
        btn.classList.toggle("active", set.has(id));
    });
    $("showDeprecated").checked = state.portalSearch.showDeprecated;
}

function searchPayload() {
    const s = state.portalSearch;
    return {
        query: s.query,
        sort_attribute: s.sort,
        page: s.page,
        page_size: s.pageSize,
        categories: [...s.categories],
        exclude_categories: [...s.excludeCategories],
        tags: [...s.tags],
        exclude_tags: [...s.excludeTags],
        expansions: [...s.expansions],
        exclude_expansions: [...s.excludeExpansions],
        show_deprecated: s.showDeprecated,
    };
}

async function searchPortal(fromInput = true) {
    if (fromInput) {
        state.portalSearch.query = $("modQuery").value.trim();
        state.portalSearch.page = 1;
        if (state.portalSearch.query && state.portalSearch.sort === "highlighted") state.portalSearch.sort = "relevancy";
        renderPortalTabs();
    }
    $("portalResultCount").textContent = "Searching Mod Portal...";
    $("portalResultSubtitle").textContent = "";
    $("portalResults").innerHTML = `<div class="empty">Loading mods...</div>`;
    try {
        const data = await api("/api/search-mods", {method:"POST", body:JSON.stringify(searchPayload())});
        renderPortalResults(data.search);
    } catch (err) {
        $("portalResultCount").textContent = "Search failed";
        $("portalResults").innerHTML = `<div class="panel error-box">${escapeHTML(err.message)}</div>`;
    }
}

function humanTime(iso) {
    if (!iso) return "";
    const t = new Date(iso).getTime();
    if (!Number.isFinite(t)) return iso;
    const sec = Math.max(0, Math.floor((Date.now() - t) / 1000));
    if (sec < 60) return `${sec}s ago`;
    if (sec < 3600) return `${Math.floor(sec/60)} minutes ago`;
    if (sec < 86400) return `${Math.floor(sec/3600)} hours ago`;
    if (sec < 86400*30) return `${Math.floor(sec/86400)} days ago`;
    return new Date(t).toLocaleDateString();
}

function formatDownloads(n) {
    n = Number(n || 0);
    if (n >= 1_000_000) return `${(n/1_000_000).toFixed(n >= 10_000_000 ? 0 : 1)}M`;
    if (n >= 1_000) return `${(n/1_000).toFixed(n >= 100_000 ? 0 : 1)}K`;
    return String(n);
}

function categoryLabel(id) {
    const item = state.searchMeta?.categories?.find(x => x.id === id);
    return item ? item.label : (id || "No category");
}

function tagLabel(id) {
    const item = state.searchMeta?.tags?.find(x => x.id === id);
    return item ? item.label : id;
}

function renderPortalResults(search) {
    const p = search.pagination || {};
    const results = search.results || [];
    state.portalSearch.page = p.page || 1;
    $("portalResultCount").textContent = `Found ${Number(p.count || 0).toLocaleString()} mods`;
    $("portalResultSubtitle").textContent = state.portalSearch.query ? `for “${state.portalSearch.query}”` : "";

    if (!results.length) {
        $("portalResults").innerHTML = `<div class="empty">No mods match these filters.</div>`;
    } else {
        $("portalResults").innerHTML = results.map(mod => {
            const initial = (mod.title || mod.name || "?").slice(0, 2).toUpperCase();
            const thumb = mod.thumbnail
                ? `<img class="portal-thumb" src="${escapeHTML(mod.thumbnail)}" alt="" loading="lazy">`
                : `<div class="portal-thumb placeholder">${escapeHTML(initial)}</div>`;
            const installed = mod.installed;
            let action = "Download";
            let actionClass = "download-button";
            if (installed && mod.update_available) action = `Update ${escapeHTML(installed.version)} → ${escapeHTML(mod.latest_version || "latest")}`;
            else if (installed) { action = `Installed ${escapeHTML(installed.version)}`; actionClass += " installed"; }
            const tags = (mod.tags || []).map(tag => `<span class="portal-tag">${escapeHTML(tagLabel(tag))}</span>`).join("");
            return `<article class="portal-mod-card">
                <div class="portal-card-main">
                    ${thumb}
                    <div class="portal-card-copy">
                        <button class="portal-title" data-details-mod="${escapeHTML(mod.name)}">${escapeHTML(mod.title)}</button>
                        <div class="portal-author">by <strong>${escapeHTML(mod.owner)}</strong></div>
                        <div class="portal-summary">${escapeHTML(mod.summary)}</div>
                    </div>
                    <div class="portal-card-meta">
                        <span>♟ ${escapeHTML(categoryLabel(mod.category))}</span>
                        ${mod.updated_at ? `<span>◷ ${escapeHTML(humanTime(mod.updated_at))}</span>` : ""}
                        <span>⚙ ${escapeHTML(mod.factorio_version_display || "?")}</span>
                        <span>⇩ ${escapeHTML(formatDownloads(mod.downloads_count))}</span>
                        ${mod.requires_space_age ? `<span class="space-age-mark">🌌 Space Age</span>` : ""}
                    </div>
                </div>
                <div class="portal-card-footer">
                    <div class="portal-tags">${tags || `<span class="portal-tag muted-tag">No tags</span>`}</div>
                    <button class="${actionClass}" data-search-install="${escapeHTML(mod.name)}" ${installed && !mod.update_available ? "disabled" : ""}>⇩ ${action}</button>
                </div>
            </article>`;
        }).join("");
    }

    document.querySelectorAll("[data-search-install]").forEach(btn => btn.addEventListener("click", () => installFromSearch(btn.dataset.searchInstall, btn)));
    document.querySelectorAll("[data-details-mod]").forEach(btn => btn.addEventListener("click", async () => {
        $("modQuery").value = btn.dataset.detailsMod;
        await lookupMod(btn.dataset.detailsMod);
        $("lookupResult").scrollIntoView({behavior:"smooth", block:"start"});
    }));

    const pagination = paginationHTML(p.page || 1, p.page_count || 1);
    $("portalPaginationTop").innerHTML = pagination;
    $("portalPaginationBottom").innerHTML = pagination;
    document.querySelectorAll("[data-portal-page]").forEach(btn => btn.addEventListener("click", async () => {
        const page = Number(btn.dataset.portalPage);
        if (!page || page === state.portalSearch.page) return;
        state.portalSearch.page = page;
        await searchPortal(false);
        $("portalResultCount").scrollIntoView({behavior:"smooth", block:"start"});
    }));
}

function paginationHTML(page, pageCount) {
    if (pageCount <= 1) return "";
    const pages = new Set([1, pageCount, page - 1, page, page + 1]);
    const valid = [...pages].filter(x => x >= 1 && x <= pageCount).sort((a,b) => a-b);
    const parts = [];
    if (page > 1) parts.push(`<button data-portal-page="${page-1}">‹</button>`);
    let last = 0;
    for (const p of valid) {
        if (last && p - last > 1) parts.push(`<span>…</span>`);
        parts.push(`<button class="${p === page ? "active" : ""}" data-portal-page="${p}">${p}</button>`);
        last = p;
    }
    if (page < pageCount) parts.push(`<button data-portal-page="${page+1}">›</button>`);
    return parts.join("");
}

async function installFromSearch(name, button) {
    busy(button, true, "Installing...");
    try {
        const data = await api("/api/install", {method:"POST", body:JSON.stringify({mod:name, include_dependencies:state.config?.install_dependencies ?? true, enable:true})});
        const installed = data.result.installed || [];
        toast(installed.length ? `Installed ${installed.map(x => `${x.name} ${x.version}`).join(", ")}` : `${name} already current.`);
        await loadInstalled();
        await searchPortal(false);
    } catch (err) { toast(err.message, "error"); }
    finally { busy(button, false); }
}

async function lookupMod(value = null) {
    const query = (value ?? $("modQuery").value).trim();
    if (!query) return;
    const button = $("lookupBtn");
    busy(button, true, "Looking up...");
    try {
        const data = await api(`/api/mod?q=${encodeURIComponent(query)}`);
        state.currentLookup = data.mod;
        renderLookup();
    } catch (err) {
        $("lookupResult").innerHTML = `<div class="panel error-box">${escapeHTML(err.message)}</div>`;
    } finally { busy(button, false); }
}

function compatibleReleases(mod) {
    const branch = (state.config?.factorio_version || "2.0").split(".").slice(0,2).join(".");
    return mod.releases.filter(r => String(r.factorio_version || "").split(".").slice(0,2).join(".") === branch);
}

function renderLookup() {
    const mod = state.currentLookup;
    if (!mod) return;
    const releases = compatibleReleases(mod);
    const latest = releases[0];
    $("lookupResult").innerHTML = `<article class="detail-card portal-detail-card">
        <div class="detail-head">
            ${mod.thumbnail ? `<img src="${escapeHTML(mod.thumbnail)}" alt="">` : `<div class="detail-placeholder">${escapeHTML(mod.title.slice(0,2).toUpperCase())}</div>`}
            <div><h2>${escapeHTML(mod.title)}</h2><p>${escapeHTML(mod.summary)}</p><div class="chips"><span>${escapeHTML(mod.name)}</span><span>${escapeHTML(mod.owner)}</span><span>${Number(mod.downloads_count||0).toLocaleString()} downloads</span></div></div>
        </div>
        <div class="install-box"><div><label>Compatible version</label><select id="lookupVersion">${releases.map(r => `<option value="${escapeHTML(r.version)}">${escapeHTML(r.version)} — Factorio ${escapeHTML(r.factorio_version)}</option>`).join("")}</select></div><button id="installLookupBtn" ${latest ? "" : "disabled"}>${mod.installed ? "Install / Change Version" : "Install"}</button></div>
        ${latest ? `<div id="lookupDeps" class="dependency-preview"></div>` : `<div class="error-box">No compatible release for Factorio ${escapeHTML(state.config.factorio_version)}.</div>`}
    </article>`;
    if (!latest) return;
    const select = $("lookupVersion");
    function renderDeps() {
        const release = releases.find(r => r.version === select.value);
        const builtins = ["base","core","quality","space-age","elevated-rails"];
        const required = (release.dependencies||[]).filter(d => d.kind === "required" && !builtins.includes(d.name));
        const optional = (release.dependencies||[]).filter(d => d.kind === "optional");
        $("lookupDeps").innerHTML = `<strong>Dependencies</strong><p>Required: ${required.length ? required.map(d=>escapeHTML(d.raw)).join(", ") : "None"}</p><p>Optional: ${optional.length ? optional.map(d=>escapeHTML(d.raw)).join(", ") : "None"}</p>`;
    }
    renderDeps(); select.addEventListener("change", renderDeps);
    $("installLookupBtn").addEventListener("click", async event => {
        const button = event.currentTarget; busy(button, true, "Installing...");
        try {
            const data = await api("/api/install", {method:"POST", body:JSON.stringify({mod:mod.name, version:select.value, include_dependencies:$("installDeps").checked, enable:true})});
            const installed = data.result.installed || [];
            toast(installed.length ? `Installed ${installed.map(x=>`${x.name} ${x.version}`).join(", ")}` : "Already up to date.");
            await loadInstalled();
        } catch(err) { toast(err.message, "error"); }
        finally { busy(button, false); }
    });
}

async function checkUpdates(button = null) {
    busy(button, true, "Checking...");
    $("updatesList").innerHTML = `<div class="empty">Checking Mod Portal...</div>`;
    try { const data = await api("/api/updates"); state.updates = data.updates || []; renderUpdates(); }
    catch(err) { $("updatesList").innerHTML = `<div class="panel error-box">${escapeHTML(err.message)}</div>`; }
    finally { busy(button, false); }
}

function renderUpdates() {
    if (!state.updates.length) { $("updatesList").innerHTML = `<div class="empty">Press Check to compare installed mods.</div>`; return; }
    $("updatesList").innerHTML = state.updates.map(item => `<article class="mod-row"><div><h3>${escapeHTML(item.title||item.name)}</h3><p>${escapeHTML(item.installed)} ${item.latest ? `→ ${escapeHTML(item.latest)}` : ""} ${item.error ? ` · ${escapeHTML(item.error)}` : ""}</p></div><div>${item.update_available ? `<button data-update="${escapeHTML(item.name)}">Update</button>` : `<span class="good">${item.error ? "Unavailable" : "Current"}</span>`}</div></article>`).join("");
    $("updatesList").querySelectorAll("[data-update]").forEach(el => el.addEventListener("click", () => updateOne(el.dataset.update, el, true)));
}

async function updateOne(name, button, refreshUpdates=false) {
    busy(button, true, "Updating...");
    try {
        const data = await api("/api/update", {method:"POST", body:JSON.stringify({mod:name})});
        toast(data.result.updated ? `${name}: ${data.result.from} → ${data.result.to}` : `${name} is already current.`);
        await loadInstalled(); if (refreshUpdates) await checkUpdates();
    } catch(err) { toast(err.message, "error"); }
    finally { busy(button, false); }
}

async function removeMod(name, button) {
    if (!confirm(`Remove ${name} from the Factorio mods folder?`)) return;
    busy(button, true, "Removing...");
    try { await api("/api/remove", {method:"POST", body:JSON.stringify({mod:name, force:false})}); toast(`${name} removed.`); await loadInstalled(); }
    catch(err) {
        if (err.message.includes("dibutuhkan oleh") && confirm(`${err.message}\n\nForce remove anyway?`)) {
            try { await api("/api/remove", {method:"POST", body:JSON.stringify({mod:name, force:true})}); toast(`${name} force removed.`); await loadInstalled(); }
            catch(forceErr) { toast(forceErr.message, "error"); }
        } else toast(err.message, "error");
    } finally { busy(button, false); }
}

async function saveSettings() {
    const button = $("saveSettingsBtn"); busy(button, true, "Saving...");
    try {
        const data = await api("/api/config", {method:"POST", body:JSON.stringify({mods_dir:$("modsDir").value.trim(), factorio_version:$("factorioVersion").value.trim(), install_dependencies:$("installDeps").checked, factorio_executable:$("factorioExecutable").value.trim(), launch_args:$("launchArgs").value.trim()})});
        state.config = data.config; toast("Settings saved."); await loadConfig(); await loadInstalled(); state.searchMeta = null;
    } catch(err) { toast(err.message, "error"); }
    finally { busy(button, false); }
}

async function updateAll() {
    const button = $("updateAllBtn"); if (!confirm("Update every mod that has a compatible newer release?")) return;
    busy(button, true, "Updating...");
    try { const data = await api("/api/update-all", {method:"POST", body:"{}"}); const count=(data.result.updated||[]).length; const errors=data.result.errors||[]; toast(`Updated ${count} mod(s)${errors.length ? `, ${errors.length} failed` : ""}.`, errors.length ? "warn" : "ok"); await loadInstalled(); await checkUpdates(); }
    catch(err) { toast(err.message, "error"); }
    finally { busy(button, false); }
}

async function loadProfiles() {
    const target = $("profilesList"); target.innerHTML = `<div class="empty">Loading profiles...</div>`;
    try {
        const data = await api("/api/profiles"); const profiles = data.profiles || [];
        target.innerHTML = profiles.length ? profiles.map(p => `<article class="mod-row"><div><h3>${escapeHTML(p.name)}</h3><p>${p.mod_count} mods · Factorio ${escapeHTML(p.factorio_version||"?")}</p></div><div class="actions"><button data-profile-apply="${escapeHTML(p.name)}">Apply</button><button class="danger small" data-profile-delete="${escapeHTML(p.name)}">Delete</button></div></article>`).join("") : `<div class="empty">No profiles yet.</div>`;
        target.querySelectorAll("[data-profile-apply]").forEach(btn => btn.addEventListener("click", async () => { busy(btn,true,"Applying..."); try { const data=await api("/api/profile/apply",{method:"POST",body:JSON.stringify({name:btn.dataset.profileApply})}); toast(`Applied ${btn.dataset.profileApply}; ${(data.result.errors||[]).length} error(s).`); await loadInstalled(); } catch(err){toast(err.message,"error");} finally{busy(btn,false);} }));
        target.querySelectorAll("[data-profile-delete]").forEach(btn => btn.addEventListener("click", async () => { if(!confirm(`Delete profile ${btn.dataset.profileDelete}?`)) return; try{await api("/api/profile/delete",{method:"POST",body:JSON.stringify({name:btn.dataset.profileDelete})});toast("Profile deleted.");await loadProfiles();}catch(err){toast(err.message,"error");} }));
    } catch(err) { target.innerHTML = `<div class="panel error-box">${escapeHTML(err.message)}</div>`; }
}

async function saveProfile() {
    const name=$("profileName").value.trim(); if(!name){toast("Enter a profile name.","error");return;}
    try{const data=await api("/api/profile/save",{method:"POST",body:JSON.stringify({name})});toast(`Saved ${data.result.name}.`);$("profileName").value="";await loadProfiles();}catch(err){toast(err.message,"error");}
}

async function checkAppUpdate(showToast = true) {
    const button = $("checkAppUpdateBtn");
    const pull = $("pullAppUpdateBtn");
    const statusEl = $("appUpdateStatus");
    busy(button, true, "Checking...");
    statusEl.textContent = "Checking origin/main...";
    try {
        const data = await api("/api/app-update");
        const s = data.status;
        if (!s.git_repo) {
            statusEl.textContent = s.message || "Not a Git clone.";
            pull.disabled = true;
        } else if (s.update_available) {
            statusEl.textContent = `Update available: ${s.local_short} → ${s.remote_short} · ${s.behind} commit(s)${s.dirty ? " · local changes detected; commit/stash first" : ""}`;
            pull.disabled = !!(s.dirty || s.ahead);
            if (showToast) toast("Application update available.", "warn");
        } else {
            statusEl.textContent = `Up to date · ${s.local_short || "?"}`;
            pull.disabled = true;
            if (showToast) toast("Application is up to date.");
        }
    } catch(err) {
        statusEl.textContent = err.message;
        pull.disabled = true;
        if (showToast) toast(err.message, "error");
    } finally { busy(button, false); }
}

async function pullAppUpdate() {
    const button = $("pullAppUpdateBtn");
    const statusEl = $("appUpdateStatus");
    busy(button, true, "Pulling...");
    try {
        const data = await api("/api/app-update/pull", {method:"POST", body:"{}"});
        if (data.result.changed) {
            const after = data.result.after || {};
            statusEl.textContent = `Updated to ${after.local_short || "new commit"}. Restart Factorio Mod Manager to load the new code.`;
            toast("Update pulled. Restart the app to apply it.");
        } else {
            statusEl.textContent = "Already up to date.";
            toast("Already up to date.");
        }
    } catch(err) {
        statusEl.textContent = err.message;
        toast(err.message, "error");
    } finally { button.disabled = true; }
}

async function loadDiagnostics() {
    try { const data=await api("/api/diagnostics"); const d=data.diagnostics; $("diagnosticsBox").innerHTML=`<div class="panel"><strong>Diagnostics</strong><p class="hint">Installed ${d.installed_count} · Enabled ${d.enabled_count} · Dependency issues ${d.dependency_issue_count} · Duplicate groups ${d.duplicates.length} · Invalid files ${d.invalid_files.length}</p></div>`; }
    catch(err){$("diagnosticsBox").innerHTML=`<div class="error-box">${escapeHTML(err.message)}</div>`;}
}

async function maintenance(endpoint,message){try{const data=await api(endpoint,{method:"POST",body:"{}"});toast(message);await loadInstalled();await loadDiagnostics();return data;}catch(err){toast(err.message,"error");}}

document.querySelectorAll(".nav-item").forEach(button => button.addEventListener("click", () => switchView(button.dataset.view)));
$("installedFilter").addEventListener("input", renderInstalled);
$("lookupBtn").addEventListener("click", () => lookupMod());
$("portalSearchBtn").addEventListener("click", () => searchPortal(true));
$("modQuery").addEventListener("keydown", e => { if (e.key === "Enter") searchPortal(true); });
$("showDeprecated").addEventListener("change", async e => { state.portalSearch.showDeprecated = e.target.checked; state.portalSearch.page=1; await searchPortal(false); });
$("resetPortalFilters").addEventListener("click", async () => {
    for (const key of ["categories","excludeCategories","tags","excludeTags","expansions","excludeExpansions"]) state.portalSearch[key].clear();
    state.portalSearch.showDeprecated=false; state.portalSearch.page=1; syncPortalFilterControls(); await searchPortal(false);
});
$("checkUpdatesBtn").addEventListener("click", e => checkUpdates(e.currentTarget));
$("updateAllBtn").addEventListener("click", updateAll);
$("saveSettingsBtn").addEventListener("click", saveSettings);
$("saveProfileBtn").addEventListener("click", saveProfile);
$("checkAppUpdateBtn").addEventListener("click", () => checkAppUpdate(true));
$("pullAppUpdateBtn").addEventListener("click", pullAppUpdate);
$("modalClose").addEventListener("click", closeModal);
$("modal").addEventListener("click", e => { if (e.target === $("modal")) closeModal(); });
$("backupBtn").addEventListener("click", () => maintenance("/api/backup", "Backup created."));
$("repairBtn").addEventListener("click", () => maintenance("/api/repair", "Dependency repair finished."));
$("cleanDuplicatesBtn").addEventListener("click", () => maintenance("/api/clean-duplicates", "Duplicate cleanup finished."));
$("launchFactorioBtn").addEventListener("click", () => maintenance("/api/launch", "Factorio launched."));
$("refreshBtn").addEventListener("click", async () => { try { await Promise.all([loadConfig(),loadInstalled()]); toast("Refreshed."); } catch(err){toast(err.message,"error");} });

(async function init(){try{await loadConfig();await loadInstalled();}catch(err){toast(err.message,"error");}})();
