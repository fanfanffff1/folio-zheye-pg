/* FOLIO 地图巡礼 — delete actions (list / detail / editor). */
(function () {
  "use strict";
  var csrfHost = document.querySelector("[data-csrf]");
  var csrf = (csrfHost && csrfHost.getAttribute("data-csrf")) || "";

  document.addEventListener("click", function (ev) {
    var btn = ev.target.closest && ev.target.closest("[data-tour-delete]");
    if (!btn) return;
    ev.preventDefault();
    ev.stopPropagation();
    var slug = btn.getAttribute("data-tour-delete");
    var title = btn.getAttribute("data-tour-title") || "";
    var msg = title ? ("确定删除巡礼《" + title + "》吗？此操作不可恢复。") : "确定删除这张巡礼地图吗？此操作不可恢复。";
    if (!window.confirm(msg)) return;
    btn.disabled = true;
    fetch("/api/tours/" + slug + "/delete", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
      body: JSON.stringify({ csrf: csrf })
    }).then(function (r) {
      if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || ("HTTP " + r.status)); });
      return r.json();
    }).then(function () {
      var tile = btn.closest("[data-tour-tile]");
      if (tile && tile.parentNode) { tile.parentNode.removeChild(tile); return; }
      window.location.href = "/tours";
    }).catch(function (e) {
      btn.disabled = false;
      window.alert("删除失败：" + e.message);
    });
  });
})();
