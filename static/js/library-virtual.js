/**
 * Virtualized language library grid.
 * Only mounts rows near the viewport; fetches light JSON chunks by offset.
 */
(function () {
  const root = document.getElementById("lang-virt");
  if (!root) return;

  const phantom = root.querySelector(".lang-virt-phantom");
  const windowEl = root.querySelector(".lang-virt-window");
  const total = Number(root.dataset.total || 0);
  const chunk = Number(root.dataset.chunk || 48);
  const api = root.dataset.api || "";
  const sizes = root.dataset.sizes || "(max-width: 767px) 42vw, (max-width: 1023px) 25vw, 180px";
  const q = root.dataset.q || "";
  const genre = root.dataset.genre || "";
  const sort = root.dataset.sort || "year";

  if (!total || !phantom || !windowEl || !api) return;

  const cache = new Map(); // index -> item
  const pending = new Set();
  const loadedChunks = new Set();
  let cols = 4;
  let rowHeight = 420;
  let gap = 20;
  let raf = 0;
  let overscan = 2;

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function measureCols() {
    const w = root.clientWidth || window.innerWidth;
    if (w <= 767) return 2;
    if (w <= 1023) return 3;
    return 4;
  }

  function measureLayout() {
    cols = measureCols();
    const styles = getComputedStyle(windowEl);
    gap = parseFloat(styles.rowGap || styles.gap || "20") || 20;
    // Probe with a temporary card if we have data
    const probe = windowEl.querySelector(".lang-lib-card");
    if (probe) {
      rowHeight = Math.max(280, probe.getBoundingClientRect().height + gap);
    } else {
      const colW = (root.clientWidth - gap * (cols - 1)) / cols;
      rowHeight = Math.round(colW * 1.55 + 140);
    }
    const rows = Math.ceil(total / cols);
    phantom.style.height = `${rows * rowHeight}px`;
  }

  function coverHtml(item, eager) {
    const avif = item.coverAvif || "";
    const webp = item.coverWebp || "";
    const src = item.cover || "/covers/placeholder.svg";
    const loading = eager ? "eager" : "lazy";
    if (avif || webp) {
      return `<picture>
        ${avif ? `<source type="image/avif" srcset="${escapeHtml(avif)}" sizes="${escapeHtml(sizes)}" />` : ""}
        ${webp ? `<source type="image/webp" srcset="${escapeHtml(webp)}" sizes="${escapeHtml(sizes)}" />` : ""}
        <img src="${escapeHtml(src)}" alt="${escapeHtml(item.title)} 封面" width="180" height="270" loading="${loading}" decoding="async" onerror="this.onerror=null;this.src='/covers/placeholder.svg'" />
      </picture>`;
    }
    return `<img src="${escapeHtml(src)}" alt="${escapeHtml(item.title)} 封面" width="180" height="270" loading="${loading}" decoding="async" onerror="this.onerror=null;this.src='/covers/placeholder.svg'" />`;
  }

  function cardHtml(item, index) {
    const year = item.year ? ` · ${item.year}` : "";
    const chinese = item.chinese
      ? `<p class="lang-lib-zh">${escapeHtml(item.chinese)}</p>`
      : "";
    const blurb = item.blurb
      ? `<p class="lang-lib-blurb">${escapeHtml(item.blurb)}</p>`
      : "";
    return `<article class="lang-lib-card" data-index="${index}">
      <a href="${escapeHtml(item.href)}">
        ${coverHtml(item, index < 6)}
        <h3>${escapeHtml(item.title)}</h3>
        ${chinese}
        <p class="lang-lib-author">${escapeHtml(item.author)}${year}</p>
        <p class="lang-lib-meta"><span class="book-lang">${escapeHtml(item.langZh)}</span> <span class="lang-pick-genre">${escapeHtml(item.genre)}</span></p>
        ${blurb}
      </a>
    </article>`;
  }

  function storeChunk(offset, items) {
    items.forEach((item, i) => {
      cache.set(offset + i, item);
    });
    loadedChunks.add(offset);
  }

  function fetchChunk(offset) {
    const start = Math.floor(offset / chunk) * chunk;
    if (pending.has(start) || loadedChunks.has(start)) return;
    pending.add(start);
    windowEl.setAttribute("aria-busy", "true");
    const params = new URLSearchParams({
      offset: String(start),
      limit: String(chunk),
      sort,
    });
    if (q) params.set("q", q);
    if (genre) params.set("genre", genre);
    fetch(`${api}?${params.toString()}`, { headers: { Accept: "application/json" } })
      .then((r) => (r.ok ? r.json() : Promise.reject(r)))
      .then((data) => {
        storeChunk(start, data.items || []);
        scheduleRender();
      })
      .catch(() => {
        pending.delete(start);
      })
      .finally(() => {
        pending.delete(start);
        if (!pending.size) windowEl.setAttribute("aria-busy", "false");
      });
  }

  function ensureRange(startIndex, endIndex) {
    for (let i = startIndex; i <= endIndex; i += 1) {
      if (!cache.has(i)) {
        fetchChunk(i);
        i = Math.floor(i / chunk) * chunk + chunk - 1;
      }
    }
  }

  function visibleRange() {
    const rootTop = root.getBoundingClientRect().top + window.scrollY;
    const scrollY = window.scrollY || window.pageYOffset;
    const viewTop = Math.max(0, scrollY - rootTop);
    const viewBottom = viewTop + window.innerHeight;
    const startRow = Math.max(0, Math.floor(viewTop / rowHeight) - overscan);
    const endRow = Math.min(
      Math.ceil(total / cols) - 1,
      Math.ceil(viewBottom / rowHeight) + overscan
    );
    return { startRow, endRow };
  }

  function render() {
    measureLayout();
    const { startRow, endRow } = visibleRange();
    const startIndex = startRow * cols;
    const endIndex = Math.min(total - 1, (endRow + 1) * cols - 1);
    ensureRange(startIndex, endIndex);

    const parts = [];
    for (let i = startIndex; i <= endIndex; i += 1) {
      const item = cache.get(i);
      if (item) parts.push(cardHtml(item, i));
      else {
        parts.push(
          `<article class="lang-lib-card lang-lib-card-skel" data-index="${i}" aria-hidden="true"><div class="lang-lib-skel"></div></article>`
        );
      }
    }
    windowEl.style.transform = `translateY(${startRow * rowHeight}px)`;
    windowEl.style.gridTemplateColumns = `repeat(${cols}, minmax(0, 1fr))`;
    windowEl.innerHTML = parts.join("");
  }

  function scheduleRender() {
    if (raf) return;
    raf = requestAnimationFrame(() => {
      raf = 0;
      render();
    });
  }

  // bootstrap first chunk
  try {
    const boot = document.getElementById("lang-virt-bootstrap");
    if (boot) storeChunk(0, JSON.parse(boot.textContent || "[]"));
  } catch (_) {}

  measureLayout();
  render();
  // second pass after images/layout settle
  requestAnimationFrame(() => {
    measureLayout();
    render();
  });

  window.addEventListener("scroll", scheduleRender, { passive: true });
  window.addEventListener("resize", scheduleRender);
})();
