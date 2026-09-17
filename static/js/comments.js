(function () {
  const stars = document.querySelector("[data-stars]");
  const form = document.getElementById("comment-form");
  const list = document.getElementById("comment-list");
  const status = document.getElementById("comment-status");
  if (!stars) return;
  const slug = stars.getAttribute("data-slug");
  function csrfToken() {
    const fromPage = stars.getAttribute("data-csrf");
    if (fromPage) return fromPage;
    const m = document.cookie.match(/(?:^|; )folio_csrf=([^;]*)/);
    return m ? decodeURIComponent(m[1]) : "";
  }
  let sort = "popular";
  let posting = false;
  const draftKey = "folio-draft-" + slug;
  const content = form ? form.querySelector("[name=content]") : null;
  const nick = form ? form.querySelector("[name=nickname]") : null;
  const count = document.querySelector("[data-count]");
  const submit = document.getElementById("comment-submit");

  async function jsonFetch(url, opts) {
    const res = await fetch(url, opts);
    const data = await res.json().catch(() => ({}));
    const msg = Array.isArray(data.detail)
      ? (data.detail[0] && (data.detail[0].msg || data.detail[0]))
      : data.detail;
    if (!res.ok) throw new Error(msg || data.message || "请求失败");
    return data;
  }

  function renderSummary(s) {
    const el = document.getElementById("rating-summary");
    if (!s.count) {
      el.innerHTML = "<p class='empty'>还没有人评分，来做第一位读者吧。</p>";
    } else {
      el.innerHTML = "<p class='score-num'>" + s.average + "</p><p class='score-sub'>基于 " + s.count + " 条评价</p>";
    }
    stars.querySelectorAll("button").forEach((btn) => {
      const n = Number(btn.getAttribute("data-score"));
      btn.textContent = s.mine && s.mine >= n ? "★" : "☆";
    });
    const dist = document.getElementById("rating-dist");
    dist.innerHTML = [5, 4, 3, 2, 1]
      .map((n) => {
        const c = (s.distribution && (s.distribution[n] || s.distribution[String(n)])) || 0;
        const pct = s.count ? Math.round((c / s.count) * 100) : 0;
        return "<li><span>" + n + "星</span><i style='--pct:" + pct + "%'></i><em>" + pct + "%</em></li>";
      })
      .join("");
  }

  let hoverScore = 0;
  stars.addEventListener("mouseover", (e) => {
    const btn = e.target.closest("button[data-score]");
    if (!btn) return;
    hoverScore = Number(btn.getAttribute("data-score"));
    stars.querySelectorAll("button").forEach((b) => {
      b.textContent = Number(b.getAttribute("data-score")) <= hoverScore ? "★" : "☆";
    });
  });
  stars.addEventListener("mouseleave", () => {
    hoverScore = 0;
    const mine = Number(stars.getAttribute("data-mine") || 0);
    stars.querySelectorAll("button").forEach((b) => {
      b.textContent = mine && Number(b.getAttribute("data-score")) <= mine ? "★" : "☆";
    });
  });
  stars.addEventListener("click", async (e) => {
    const btn = e.target.closest("button[data-score]");
    if (!btn) return;
    status.textContent = "正在提交评分…";
    try {
      const s = await jsonFetch(`/api/books/${slug}/ratings`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ score: Number(btn.dataset.score), csrf: csrfToken() }),
      });
      stars.setAttribute("data-mine", s.mine || btn.dataset.score);
      renderSummary(s);
      status.textContent = "评分已更新。";
    } catch (err) {
      status.textContent = err.message + "，请重试。";
    }
  });

  function bodyHtml(c) {
    if (!c.containsSpoiler) return `<p class="body">${escapeHtml(c.content)}</p>`;
    return `<p class="body spoiler" data-spoiler>包含剧透，点击查看</p><p class="body spoiler-src" hidden>${escapeHtml(c.content)}</p>`;
  }

  function avatarHtml(c) {
    const name = c.nickname || "访客";
    if (c.avatarUrl) {
      return `<img class="avatar avatar-sm" src="${escapeHtml(c.avatarUrl)}" alt="" width="36" height="36" />`;
    }
    return `<span class="avatar-fallback" aria-hidden="true">${escapeHtml(name.slice(0, 1))}</span>`;
  }

  function commentHtml(c, isReply) {
    const replies = c.replies || [];
    const shown = replies.slice(0, 2).map((r) => commentHtml(r, true)).join("");
    const extra = replies.length > 2
      ? `<button type="button" data-more="${c.id}">展开更多回复（${replies.length - 2}）</button>
         <div hidden data-more-box>${replies.slice(2).map((r) => commentHtml(r, true)).join("")}</div>`
      : "";
    return `<article class="comment ${isReply ? "replies" : ""}" data-id="${c.id}">
      <div class="comment-head">
        ${avatarHtml(c)}
        <p><strong>${escapeHtml(c.nickname)}</strong> · <time>${c.createdAt.slice(0, 16).replace("T", " ")}</time>${c.status === "pending" ? " · 待审核" : ""}</p>
      </div>
      ${bodyHtml(c)}
      <p>
        <button type="button" data-like="${c.id}" aria-pressed="${c.liked}">赞 ${c.likeCount}</button>
        ${isReply ? "" : `<button type="button" data-reply="${c.id}">回复</button>`}
        ${c.mine ? `<button type="button" data-edit="${c.id}">编辑</button><button type="button" data-del="${c.id}">删除</button>` : `<button type="button" data-report="${c.id}">举报</button>`}
      </p>
      ${shown}${extra}
    </article>`;
  }

  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function updateComposer() {
    const n = (content && content.value || "").trim().length;
    if (count) count.textContent = n + " / 500";
    if (submit) submit.disabled = n < 5 || n > 500;
    if (content && nick) {
      try { localStorage.setItem(draftKey, JSON.stringify({ nick: nick.value, content: content.value })); } catch (e) {}
    }
  }
  if (content) {
    try {
      const draft = JSON.parse(localStorage.getItem(draftKey) || "null");
      if (draft) {
        if (nick && draft.nick) nick.value = draft.nick;
        if (draft.content) content.value = draft.content;
      }
    } catch (e) {}
    content.addEventListener("input", updateComposer);
    if (nick) nick.addEventListener("input", updateComposer);
    updateComposer();
  }

  let offset = 0;
  let hasMore = false;

  async function loadComments(append) {
    if (!append) {
      offset = 0;
      list.innerHTML = "<p class='empty'>评论加载中…</p>";
    }
    try {
      const data = await jsonFetch(`/api/books/${slug}/comments?sort=${sort}&offset=${offset}`);
      hasMore = data.hasMore;
      offset = (data.offset || 0) + (data.comments || []).length;
      const html = data.comments.length
        ? data.comments.map((c) => commentHtml(c, false)).join("")
        : append ? "" : "<p class='empty'>还没有评论。来做第一位读者吧。</p>";
      if (append) list.insertAdjacentHTML("beforeend", html);
      else list.innerHTML = html;
    } catch (e) {
      if (!append) list.innerHTML = "<p class='empty'>评论加载失败，请刷新重试。</p>";
      status.textContent = e.message;
    }
    let more = document.getElementById("load-more");
    if (!more) {
      more = document.createElement("button");
      more.id = "load-more";
      more.type = "button";
      more.textContent = "加载更多";
      list.after(more);
      more.addEventListener("click", () => loadComments(true).catch((err) => (status.textContent = err.message)));
    }
    more.hidden = !hasMore;
    more.textContent = hasMore ? "加载更多" : "没有更多了";
    if (!hasMore && offset === 0) more.hidden = true;
  }

  document.querySelectorAll("[data-sort]").forEach((btn) => {
    btn.addEventListener("click", () => {
      sort = btn.getAttribute("data-sort");
      document.querySelectorAll("[data-sort]").forEach((b) => b.setAttribute("aria-pressed", b === btn ? "true" : "false"));
      loadComments().catch((e) => (status.textContent = e.message));
    });
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (posting) return;
    posting = true;
    if (submit) submit.disabled = true;
    status.textContent = "正在发布…";
    const fd = new FormData(form);
    try {
      const data = await jsonFetch(`/api/books/${slug}/comments`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          nickname: fd.get("nickname"),
          content: fd.get("content"),
          csrf: csrfToken(),
          spoiler: fd.get("spoiler") === "1",
          parent_id: fd.get("parent_id") ? Number(fd.get("parent_id")) : null,
        }),
      });
      form.reset();
      const hidden = form.querySelector("[name=parent_id]");
      if (hidden) hidden.remove();
      try { localStorage.removeItem(draftKey); } catch (err) {}
      updateComposer();
      status.textContent = data.message || (data.status === "pending" ? "已提交，等待复核。" : "评论已发布。");
      await loadComments();
    } catch (err) {
      status.textContent = err.message;
    } finally {
      posting = false;
      updateComposer();
    }
  });

  list.addEventListener("click", async (e) => {
    const spoiler = e.target.closest("[data-spoiler]");
    if (spoiler) {
      const src = spoiler.parentNode.querySelector(".spoiler-src");
      spoiler.hidden = true;
      if (src) { src.hidden = false; src.classList.add("is-open"); }
      return;
    }
    const more = e.target.closest("[data-more]");
    if (more) {
      const box = more.parentNode.querySelector("[data-more-box]");
      if (box) box.hidden = false;
      more.hidden = true;
      return;
    }
    const like = e.target.closest("[data-like]");
    const reply = e.target.closest("[data-reply]");
    const del = e.target.closest("[data-del]");
    const edit = e.target.closest("[data-edit]");
    const report = e.target.closest("[data-report]");
    try {
      if (like) {
        const data = await jsonFetch(`/api/comments/${like.getAttribute("data-like")}/like`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ csrf: csrfToken() }),
        });
        like.textContent = `赞 ${data.likeCount}`;
        like.setAttribute("aria-pressed", data.liked);
      }
      if (reply) {
        let hidden = form.querySelector("[name=parent_id]");
        if (!hidden) {
          hidden = document.createElement("input");
          hidden.type = "hidden";
          hidden.name = "parent_id";
          form.appendChild(hidden);
        }
        hidden.value = reply.getAttribute("data-reply");
        status.textContent = "正在回复该评论。";
        form.querySelector("[name=content]").focus();
      }
      if (del) {
        if (!window.confirm("确定删除这条评论？")) return;
        await jsonFetch(`/api/comments/${del.getAttribute("data-del")}/delete`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ csrf: csrfToken() }),
        });
        await loadComments();
      }
      if (edit) {
        const next = prompt("修改评论");
        if (next) {
          await jsonFetch(`/api/comments/${edit.getAttribute("data-edit")}/edit`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ csrf: csrfToken(), content: next }),
          });
          await loadComments();
        }
      }
      if (report) {
        await jsonFetch(`/api/comments/${report.getAttribute("data-report")}/report`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ csrf: csrfToken(), reason: "读者举报" }),
        });
        status.textContent = "已提交举报，进入审核。";
      }
    } catch (err) {
      status.textContent = err.message;
    }
  });

  loadComments().catch((e) => (status.textContent = e.message));
})();
