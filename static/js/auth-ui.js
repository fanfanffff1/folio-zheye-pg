(function () {
  function csrfToken() {
    const m = document.cookie.match(/(?:^|; )folio_csrf=([^;]*)/);
    return m ? decodeURIComponent(m[1]) : "";
  }
  const gate = document.getElementById("login-gate");
  function nextPath() {
    return location.pathname + location.search;
  }
  function openGate(kind) {
    if (!gate) {
      location.href = "/login?next=" + encodeURIComponent(nextPath());
      return;
    }
    const title = gate.querySelector("[data-gate-title]");
    const copy = gate.querySelector("[data-gate-copy]");
    const link = gate.querySelector("[data-gate-login]");
    if (kind === "recommend") {
      title.textContent = "登录后推荐图书";
      copy.textContent = "暂时不登录也可以继续浏览和参与评论，但推荐图书与收藏功能需要登录。";
    } else {
      title.textContent = "请先登录";
      copy.textContent = "登录后可以把这本书放进“我的喜欢”。";
    }
    if (link) link.href = "/login?next=" + encodeURIComponent(nextPath());
    if (typeof gate.showModal === "function") gate.showModal();
  }
  document.querySelectorAll("[data-pw-toggle]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const input = btn.closest("label, .pw-wrap, form").querySelector("[data-password], input[type=password], input[name=password]");
      if (!input) return;
      const show = input.type === "password";
      input.type = show ? "text" : "password";
      btn.textContent = show ? "隐藏" : "显示";
    });
  });
  document.addEventListener("click", async (e) => {
    const fav = e.target.closest("[data-fav]");
    if (fav) {
      e.preventDefault();
      e.stopPropagation();
      if (fav.getAttribute("data-authed") !== "1") {
        openGate("favorite");
        return;
      }
      const res = await fetch("/api/books/" + fav.getAttribute("data-fav") + "/favorite", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ csrf: csrfToken() }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.status === 401) {
        openGate("favorite");
        return;
      }
      fav.classList.toggle("is-on", !!data.favorited);
      fav.setAttribute("aria-pressed", data.favorited ? "true" : "false");
      fav.setAttribute("aria-label", data.favorited ? "取消喜欢" : "喜欢这本书");
      const wrap = fav.closest(".fav-block");
      if (wrap && data.likeCount != null) {
        const count = wrap.querySelector("[data-fav-count]");
        if (count) count.textContent = data.likeCount;
      }
    }
  });
  const guestLine = document.querySelector("[data-guest-line]");
  if (guestLine) {
    fetch("/api/guest/identity")
      .then((r) => r.json())
      .then((d) => {
        if (d.displayName) {
          const meta = guestLine.querySelector(".person-meta");
          const fall = guestLine.querySelector(".avatar-fallback");
          if (meta) {
            const small = meta.querySelector("small");
            meta.innerHTML = (small ? small.outerHTML : "") + d.displayName;
          } else {
            guestLine.textContent = "你将以“" + d.displayName + "”发表评论";
          }
          if (fall) fall.textContent = d.displayName.slice(0, 1);
        }
      })
      .catch(() => {});
  }
  const profile = document.querySelector("[data-profile]");
  if (profile) {
    profile.addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData(profile);
      const status = document.querySelector("[data-profile-status]");
      const res = await fetch("/api/account/profile", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          csrf: fd.get("csrf"),
          nickname: fd.get("nickname"),
          old_password: fd.get("old_password"),
          password: fd.get("password"),
          confirm: fd.get("confirm"),
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (status) status.textContent = res.ok ? "已保存。" : (data.detail || "保存失败");
    });
  }
})();
