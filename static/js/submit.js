(function () {
  const form = document.getElementById("submit-form");
  if (!form) return;
  const csrf = form.querySelector("[name=csrf]").value;
  const idInput = document.getElementById("sub-id");
  const fileInput = document.getElementById("cover-file");
  const preview = document.getElementById("cover-preview");
  const placeholder = form.querySelector(".cover-placeholder");
  const drop = document.getElementById("cover-drop");
  const intro = document.getElementById("introduction");
  const count = document.getElementById("intro-count");
  const hint = document.getElementById("intro-hint");
  const submitBtn = document.getElementById("submit-btn");
  const statusBox = document.getElementById("form-status");
  const coverStatus = document.getElementById("cover-status");
  const draftKey = "folio-submit-draft";
  let uploading = false;
  let saveTimer = 0;

  function introLen(text) {
    const m = (text || "").match(/[\u4e00-\u9fff\u3400-\u4dbf。，、；：？！“”‘’（）《》【】—…]/g);
    return m ? m.length : 0;
  }

  function hasCover() {
    return Boolean(preview.getAttribute("src")) && !preview.hidden;
  }

  function payload() {
    const fd = new FormData(form);
    const genres = [];
    form.querySelectorAll("[name=genres]:checked").forEach(function (el) { genres.push(el.value); });
    const tags = String(fd.get("tags") || "").split(/[,，、]/).map(function (t) { return t.trim(); }).filter(Boolean).slice(0, 5);
    return {
      id: idInput.value ? Number(idInput.value) : null,
      csrf: csrf,
      title: String(fd.get("title") || "").trim(),
      authors: String(fd.get("authors") || "").trim(),
      introduction: String(fd.get("introduction") || "").trim(),
      originalTitle: fd.get("originalTitle"),
      chineseTitle: fd.get("chineseTitle"),
      chineseTitleIsTemporary: form.querySelector("[name=chineseTitleIsTemporary]").checked,
      recommendationReason: fd.get("recommendationReason"),
      suitableReaders: fd.get("suitableReaders"),
      authorBiography: fd.get("authorBiography"),
      publicationYear: fd.get("publicationYear"),
      publicationDate: fd.get("publicationDate"),
      publisher: fd.get("publisher"),
      isbn: fd.get("isbn"),
      language: fd.get("language"),
      languageOther: fd.get("languageOther"),
      region: fd.get("region"),
      genres: genres,
      tags: tags,
      informationSource: fd.get("informationSource"),
      confirmTruth: form.querySelector("[name=confirmTruth]").checked,
      confirmReview: form.querySelector("[name=confirmReview]").checked,
    };
  }

  function ready() {
    const p = payload();
    const okIntro = introLen(p.introduction) >= 50;
    return p.title.length >= 2 && p.authors.length >= 2 && okIntro && hasCover() && p.confirmTruth && p.confirmReview && !uploading;
  }

  function refresh() {
    const n = introLen(intro.value);
    count.textContent = n + " / 50";
    count.style.color = n >= 50 ? "#3F8A68" : "";
    hint.textContent = n >= 50 ? "字数已经达到要求。" : "请尽量用自己的语言介绍，不要直接复制出版方简介。";
    submitBtn.disabled = !ready();
    try { localStorage.setItem(draftKey, JSON.stringify(payload())); } catch (e) {}
  }

  function showCover(url) {
    preview.src = url;
    preview.hidden = false;
    if (placeholder) placeholder.hidden = true;
  }

  async function uploadFile(file) {
    if (!file) return;
    if (!/image\/(jpeg|png|webp)/.test(file.type) && !/\.(jpe?g|png|webp)$/i.test(file.name)) {
      coverStatus.textContent = "仅支持 JPG、PNG 或 WebP。";
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      coverStatus.textContent = "封面请小于 10MB。";
      return;
    }
    uploading = true;
    coverStatus.textContent = "正在上传封面…";
    refresh();
    const body = new FormData();
    body.append("file", file);
    body.append("csrf", csrf);
    if (idInput.value) body.append("id", idInput.value);
    try {
      const res = await fetch("/api/submissions/cover", { method: "POST", body: body });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "上传失败");
      idInput.value = data.id;
      showCover(data.coverUrl);
      coverStatus.textContent = "封面已上传。";
    } catch (err) {
      coverStatus.textContent = err.message;
    } finally {
      uploading = false;
      refresh();
    }
  }

  fileInput.addEventListener("change", function () { uploadFile(fileInput.files[0]); });
  drop.addEventListener("dragover", function (e) { e.preventDefault(); drop.classList.add("is-over"); });
  drop.addEventListener("dragleave", function () { drop.classList.remove("is-over"); });
  drop.addEventListener("drop", function (e) {
    e.preventDefault();
    drop.classList.remove("is-over");
    uploadFile(e.dataTransfer.files[0]);
  });
  document.getElementById("cover-replace").addEventListener("click", function () { fileInput.click(); });
  document.getElementById("cover-remove").addEventListener("click", function () {
    preview.removeAttribute("src");
    preview.hidden = true;
    if (placeholder) placeholder.hidden = false;
    refresh();
  });

  intro.addEventListener("input", refresh);
  form.addEventListener("input", refresh);
  form.addEventListener("change", refresh);

  const lang = document.getElementById("language");
  const other = document.getElementById("lang-other-wrap");
  if (lang && other) {
    lang.addEventListener("change", function () { other.hidden = lang.value !== "other"; });
  }

  let dupTimer = 0;
  document.getElementById("title").addEventListener("input", function () {
    clearTimeout(dupTimer);
    const q = this.value.trim();
    dupTimer = setTimeout(async function () {
      if (q.length < 2) return;
      const isbn = form.querySelector("[name=isbn]").value;
      const res = await fetch("/api/submissions/duplicates?q=" + encodeURIComponent(q) + "&isbn=" + encodeURIComponent(isbn));
      const data = await res.json();
      const box = document.getElementById("dup-box");
      if (!data.results || !data.results.length) { box.hidden = true; return; }
      box.hidden = false;
      box.innerHTML = "<p>站内可能已有相近的书，仍可继续投稿：</p>" + data.results.map(function (b) {
        return "<a href='/books/" + b.slug + "'>" + b.title + (b.chinese ? " / " + b.chinese : "") + "</a>";
      }).join("<br>");
    }, 280);
  });

  async function saveDraft(silent) {
    statusBox.textContent = "正在保存草稿…";
    const res = await fetch("/api/submissions/draft", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload()),
    });
    const data = await res.json().catch(function () { return {}; });
    if (!res.ok) {
      statusBox.textContent = (data.detail && (data.detail[0] && data.detail[0].msg || data.detail)) || "草稿保存失败";
      return;
    }
    idInput.value = data.id;
    statusBox.textContent = silent ? "草稿已自动保存。" : "草稿已保存。";
  }
  document.getElementById("save-draft").addEventListener("click", function () { saveDraft(false); });
  form.addEventListener("input", function () {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(function () { saveDraft(true); }, 4000);
  });

  document.getElementById("preview-btn").addEventListener("click", function () {
    const p = payload();
    const dlg = document.getElementById("preview-dialog");
    const body = document.getElementById("preview-body");
    body.innerHTML = [
      hasCover() ? "<img src='" + preview.src + "' alt='封面预览' style='width:160px;height:auto'>" : "",
      p.title ? "<h2>" + p.title + "</h2>" : "",
      p.authors ? "<p>" + p.authors + "</p>" : "",
      p.language ? "<p>" + p.language + "</p>" : "",
      p.genres.length ? "<p>" + p.genres.join(" / ") + "</p>" : "",
      p.publisher || p.publicationYear ? "<p>" + (p.publisher || "") + " " + (p.publicationYear || "") + "</p>" : "",
      p.introduction ? "<p>" + p.introduction.replace(/</g, "&lt;") + "</p>" : "",
      p.recommendationReason ? "<p>" + p.recommendationReason.replace(/</g, "&lt;") + "</p>" : "",
      p.suitableReaders ? "<p>" + p.suitableReaders.replace(/</g, "&lt;") + "</p>" : "",
    ].join("");
    if (dlg.showModal) dlg.showModal();
  });

  form.addEventListener("submit", async function (e) {
    e.preventDefault();
    if (!ready()) {
      statusBox.textContent = "请完成必填项并勾选确认。";
      const first = form.querySelector(":invalid");
      if (first) first.focus();
      return;
    }
    submitBtn.disabled = true;
    statusBox.textContent = "正在提交审核…";
    try {
      const res = await fetch("/api/submissions/submit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload()),
      });
      const data = await res.json().catch(function () { return {}; });
      if (!res.ok) throw new Error((Array.isArray(data.detail) ? data.detail[0].msg : data.detail) || "提交失败");
      try { localStorage.removeItem(draftKey); } catch (err) {}
      window.location.href = data.redirect;
    } catch (err) {
      statusBox.textContent = err.message;
      submitBtn.disabled = false;
    }
  });

  try {
    const saved = JSON.parse(localStorage.getItem(draftKey) || "null");
    if (saved && !idInput.value) {
      ["title", "authors", "introduction", "originalTitle", "chineseTitle", "publisher", "isbn"].forEach(function (name) {
        const el = form.querySelector("[name=" + name + "]");
        if (el && saved[name] && !el.value) el.value = saved[name];
      });
    }
  } catch (e) {}
  refresh();
})();
