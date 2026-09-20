/* FOLIO 地图巡礼 — editor.
 * Region colour is auto. Optional custom tags add a coloured ring. Each stop
 * can link a book and carry multiple photos (R2). Stops connect as a route. */
(function () {
  "use strict";
  var dataEl = document.getElementById("tour-data");
  var mapEl = document.getElementById("tour-map");
  if (!dataEl || !mapEl || !window.FolioTour) return;

  var tour = JSON.parse(dataEl.textContent || "{}");
  var csrfMeta = document.querySelector('meta[name="csrf"]');
  var csrfHost = document.querySelector("[data-csrf]");
  var csrf = (csrfHost && csrfHost.getAttribute("data-csrf")) || (csrfMeta && csrfMeta.content) || "";
  var FT = window.FolioTour;
  var catById = FT.categoryMap(tour.categories);
  var stops = (tour.stops || []).slice();
  var map, gaz = [], markers = {}, routeLine = null;
  var statusEl = document.getElementById("tour-status");
  var LEVEL_LABEL = { country: "国家", region: "地区", city: "城市" };

  function setStatus(msg, ok) {
    if (!statusEl) return;
    statusEl.textContent = msg || "";
    statusEl.className = "tour-status" + (ok === false ? " is-err" : ok ? " is-ok" : "");
  }
  function debounce(fn, ms) {
    var t; return function () { var a = arguments, self = this; clearTimeout(t); t = setTimeout(function () { fn.apply(self, a); }, ms); };
  }
  function api(url, body) {
    body = Object.assign({ csrf: csrf }, body || {});
    return fetch(url, {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
      body: JSON.stringify(body)
    }).then(function (r) {
      if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || ("HTTP " + r.status)); });
      return r.json();
    });
  }
  function tagOf(s) { return s.tag_id ? catById[s.tag_id] : null; }
  function regionOf(s) { return catById[s.category_id] || null; }
  function photosOf(s) { return (s.photos && s.photos.length) ? s.photos : (s.media_url ? [s.media_url] : []); }

  function refreshMarker(s) {
    if (!markers[s.id]) return;
    var r = regionOf(s), t = tagOf(s);
    markers[s.id].setIcon(FT.pinIcon(r ? r.color : "#9BB3C9", t ? t.color : null, false, s.level));
    markers[s.id].setPopupContent(FT.popupHtml(s, r, t));
  }

  function markerFor(stop) {
    var region = regionOf(stop), tag = tagOf(stop);
    var m = L.marker([stop.lat, stop.lon], {
      icon: FT.pinIcon(region ? region.color : "#9BB3C9", tag ? tag.color : null, false, stop.level),
      riseOnHover: true
    });
    m.bindPopup(FT.popupHtml(stop, region, tag));
    m.addTo(map);
    markers[stop.id] = m;
    return m;
  }
  function drawRoute() {
    if (routeLine) { map.removeLayer(routeLine); routeLine = null; }
    routeLine = FT.routeLayer(stops);
    if (routeLine) routeLine.addTo(map);
  }
  function drawStops() {
    Object.keys(markers).forEach(function (k) { map.removeLayer(markers[k]); });
    markers = {};
    stops.forEach(markerFor);
    drawRoute();
    renderStopList();
  }
  function snapKm(z) {
    if (z <= 3) return 400; if (z === 4) return 200; if (z === 5) return 120;
    if (z === 6) return 80; if (z === 7) return 50; return 35;
  }
  function defaultTagId() {
    var sel = document.getElementById("tour-default-tag");
    return sel && sel.value ? parseInt(sel.value, 10) : null;
  }
  function addStop(city) {
    if (!city) return;
    return api("/api/tours/" + tour.slug + "/stops", {
      lat: city.lat, lon: city.lon,
      place_name: city.name || "", city: city.level === "city" ? (city.name || "") : "",
      admin1: city.admin1 || "", country: city.country || "",
      level: city.level || "city", tag_id: defaultTagId()
    }).then(function (res) {
      stops.push(res.stop); markerFor(res.stop); drawRoute(); renderStopList();
      setStatus("已标记：" + (city.name || "地点") + "（地域自动分类）", true);
    }).catch(function (e) { setStatus(e.message, false); });
  }
  function uploadPhoto(sid, file) {
    var fd = new FormData();
    fd.append("file", file); fd.append("csrf", csrf);
    return fetch("/api/tours/" + tour.slug + "/stops/" + sid + "/photo", {
      method: "POST", credentials: "same-origin", body: fd
    }).then(function (r) {
      if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || ("HTTP " + r.status)); });
      return r.json();
    });
  }

  function renderStopList() {
    var list = document.getElementById("tour-stops");
    if (!list) return;
    list.innerHTML = "";
    document.getElementById("tour-count").textContent = stops.length;
    var customCats = (tour.categories || []).filter(function (c) { return c.kind === "custom"; });
    stops.forEach(function (s, i) {
      var region = regionOf(s), tag = tagOf(s);
      var li = document.createElement("li");
      li.className = "tour-stop";
      var thumbs = photosOf(s).map(function (u) {
        return '<span class="tour-photo-thumb"><img src="' + FT.escapeHtml(u) + '" alt="" />' +
          '<button type="button" class="tour-photo-del" data-url="' + FT.escapeHtml(u) + '" title="删除照片">×</button></span>';
      }).join("");
      li.innerHTML =
        '<div class="tour-stop-head"><span class="tour-stop-idx">' + (i + 1) + "</span>" +
        '<input class="tour-stop-name" value="' + FT.escapeHtml(s.place_name || s.city || "") + '" />' +
        '<button class="tour-stop-del" title="删除">×</button></div>' +
        '<div class="tour-stop-row">' +
        '<span class="tour-stop-region" style="--pin:' + (region ? region.color : "#ccc") + '">' +
        (region ? FT.escapeHtml(region.label) : "地域") + "</span>" +
        '<select class="tour-stop-tag"><option value="">无标签</option></select>' +
        '<input class="tour-stop-period" placeholder="时间（可选）" value="' + FT.escapeHtml(s.period || "") + '" /></div>' +
        '<textarea class="tour-stop-note" placeholder="写点什么…">' + FT.escapeHtml(s.note || "") + "</textarea>" +
        '<div class="tour-stop-book"><input class="tour-stop-book-q" placeholder="关联书籍（可选）" value="' + FT.escapeHtml(s.book_title || "") + '" autocomplete="off" />' +
        '<div class="tour-stop-book-results" hidden></div></div>' +
        '<div class="tour-stop-photos">' + thumbs +
        '<label class="tour-photo-btn">+ 照片<input type="file" accept="image/*" multiple hidden /></label></div>';
      var tagSel = li.querySelector(".tour-stop-tag");
      customCats.forEach(function (c) {
        var o = document.createElement("option");
        o.value = c.id; o.textContent = c.label;
        if (c.id === s.tag_id) o.selected = true;
        tagSel.appendChild(o);
      });
      function save() {
        api("/api/tours/" + tour.slug + "/stops/" + s.id, {
          place_name: li.querySelector(".tour-stop-name").value,
          note: li.querySelector(".tour-stop-note").value,
          period: li.querySelector(".tour-stop-period").value,
          tag_id: tagSel.value ? parseInt(tagSel.value, 10) : 0
        }).then(function () {
          s.place_name = li.querySelector(".tour-stop-name").value;
          s.note = li.querySelector(".tour-stop-note").value;
          s.period = li.querySelector(".tour-stop-period").value;
          s.tag_id = tagSel.value ? parseInt(tagSel.value, 10) : null;
          refreshMarker(s);
          setStatus("已保存", true);
        }).catch(function (e) { setStatus(e.message, false); });
      }
      tagSel.addEventListener("change", save);
      li.querySelector(".tour-stop-name").addEventListener("change", save);
      li.querySelector(".tour-stop-note").addEventListener("blur", save);
      li.querySelector(".tour-stop-period").addEventListener("change", save);
      li.querySelector(".tour-stop-del").addEventListener("click", function () {
        api("/api/tours/" + tour.slug + "/stops/" + s.id + "/delete", {}).then(function () {
          stops = stops.filter(function (x) { return x.id !== s.id; });
          if (markers[s.id]) { map.removeLayer(markers[s.id]); delete markers[s.id]; }
          drawRoute(); renderStopList(); setStatus("已删除", true);
        }).catch(function (e) { setStatus(e.message, false); });
      });
      // book link
      var bookInput = li.querySelector(".tour-stop-book-q");
      var bookBox = li.querySelector(".tour-stop-book-results");
      bookInput.addEventListener("input", debounce(function () {
        var q = bookInput.value.trim();
        if (!q) { bookBox.hidden = true; return; }
        fetch("/api/tours/search?q=" + encodeURIComponent(q), { credentials: "same-origin" })
          .then(function (r) { return r.json(); })
          .then(function (d) {
            bookBox.innerHTML = "";
            (d.books || []).forEach(function (b) {
              var el = document.createElement("button");
              el.type = "button";
              el.textContent = b.chinese || b.title;
              el.addEventListener("click", function () {
                s.book_id = b.id; s.book_title = b.chinese || b.title;
                bookInput.value = s.book_title; bookBox.hidden = true;
                api("/api/tours/" + tour.slug + "/stops/" + s.id, { book_id: b.id })
                  .then(function () { refreshMarker(s); setStatus("已关联《" + s.book_title + "》", true); })
                  .catch(function (e) { setStatus(e.message, false); });
              });
              bookBox.appendChild(el);
            });
            bookBox.hidden = bookBox.children.length === 0;
          }).catch(function () {});
      }, 250));
      bookInput.addEventListener("change", function () {
        if (!bookInput.value.trim() && s.book_id) {
          s.book_id = null; s.book_title = "";
          api("/api/tours/" + tour.slug + "/stops/" + s.id, { book_id: 0 })
            .then(function () { refreshMarker(s); setStatus("已取消关联", true); }).catch(function () {});
        }
      });
      // photos
      li.querySelector('.tour-stop-photos input[type="file"]').addEventListener("change", function (ev) {
        var files = Array.prototype.slice.call(ev.target.files || []);
        if (!files.length) return;
        setStatus("上传中…");
        var seq = Promise.resolve();
        files.forEach(function (file) {
          seq = seq.then(function () {
            return uploadPhoto(s.id, file).then(function (res) {
              s.photos = (s.photos || []).concat([res.media_url]);
              if (!s.media_url) s.media_url = res.media_url;
            }).catch(function (e) { setStatus(e.message, false); });
          });
        });
        seq.then(function () { renderStopList(); refreshMarker(s); setStatus("照片已上传", true); });
      });
      Array.prototype.forEach.call(li.querySelectorAll(".tour-photo-del"), function (btn) {
        btn.addEventListener("click", function () {
          var url = btn.getAttribute("data-url");
          api("/api/tours/" + tour.slug + "/stops/" + s.id + "/photos/delete", { url: url })
            .then(function (res) {
              s.photos = res.photos; s.media_url = s.photos[0] || "";
              renderStopList(); refreshMarker(s); setStatus("已删除照片", true);
            }).catch(function (e) { setStatus(e.message, false); });
        });
      });
      list.appendChild(li);
    });
  }

  function renderCats() {
    var autoBox = document.getElementById("tour-auto-cats");
    var customBox = document.getElementById("tour-custom-cats");
    var sel = document.getElementById("tour-default-tag");
    if (autoBox) {
      autoBox.innerHTML = "";
      (tour.categories || []).filter(function (c) { return c.kind !== "custom"; }).forEach(function (c) {
        var el = document.createElement("span");
        el.className = "tour-cat-chip is-auto";
        el.innerHTML = '<i style="background:' + c.color + '"></i>' + FT.escapeHtml(c.label);
        autoBox.appendChild(el);
      });
    }
    if (customBox) {
      customBox.innerHTML = "";
      (tour.categories || []).filter(function (c) { return c.kind === "custom"; }).forEach(function (c) {
        var el = document.createElement("span");
        el.className = "tour-cat-chip";
        el.innerHTML = '<i style="background:' + c.color + '"></i>' + FT.escapeHtml(c.label);
        customBox.appendChild(el);
      });
    }
    if (sel) {
      sel.innerHTML = '<option value="">无标签</option>';
      (tour.categories || []).filter(function (c) { return c.kind === "custom"; }).forEach(function (c) {
        var o = document.createElement("option");
        o.value = c.id; o.textContent = c.label;
        sel.appendChild(o);
      });
    }
  }

  function bindSearch() {
    var input = document.getElementById("tour-search");
    var box = document.getElementById("tour-search-results");
    var levelSel = document.getElementById("tour-level-filter");
    if (!input || !box) return;
    function run() {
      var q = input.value, level = levelSel ? levelSel.value : "";
      box.innerHTML = "";
      if (q.trim().length < 1) { box.hidden = true; return; }
      FT.search(gaz, q, 20, level).forEach(function (city) {
        var li = document.createElement("li");
        li.innerHTML = '<span class="tour-result-level is-' + (city.level || "city") + '">' +
          (LEVEL_LABEL[city.level] || "") + "</span>" +
          '<span class="tour-result-name">' + FT.escapeHtml(city.name || "") + "</span>" +
          '<span class="tour-result-meta">' + FT.escapeHtml([city.admin1, city.country].filter(Boolean).join(" · ")) + "</span>";
        li.addEventListener("click", function () {
          var z = city.level === "country" ? 4 : city.level === "region" ? 6 : Math.max(map.getZoom(), 7);
          map.setView([city.lat, city.lon], z);
          addStop(city);
          input.value = ""; box.hidden = true;
        });
        box.appendChild(li);
      });
      box.hidden = box.children.length === 0;
    }
    input.addEventListener("input", run);
    if (levelSel) levelSel.addEventListener("change", run);
  }

  function bindMeta() {
    var saveBtn = document.getElementById("tour-save");
    if (saveBtn) saveBtn.addEventListener("click", function () {
      var c = map.getCenter();
      api("/api/tours/" + tour.slug + "/meta", {
        title: document.getElementById("tour-title").value,
        description: document.getElementById("tour-desc").value,
        visibility: document.getElementById("tour-visibility").value,
        center_lat: c.lat, center_lon: c.lng, zoom: map.getZoom()
      }).then(function () { setStatus("已保存", true); }).catch(function (e) { setStatus(e.message, false); });
    });
    var pub = document.getElementById("tour-publish");
    if (pub) pub.addEventListener("click", function () {
      api("/api/tours/" + tour.slug + "/publish", {}).then(function (res) {
        setStatus("已发布", true); window.location.href = "/tours/" + res.slug;
      }).catch(function (e) { setStatus(e.message, false); });
    });
    var addCat = document.getElementById("tour-add-cat");
    if (addCat) addCat.addEventListener("click", function () {
      var label = (document.getElementById("tour-new-cat").value || "").trim();
      var color = document.getElementById("tour-new-cat-color").value || "#9BB3C9";
      if (!label) return;
      api("/api/tours/" + tour.slug + "/categories", { label: label, color: color }).then(function (res) {
        tour.categories.push(res.category);
        catById[res.category.id] = res.category;
        document.getElementById("tour-new-cat").value = "";
        renderCats(); renderStopList(); setStatus("已添加标签", true);
      }).catch(function (e) { setStatus(e.message, false); });
    });
  }

  (async function init() {
    map = await FT.baseMap(mapEl, tour.scope, tour.center ? { lat: tour.center.lat, lon: tour.center.lon, zoom: tour.zoom } : null);
    window.__tourMap = map;
    gaz = await FT.gazetteer(tour.scope);
    renderCats(); drawStops(); bindSearch(); bindMeta();
    map.on("click", function (e) {
      var hit = FT.nearest(gaz, e.latlng.lat, e.latlng.lng, snapKm(map.getZoom()));
      if (!hit) { setStatus("附近没有可标记的城市，请放大后再点。", false); return; }
      addStop(hit);
    });
  })();
})();
