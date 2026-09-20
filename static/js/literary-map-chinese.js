(function () {
  const dataEl = document.getElementById("clm-regions-data");
  if (!dataEl) return;
  let regions = [];
  try {
    regions = JSON.parse(dataEl.textContent || "[]");
  } catch (e) {
    regions = [];
  }
  const byId = Object.create(null);
  regions.forEach(function (r) {
    byId[r.id] = r;
  });

  const stage = document.querySelector("[data-clm-stage]");
  const preview = document.querySelector("[data-clm-preview]");
  const drawer = document.querySelector("[data-clm-drawer]");
  const viewport = document.querySelector("[data-clm-viewport]");
  const transformEl = document.querySelector("[data-clm-transform]");
  const controls = document.querySelector("[data-clm-controls]");
  const regionNodes = Array.prototype.slice.call(document.querySelectorAll(".clm-region[data-region]"));

  let activeId = null;
  let leaveTimer = null;
  let filterId = "all";

  function isMobile() {
    return window.matchMedia("(max-width: 767px)").matches;
  }
  function isTablet() {
    return window.matchMedia("(min-width: 768px) and (max-width: 1023px)").matches;
  }

  function fillPanel(root, region) {
    if (!root || !region) return;
    root.querySelectorAll("[data-clm-name]").forEach(function (el) {
      el.textContent = region.name;
    });
    root.querySelectorAll("[data-clm-brief]").forEach(function (el) {
      el.textContent = region.brief || "";
    });
    root.querySelectorAll("[data-clm-keywords]").forEach(function (el) {
      el.innerHTML = "";
      (region.keywords || []).forEach(function (k) {
        const li = document.createElement("li");
        li.textContent = k;
        el.appendChild(li);
      });
    });
    root.querySelectorAll("[data-clm-writers]").forEach(function (el) {
      el.textContent = (region.writers || []).join("、");
    });
    root.querySelectorAll("[data-clm-books]").forEach(function (el) {
      el.innerHTML = "";
      (region.starter_books || []).forEach(function (b) {
        const li = document.createElement("li");
        li.textContent = b.author ? "《" + b.title + "》· " + b.author : "《" + b.title + "》";
        el.appendChild(li);
      });
    });
    root.querySelectorAll("[data-clm-cta]").forEach(function (el) {
      el.setAttribute("href", region.detail_path || "#");
    });
  }

  function positionPreview(node) {
    if (!preview) return;
    if (isMobile() || isTablet()) {
      preview.style.left = "";
      preview.style.top = "";
      preview.style.right = "";
      return;
    }
    if (!stage || !node) return;
    const stageRect = stage.getBoundingClientRect();
    const rect = node.getBoundingClientRect();
    const pw = preview.offsetWidth || 300;
    const ph = preview.offsetHeight || 380;
    const gap = 18;
    let left = rect.right - stageRect.left + gap;
    if (left + pw > stageRect.width - 8) {
      left = rect.left - stageRect.left - pw - gap;
    }
    left = Math.max(8, Math.min(left, stageRect.width - pw - 8));
    let top = rect.top - stageRect.top + rect.height / 2 - ph / 2;
    top = Math.max(8, Math.min(top, Math.max(8, stageRect.height - ph - 8)));
    preview.style.left = left + "px";
    preview.style.top = top + "px";
    preview.style.right = "auto";
  }

  function setActive(id, opts) {
    opts = opts || {};
    activeId = id;
    regionNodes.forEach(function (node) {
      node.classList.toggle("is-active", node.getAttribute("data-region") === id);
    });
    const region = byId[id];
    if (!region) return;

    if (isMobile()) {
      fillPanel(drawer, region);
      drawer.hidden = false;
      document.body.style.overflow = "hidden";
    } else {
      fillPanel(preview, region);
      preview.hidden = false;
      if (drawer) drawer.hidden = true;
      document.body.style.overflow = "";
      const node = regionNodes.find(function (n) {
        return n.getAttribute("data-region") === id;
      });
      requestAnimationFrame(function () {
        positionPreview(node);
      });
    }
    if (opts.focusCta) {
      const cta = (isMobile() ? drawer : preview).querySelector("[data-clm-cta]");
      if (cta) cta.focus();
    }
  }

  function clearActive() {
    activeId = null;
    regionNodes.forEach(function (node) {
      node.classList.remove("is-active");
    });
    if (preview) preview.hidden = true;
    if (drawer) drawer.hidden = true;
    document.body.style.overflow = "";
  }

  function applyFilter(id) {
    filterId = id || "all";
    document.querySelectorAll("[data-clm-filter]").forEach(function (btn) {
      btn.classList.toggle("is-active", btn.getAttribute("data-clm-filter") === filterId);
    });
    regionNodes.forEach(function (node) {
      const f = node.getAttribute("data-filter");
      const match = filterId === "all" || f === filterId;
      node.classList.toggle("is-dimmed", !match);
      node.setAttribute("tabindex", match ? "0" : "-1");
      node.setAttribute("aria-hidden", match ? "false" : "true");
    });
    if (activeId && byId[activeId] && filterId !== "all" && byId[activeId].filter !== filterId) {
      clearActive();
    }
  }

  regionNodes.forEach(function (node) {
    const id = node.getAttribute("data-region");
    node.addEventListener("mouseenter", function () {
      if (isMobile()) return;
      if (leaveTimer) {
        clearTimeout(leaveTimer);
        leaveTimer = null;
      }
      setActive(id);
    });
    node.addEventListener("mouseleave", function () {
      if (isMobile()) return;
      leaveTimer = setTimeout(function () {
        // keep preview on tablet/desktop until another selection or Esc
      }, 200);
    });
    node.addEventListener("click", function (ev) {
      ev.preventDefault();
      setActive(id);
      if (!isMobile() && !isTablet()) {
        // desktop click → detail
        const region = byId[id];
        if (region && region.detail_path) {
          window.location.href = region.detail_path;
        }
      }
    });
    node.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter" || ev.key === " ") {
        ev.preventDefault();
        setActive(id, { focusCta: true });
        if (!isMobile() && !isTablet()) {
          const region = byId[id];
          if (region && region.detail_path) window.location.href = region.detail_path;
        }
      } else if (ev.key === "Escape") {
        clearActive();
      }
    });
  });

  document.querySelectorAll("[data-clm-filter]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      applyFilter(btn.getAttribute("data-clm-filter"));
    });
  });

  document.querySelectorAll("[data-clm-list]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      const id = btn.getAttribute("data-clm-list");
      const region = byId[id];
      if (region) {
        applyFilter(region.filter);
        setActive(id, { focusCta: true });
        const svgNode = document.getElementById("region-" + id);
        if (svgNode && svgNode.scrollIntoView) {
          svgNode.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "smooth" });
        }
      }
    });
  });

  document.querySelectorAll("[data-clm-close]").forEach(function (el) {
    el.addEventListener("click", function () {
      clearActive();
    });
  });

  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape") clearActive();
  });

  // Keep preview open when pointer moves onto it (desktop/tablet)
  if (preview) {
    preview.addEventListener("mouseenter", function () {
      if (leaveTimer) {
        clearTimeout(leaveTimer);
        leaveTimer = null;
      }
    });
  }

  // Mobile pinch-zoom / pan
  let scale = 1;
  let tx = 0;
  let ty = 0;
  function applyTransform() {
    if (!transformEl) return;
    transformEl.style.transform = "translate(" + tx + "px," + ty + "px) scale(" + scale + ")";
  }
  function setScale(next) {
    scale = Math.min(3.2, Math.max(1, next));
    if (scale === 1) {
      tx = 0;
      ty = 0;
    }
    applyTransform();
  }

  if (controls) {
    const zin = controls.querySelector("[data-clm-zoom-in]");
    const zout = controls.querySelector("[data-clm-zoom-out]");
    const zreset = controls.querySelector("[data-clm-zoom-reset]");
    if (zin) zin.addEventListener("click", function () { setScale(scale + 0.25); });
    if (zout) zout.addEventListener("click", function () { setScale(scale - 0.25); });
    if (zreset) zreset.addEventListener("click", function () { setScale(1); });
  }

  if (viewport && transformEl) {
    let pointers = new Map();
    let lastDist = 0;
    let panning = false;
    let startX = 0;
    let startY = 0;
    let originTx = 0;
    let originTy = 0;

    viewport.addEventListener("pointerdown", function (ev) {
      if (!isMobile()) return;
      viewport.setPointerCapture(ev.pointerId);
      pointers.set(ev.pointerId, { x: ev.clientX, y: ev.clientY });
      if (pointers.size === 1) {
        panning = true;
        startX = ev.clientX;
        startY = ev.clientY;
        originTx = tx;
        originTy = ty;
      } else if (pointers.size === 2) {
        panning = false;
        const pts = Array.from(pointers.values());
        lastDist = Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y);
      }
    });
    viewport.addEventListener("pointermove", function (ev) {
      if (!isMobile() || !pointers.has(ev.pointerId)) return;
      pointers.set(ev.pointerId, { x: ev.clientX, y: ev.clientY });
      if (pointers.size === 2) {
        const pts = Array.from(pointers.values());
        const dist = Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y);
        if (lastDist > 0) {
          setScale(scale * (dist / lastDist));
        }
        lastDist = dist;
      } else if (panning && scale > 1) {
        tx = originTx + (ev.clientX - startX);
        ty = originTy + (ev.clientY - startY);
        applyTransform();
      }
    });
    function endPointer(ev) {
      pointers.delete(ev.pointerId);
      if (pointers.size < 2) lastDist = 0;
      if (pointers.size === 0) panning = false;
    }
    viewport.addEventListener("pointerup", endPointer);
    viewport.addEventListener("pointercancel", endPointer);
  }

  function syncControls() {
    if (!controls) return;
    controls.hidden = true;
    controls.style.display = "none";
  }
  window.addEventListener("resize", function () {
    syncControls();
    if (!isMobile() && drawer && !drawer.hidden) {
      drawer.hidden = true;
      document.body.style.overflow = "";
      if (activeId) {
        fillPanel(preview, byId[activeId]);
        preview.hidden = false;
        const node = regionNodes.find(function (n) {
          return n.getAttribute("data-region") === activeId;
        });
        positionPreview(node);
      }
    } else if (activeId && preview && !preview.hidden && !isMobile() && !isTablet()) {
      const node = regionNodes.find(function (n) {
        return n.getAttribute("data-region") === activeId;
      });
      positionPreview(node);
    }
  });

  applyFilter("all");
  syncControls();
})();
