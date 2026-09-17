(function () {
  const header = document.querySelector("[data-header]");
  if (header) {
    const onScroll = function () {
      header.classList.toggle("is-scrolled", window.scrollY > 10);
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
  }

  const rail = document.querySelector("[data-lang-scroller]");
  const next = document.querySelector("[data-lang-next]");
  if (rail && next) {
    const update = function () {
      const overflow = rail.scrollWidth - rail.clientWidth > 8;
      next.hidden = !overflow;
      next.disabled = rail.scrollLeft + rail.clientWidth >= rail.scrollWidth - 8;
    };
    next.addEventListener("click", function () {
      rail.scrollBy({ left: Math.min(rail.clientWidth * 0.72, 320), behavior: "smooth" });
    });
    rail.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update);
    update();
  }

  const suggestForm = document.querySelector("[data-suggest]");
  if (suggestForm) {
    const input = suggestForm.querySelector("input[name=q]");
    const box = suggestForm.querySelector("[data-suggest-list]");
    let timer = 0;
    const hide = function () { if (box) box.hidden = true; };
    const esc = function (s) {
      return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;");
    };
    const render = function (items) {
      if (!box) return;
      if (!items.length) {
        box.innerHTML = "<li class='empty' style='padding:8px'>没有符合条件的书</li>";
        box.hidden = false;
        return;
      }
      box.innerHTML = items.map(function (item) {
        return "<li><a href='/books/" + esc(item.slug) + "'><img src='" + esc(item.cover) + "' alt='' width='28' height='42'><span>" +
          esc(item.title) + (item.chinese ? "<br><small>" + esc(item.chinese) + "</small>" : "") + "</span></a></li>";
      }).join("");
      box.hidden = false;
    };
    if (input && box) {
      input.addEventListener("input", function () {
        clearTimeout(timer);
        const q = input.value.trim();
        if (!q) { hide(); return; }
        timer = setTimeout(function () {
          fetch("/api/search/suggest?q=" + encodeURIComponent(q))
            .then(function (r) { return r.json(); })
            .then(function (data) { render(data.results || []); })
            .catch(hide);
        }, 180);
      });
      document.addEventListener("click", function (e) {
        if (!suggestForm.contains(e.target)) hide();
      });
    }
  }

  const lightbox = document.querySelector("[data-lightbox]");
  const openBtn = document.querySelector("[data-lightbox-open]");
  const closeBtnLb = document.querySelector("[data-lightbox-close]");
  if (lightbox && openBtn && lightbox.showModal) {
    openBtn.addEventListener("click", function () {
      lightbox.showModal();
      if (closeBtnLb) closeBtnLb.focus();
    });
    if (closeBtnLb) closeBtnLb.addEventListener("click", function () { lightbox.close(); });
    lightbox.addEventListener("click", function (e) {
      if (e.target === lightbox) lightbox.close();
    });
    lightbox.addEventListener("close", function () { openBtn.focus(); });
  }

  const prev = document.querySelector("[data-prev]");
  const nextBook = document.querySelector("[data-next]");
  if (prev || nextBook) {
    document.addEventListener("keydown", function (e) {
      const tag = (e.target && e.target.tagName) || "";
      if (tag === "INPUT" || tag === "TEXTAREA" || e.target.isContentEditable) return;
      if (e.key === "ArrowLeft" && prev) window.location.href = prev.href;
      if (e.key === "ArrowRight" && nextBook) window.location.href = nextBook.href;
    });
  }

  const article = document.querySelector("[data-article]");
  const dot = document.querySelector("[data-progress-dot]");
  const bar = document.querySelector("[data-read-bar]");
  const back = document.querySelector("[data-back-top]");
  const onRead = function () {
    if (article) {
      const start = article.getBoundingClientRect().top + window.scrollY - 90;
      const span = Math.max(article.offsetHeight - window.innerHeight * 0.45, 1);
      const p = Math.min(1, Math.max(0, (window.scrollY - start) / span));
      if (dot) dot.style.top = (p * 100) + "%";
      if (bar) {
        const mobile = window.matchMedia("(max-width: 767px)").matches;
        bar.hidden = !mobile;
        bar.style.transform = "scaleX(" + p + ")";
      }
    }
    if (back) back.hidden = window.scrollY < 420 || window.innerWidth > 767;
  };
  window.addEventListener("scroll", onRead, { passive: true });
  window.addEventListener("resize", onRead);
  onRead();
  if (back) back.addEventListener("click", function () { window.scrollTo({ top: 0, behavior: "smooth" }); });

  const btn = document.querySelector("[data-menu]");
  const nav = document.querySelector("[data-nav]");
  if (!btn || !nav) return;

  const closeBtn = document.querySelector("[data-menu-close]");
  const close = function () {
    const wasOpen = nav.classList.contains("open");
    nav.classList.remove("open");
    btn.setAttribute("aria-expanded", "false");
    document.body.classList.remove("nav-open");
    if (wasOpen && window.matchMedia("(max-width: 767px)").matches) btn.focus();
  };
  const open = function () {
    nav.classList.add("open");
    btn.setAttribute("aria-expanded", "true");
    document.body.classList.add("nav-open");
    if (closeBtn) closeBtn.focus();
    else {
      const first = nav.querySelector("a");
      if (first) first.focus();
    }
  };
  btn.addEventListener("click", function () {
    if (nav.classList.contains("open")) close();
    else open();
  });
  if (closeBtn) closeBtn.addEventListener("click", close);
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && nav.classList.contains("open")) close();
  });
  nav.querySelectorAll("a").forEach(function (link) {
    link.addEventListener("click", function () {
      if (nav.classList.contains("open")) close();
    });
  });
})();
