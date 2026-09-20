/* FOLIO 地图巡礼 — one big map.
 * Shared collections (per author/book); everyone contributes points into the
 * same collection. Search + create/mark both live in the left panel. */
(function () {
  "use strict";
  var dataEl = document.getElementById("globe-data");
  var mapEl = document.getElementById("tour-globe-map");
  if (!dataEl || !mapEl || !window.FolioTour) return;

  var boot = JSON.parse(dataEl.textContent || "{}");
  var FT = window.FolioTour;
  var csrfHost = document.querySelector("[data-csrf]");
  var csrf = (csrfHost && csrfHost.getAttribute("data-csrf")) || "";

  var map, gaz = null;
  var collections = [], points = [], places = [], mine = [], drafts = [], published = [];
  var listMode = "all";
  var browseCollapsed = true;     // browse list hidden until search focus / mode pick
  var addPlaceMode = false;       // "add specific place" form open: map click sets coords
  var addPlaceMarker = null;      // glowing marker at the picked coordinate

  function setPickMarker(lat, lon) {
    if (!map) return;
    if (addPlaceMarker) {
      addPlaceMarker.setLatLng([lat, lon]);
    } else {
      addPlaceMarker = L.marker([lat, lon], {
        interactive: false, zIndexOffset: 1000,
        icon: L.divIcon({ className: "tg-pick-marker", iconSize: [18, 18], iconAnchor: [9, 9] })
      }).addTo(map);
    }
  }
  function clearPickMarker() {
    if (addPlaceMarker && map) map.removeLayer(addPlaceMarker);
    addPlaceMarker = null;
  }
  var trashItems = [], openStopId = null;
  var placeByKey = {}, placeByName = {};
  function pkey(level, lat, lon) { return (level || "city") + "|" + (Math.round(lat * 100) / 100) + "|" + (Math.round(lon * 100) / 100); }
  var catById = {};               // collectionSlug -> {catId: cat}
  var active = null;              // active pack_tour
  var detailPushed = false;       // true only when detail opened via in-page click
  var currentDetailKey = null;    // "kind:key" of the detail currently shown
  var previewingDetail = false;   // true when the shown detail is a hover preview
  var pinnedDetail = null;        // {kind, key} saved by clicking a link
  var pinnedData = null;          // last pinned detail payload (for the peek tab)
  var currentDetailData = null;   // payload currently rendered
  var detailCache = {};           // kind:key -> fetched payload (hover preview speedup)
  var marking = false;
  var hiddenRegion = {}, hiddenTag = {};
  var autoFollowCollection = localStorage.getItem("folio_af_collection") === "1";
  var autoFollowStop = localStorage.getItem("folio_af_stop") === "1";
  var layer, routeLine = null, markers = {};

  function catOf(slug, id) { var m = catById[slug]; return m ? m[id] : null; }
  function regionLabel(p) { var c = catOf(p.tour, p.category_id); return c ? c.label : ""; }
  function tagLabel(p) { var c = catOf(p.tour, p.tag_id); return c ? c.label : ""; }
  function colorOf(p) { var c = catOf(p.tour, p.category_id); return c ? c.color : "#9BB3C9"; }
  function tagColorOf(p) { var c = catOf(p.tour, p.tag_id); return c ? c.color : null; }
  function pass(p) { return !hiddenRegion[regionLabel(p)] && !hiddenTag[tagLabel(p)]; }
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
  function debounce(fn, ms) { var t; return function () { var a = arguments, self = this; clearTimeout(t); t = setTimeout(function () { fn.apply(self, a); }, ms); }; }
  function setHint(msg, ok) {
    var el = document.getElementById("tg-active-hint");
    if (!el) return;
    el.textContent = msg || "点击地图上的城市即可添加标记。";
    el.className = "tg-hint" + (ok === false ? " is-err" : "");
  }

  function popupHtml(p) {
    var cat = catOf(p.tour, p.category_id), tag = catOf(p.tour, p.tag_id);
    var b = ['<div class="tour-pop">'];
    b.push("<h4>" + FT.escapeHtml(p.place_name || p.city || "地点") + "</h4>");
    var meta = [p.city, p.country].filter(Boolean).join(" · ");
    if (meta) b.push('<p class="tour-pop-meta">' + FT.escapeHtml(meta) + "</p>");
    if (cat) b.push('<p class="tour-pop-cat"><i style="background:' + cat.color + '"></i>' + FT.escapeHtml(cat.label) + "</p>");
    if (tag) b.push('<p class="tour-pop-cat"><i style="background:' + tag.color + '"></i>' + FT.escapeHtml(tag.label) + "</p>");
    if (p.media_url) b.push('<img class="tour-pop-img" src="' + FT.escapeHtml(p.media_url) + '" alt="" loading="lazy" />');
    if (p.note) b.push('<p class="tour-pop-note">' + FT.escapeHtml(p.note) + "</p>");
    b.push('<p class="tour-pop-subject">合集：' + FT.escapeHtml(p.title) + "</p>");
    b.push("</div>");
    return b.join("");
  }
  // show the popup on hover (no click), hide when the cursor leaves
  function hoverPopup(mk) {
    var t = null;
    function cancel() { if (t) { clearTimeout(t); t = null; } }
    mk.on("mouseover", function () { cancel(); mk.openPopup(); });
    mk.on("mouseout", function () { cancel(); t = setTimeout(function () { mk.closePopup(); }, 180); });
    mk.on("popupopen", function (e) {
      var el = e.popup.getElement();
      if (!el) return;
      L.DomEvent.on(el, "mouseenter", cancel);
      L.DomEvent.on(el, "mouseleave", function () { mk.closePopup(); });
    });
  }
  function addMarker(p) {
    var mk = L.marker([p.lat, p.lon], { icon: FT.pinIcon(colorOf(p), tagColorOf(p), false, p.level), riseOnHover: true });
    mk.bindPopup(popupHtml(p));
    hoverPopup(mk);
    mk.addTo(layer);
    markers[p.id] = mk;
  }
  function drawClusters(vis) {
    var cell = 360 / Math.pow(2, map.getZoom() + 2), grid = {};
    vis.forEach(function (p) {
      var k = Math.floor((p.lon + 180) / cell) + "," + Math.floor((p.lat + 90) / cell);
      (grid[k] = grid[k] || []).push(p);
    });
    Object.keys(grid).forEach(function (k) {
      var arr = grid[k];
      if (arr.length === 1) { addMarker(arr[0]); return; }
      var lat = arr.reduce(function (a, x) { return a + x.lat; }, 0) / arr.length;
      var lon = arr.reduce(function (a, x) { return a + x.lon; }, 0) / arr.length;
      var mk = L.marker([lat, lon], { icon: L.divIcon({ className: "tour-cluster", html: "<span>" + arr.length + "</span>", iconSize: [34, 34], iconAnchor: [17, 17] }) });
      mk.on("click", function () { map.setView([lat, lon], Math.min(map.getZoom() + 2, map.getMaxZoom())); });
      mk.addTo(layer);
    });
  }
  // ---- aggregate: ranked, density-aware, labelled places -------------------
  function placeScore(p) { return (p.like_count || 0) * 3 + (p.view_count || 0) + (p.stop_count || 0); }
  function placeColor(p) { return p.level === "country" ? "#8FA9C9" : p.level === "region" ? "#9BBE9A" : "#D2A06E"; }
  function maxPlaces(z) {
    if (z <= 2) return 12; if (z === 3) return 18; if (z === 4) return 26; if (z === 5) return 45;
    if (z === 6) return 75; if (z === 7) return 130; return 220;
  }
  function placeIcon(p) {
    var cls = "tour-place" + (p.level === "spot" ? " is-spot" : "") +
      (p.status === "disputed" ? " is-disputed" : "");
    return L.divIcon({
      className: cls,
      iconSize: null,
      html: '<span class="tour-place-dot" style="--pin:' + placeColor(p) + '"></span>' +
        '<span class="tour-place-name">' + FT.escapeHtml(p.name) + "</span>"
    });
  }
  function placePopup(p) {
    var b = ['<div class="tour-pop tour-place-pop">'];
    b.push("<h4>" + FT.escapeHtml(p.name) + ' <span class="tour-level-badge">' +
      ({ country: "国家", region: "地区", city: "城市", spot: "具体地点" }[p.level] || "") + "</span>" +
      (p.status === "disputed" ? ' <span class="tour-disputed-badge">待核实</span>' : "") + "</h4>");
    var meta = [p.admin1, p.country].filter(Boolean).join(" · ");
    if (meta) b.push('<p class="tour-pop-meta">' + FT.escapeHtml(meta) + "</p>");
    if (p.lat != null && p.lon != null) {
      b.push('<p class="tour-pop-meta">' + (+p.lat).toFixed(4) + ", " + (+p.lon).toFixed(4) + "</p>");
    }
    b.push('<p class="tour-place-stats">被 ' + (p.stop_count || 0) + " 个巡礼标记</p>");
    b.push("</div>");
    return b.join("");
  }
  function bindPlacePopup(p, mk) {
    var el = mk.getPopup().getElement();
    fetch("/api/tours/places/" + p.id + "/view", { method: "POST", credentials: "same-origin" })
      .then(function () { p.view_count = (p.view_count || 0) + 1; }).catch(function () {});
    var likeBtn = el.querySelector(".tp-like");
    if (likeBtn) likeBtn.addEventListener("click", function () {
      api("/api/tours/places/" + p.id + "/like", {}).then(function (res) {
        p.liked = res.liked; p.like_count = res.like_count;
        likeBtn.textContent = res.liked ? "♥ 已收藏" : "♡ 收藏";
        likeBtn.classList.toggle("is-on", res.liked);
      }).catch(function (e) { alert(e.message); });
    });
    var editBtn = el.querySelector(".tp-edit"), box = el.querySelector(".tp-edit-box");
    if (editBtn && box) {
      var ta = box.querySelector("textarea"); ta.value = p.footnote || "";
      editBtn.addEventListener("click", function () { box.hidden = !box.hidden; });
      box.querySelector(".tp-save").addEventListener("click", function () {
        api("/api/tours/places/" + p.id + "/footnote", { footnote: ta.value }).then(function (res) {
          p.footnote = res.footnote;
          el.querySelector(".tour-place-footnote").textContent = p.footnote;
          box.hidden = true;
        }).catch(function (e) { alert(e.message); });
      });
    }
    var photoInput = el.querySelector('.tp-photo input[type="file"]');
    if (photoInput) photoInput.addEventListener("change", function (ev) {
      var file = ev.target.files[0]; if (!file) return;
      var fd = new FormData(); fd.append("file", file); fd.append("csrf", csrf);
      fetch("/api/tours/places/" + p.id + "/photo", { method: "POST", credentials: "same-origin", body: fd })
        .then(function (r) { if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail); }); return r.json(); })
        .then(function (res) { p.photos = res.photos; mk.setPopupContent(placePopup(p)); mk.openPopup(); })
        .catch(function (e) { alert(e.message); });
    });
    var editPlaceBtn = el.querySelector(".tp-edit-place");
    if (editPlaceBtn) editPlaceBtn.addEventListener("click", function () {
      if (window.__folioOpenPlaceForm) window.__folioOpenPlaceForm(p, p.id);
    });
    var reportBtn = el.querySelector(".tp-report");
    if (reportBtn) reportBtn.addEventListener("click", function () {
      var reason = prompt("举报原因（如：重复、错误、无关）：") || "";
      if (reason.trim().length < 3) return;
      api("/api/tours/places/" + p.id + "/report", { reason: reason.trim() })
        .then(function () { reportBtn.textContent = "已举报"; reportBtn.disabled = true; })
        .catch(function (e) { alert(e.message); });
    });
  }
  // ---- place marks: show related tours/entries in the left list ------------
  var marksCache = {}, marksHideTimer = null, marksPinned = null, marksHover = null, marksPid = null;

  function renderPlaceInList(d) {
    var box = document.getElementById("globe-search-list");
    if (!box) return;
    var gq = document.getElementById("globe-q");
    if (gq && marksPinned) gq.value = d.name || "";
    var list = document.getElementById("globe-list"); if (list) list.hidden = true;
    var mine = document.getElementById("globe-mine"); if (mine) mine.hidden = true;
    var no = document.getElementById("globe-noresult"); if (no) no.hidden = true;
    box.innerHTML = "";
    function row(html) { var li = document.createElement("li"); li.innerHTML = html; box.appendChild(li); return li; }
    (d.collections || []).forEach(function (c) {
      var li = row('<span class="tour-result-level is-region">巡礼</span><span class="tour-result-name">' + FT.escapeHtml(c.title) + "</span>");
      li.addEventListener("click", function () { clearPlaceList(); selectCollection(c.slug); });
    });
    (d.stops || []).forEach(function (s) {
      var li = row('<span class="tour-result-level is-city">条目</span><span class="tour-result-name">' +
        FT.escapeHtml(s.map_title) + " › " + FT.escapeHtml(s.place_name) + "</span>");
      li.addEventListener("click", function () { clearPlaceList(); selectCollection(s.map_slug, s.stop_id); });
    });
    box.hidden = box.children.length === 0;
    showSide("tg-browse");
    setBrowseCollapsed(false);
  }

  function reportPlace(pid) {
    if (!pid) return;
    var reason = prompt("上报该地点的问题（如：重复、位置错误、信息有误）：") || "";
    if (reason.trim().length < 3) return;
    api("/api/tours/places/" + pid + "/report", { reason: reason.trim() })
      .then(function () { setHint("已上报，感谢反馈", true); })
      .catch(function (e) { alert(e.message); });
  }

  function showPlaceInList(pid) {
    if (marksHideTimer) { clearTimeout(marksHideTimer); marksHideTimer = null; }
    marksHover = pid; marksPid = pid;
    if (marksCache[pid]) { renderPlaceInList(marksCache[pid]); return; }
    fetch("/api/tours/places/" + pid + "/stops", { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        marksCache[pid] = d;
        if (marksHover === pid || marksPinned === pid) renderPlaceInList(d);
      })
      .catch(function () {});
  }

  function clearPlaceList() {
    marksPinned = null;
    var box = document.getElementById("globe-search-list");
    if (box) { box.hidden = true; box.innerHTML = ""; }
    var gq = document.getElementById("globe-q");
    if (gq) gq.value = "";
    var list = document.getElementById("globe-list"); if (list) list.hidden = false;
    var mine = document.getElementById("globe-mine"); if (mine) mine.hidden = false;
  }

  function revertPlaceList() {
    if (marksPinned) return;
    clearPlaceList();
  }

  // Web Mercator cannot show latitudes below ~-85.05, so polar places are
  // nudged up to the map's southern edge (their real coords stay in the data).
  function dispLat(lat) { return Math.max(lat, -84.8); }
  function dispLatLng(p) { return [dispLat(p.lat), p.lon]; }

  var SPOT_MIN_ZOOM = 9;  // user-added specific places only show when zoomed in
  // Rough continent / ocean label from coordinates (for the "我的地点" list).
  function geoRegion(lat, lon) {
    lat = +lat; lon = +lon;
    if (isNaN(lat) || isNaN(lon)) return "";
    if (lat <= -60) return "南极洲";
    if (lat >= 66.6) return "北冰洋";
    if (lat >= 15 && lon >= -168 && lon <= -52) return "北美洲";
    if (lat >= 7 && lat < 15 && lon >= -92 && lon <= -77) return "北美洲";
    if (lat >= -56 && lat <= 12 && lon >= -82 && lon <= -34) return "南美洲";
    if (lat >= 36 && lon >= -9 && lon <= 40) return "欧洲";
    if (lat >= -35 && lat <= 37 && lon >= -17 && lon <= 51) return "非洲";
    if (lat >= 5 && lon >= 40 && lon <= 180) return "亚洲";
    if (lat >= -50 && lat <= -10 && lon >= 110 && lon <= 180) return "大洋洲";
    if (lat >= -47 && lat <= -34 && lon >= 165) return "大洋洲";
    if (lon >= -70 && lon <= 20) return "大西洋";
    if (lon >= 20 && lon <= 110) return "印度洋";
    return "太平洋";
  }

  function drawPlaces() {
    var z = map.getZoom(), b = map.getBounds();
    var vis = places
      .filter(function (p) {
        if (!b.contains(dispLatLng(p))) return false;
        if (p.level !== "city" && z < SPOT_MIN_ZOOM) return false;
        return true;
      })
      .sort(function (a, c) { return placeScore(c) - placeScore(a); })
      .slice(0, maxPlaces(z));
    vis.forEach(function (p) {
      var mk = L.marker(dispLatLng(p), { icon: placeIcon(p), riseOnHover: true });
      mk.bindPopup(placePopup(p));
      hoverPopup(mk);
      mk.on("mouseover", function () { showPlaceInList(p.id); });
      mk.on("mouseout", function () { marksHover = null; marksHideTimer = setTimeout(revertPlaceList, 300); });
      mk.on("click", function () { marksPinned = p.id; showPlaceInList(p.id); });
      mk.addTo(layer);
    });
    var c = document.getElementById("globe-count");
    if (c) c.textContent = vis.length;
  }

  function draw() {
    if (layer) map.removeLayer(layer);
    if (routeLine) { map.removeLayer(routeLine); routeLine = null; }
    markers = {};
    layer = L.layerGroup().addTo(map);
    if (active) {
      var vis = (active.stops || []).map(function (s) {
        return Object.assign({}, s, { tour: active.slug, title: active.title });
      }).filter(pass);
      vis.forEach(addMarker);
      routeLine = FT.routeLayer(vis);
      if (routeLine) routeLine.addTo(map);
      var c = document.getElementById("globe-count");
      if (c) c.textContent = vis.length;
    } else {
      drawPlaces();
    }
  }

  // ---- left panel: search --------------------------------------------------
  function renderList() {
    var box = document.getElementById("globe-list");
    if (!box) return;
    box.innerHTML = "";
    if (listMode === "trash") {
      var th = document.createElement("p"); th.className = "tour-globe-section"; th.textContent = "回收站（删除的合集，可恢复）";
      box.appendChild(th);
      if (!trashItems.length) { var te = document.createElement("p"); te.className = "empty"; te.textContent = "回收站为空。"; box.appendChild(te); }
      trashItems.forEach(function (t) {
        var el = document.createElement("div");
        el.className = "tour-globe-item";
        el.innerHTML = '<span class="tour-globe-item-title">' + FT.escapeHtml(t.title) + "</span>" +
          '<span class="tour-globe-item-meta">' + t.stop_count + " 个地点 · 已删除</span>" +
          '<span class="tour-globe-item-by"><button type="button" class="tour-restore-btn" data-restore="' + FT.escapeHtml(t.slug) + '">恢复</button></span>';
        el.querySelector("[data-restore]").addEventListener("click", function () {
          api("/api/tours/" + t.slug + "/restore", {}).then(function () {
            trashItems = trashItems.filter(function (x) { return x.slug !== t.slug; });
            renderList(); setHint("已恢复", true);
          }).catch(function (e) { alert(e.message); });
        });
        box.appendChild(el);
      });
      return;
    }
    var h = document.createElement("p");
    h.className = "tour-globe-section";
    h.innerHTML = (listMode === "draft" ? "我的草稿" : listMode === "published" ? "我的发布" : "公开合集") +
      ' · <b id="globe-count">' + points.length + "</b> 个地点";
    box.appendChild(h);
    var src = listMode === "draft" ? drafts : listMode === "published" ? published : collections;
    src.forEach(function (t) {
      var el = document.createElement("div");
      el.className = "tour-globe-item" + (active && active.slug === t.slug ? " is-active" : "");
      var owned = t.is_owner || listMode !== "all";
      el.innerHTML = '<span class="tour-globe-item-title">' + FT.escapeHtml(t.title) + " " +
        FT.kindBadge(t.kind) + "</span>" +
        '<span class="tour-globe-item-meta">' + t.stop_count + " 个地点 · " + t.view_count + " 次浏览</span>" +
        '<span class="tour-globe-item-by">' +
        (t.owner_avatar ? '<img class="tour-by-avatar" src="' + FT.escapeHtml(t.owner_avatar) + '" alt="" />' : '<span class="tour-by-avatar is-empty"></span>') +
        FT.escapeHtml(t.owner_name || "编辑部") + "</span>" +
        (owned ? '<span class="tour-globe-item-menu-wrap"><button type="button" class="tour-globe-item-menu-btn" title="更多">⋯</button>' +
          '<span class="tour-globe-item-menu" hidden><button type="button" class="tour-delete-btn" data-tour-delete="' +
          FT.escapeHtml(t.slug) + '" data-tour-title="' + FT.escapeHtml(t.title) + '">删除</button></span></span>' : "");
      var mb = el.querySelector(".tour-globe-item-menu-btn");
      if (mb) mb.addEventListener("click", function (ev) { ev.stopPropagation(); var m = el.querySelector(".tour-globe-item-menu"); m.hidden = !m.hidden; });
      var delBtn = el.querySelector(".tour-delete-btn");
      if (delBtn) delBtn.addEventListener("click", function (ev) {
        ev.stopPropagation();
        if (!confirm("确定删除巡礼《" + t.title + "》吗？删除后可在回收站恢复。")) return;
        api("/api/tours/" + t.slug + "/delete", {}).then(function () {
          collections = collections.filter(function (x) { return x.slug !== t.slug; });
          published = published.filter(function (x) { return x.slug !== t.slug; });
          drafts = drafts.filter(function (x) { return x.slug !== t.slug; });
          renderList(); setHint("已删除，可在回收站恢复", true);
        }).catch(function (e) { alert(e.message); });
      });
      el.addEventListener("click", function (ev) {
        if (ev.target.closest("[data-tour-delete]") || ev.target.closest(".tour-globe-item-menu-btn") || ev.target.closest(".tour-globe-item-menu")) return;
        selectCollection(t.slug);
      });
      box.appendChild(el);
    });
    if (!collections.length) {
      var e = document.createElement("p"); e.className = "empty"; e.textContent = "还没有公开的巡礼。";
      box.appendChild(e);
    }
  }
  function renderMine() {
    var box = document.getElementById("globe-mine");
    if (!box) return;
    box.innerHTML = "";
    if (!mine.length) return;
    var h = document.createElement("p"); h.className = "tour-globe-section"; h.textContent = "我的未公开巡礼";
    box.appendChild(h);
    mine.forEach(function (t) {
      var el = document.createElement("button");
      el.type = "button";
      el.className = "tour-globe-item is-mine";
      el.innerHTML = '<span class="tour-globe-item-title">' + FT.escapeHtml(t.title) + "</span>" +
        '<span class="tour-globe-item-meta">' + t.stop_count + " 个地点 · 未公开</span>";
      el.addEventListener("click", function () { selectCollection(t.slug); });
      box.appendChild(el);
    });
  }
  function renderFilters() {
    var box = document.getElementById("globe-filters");
    if (!box) return;
    box.innerHTML = "";
    var regions = {}, tags = {};
    collections.forEach(function (t) {
      (t.categories || []).forEach(function (c) {
        if (c.kind === "custom") tags[c.label] = c.color; else regions[c.label] = c.color;
      });
    });
    function chip(label, color, store) {
      var b = document.createElement("button");
      b.type = "button"; b.className = "tour-filter-chip";
      b.innerHTML = '<i style="background:' + color + '"></i>' + FT.escapeHtml(label);
      b.addEventListener("click", function () { store[label] = !store[label]; b.classList.toggle("is-off", store[label]); draw(); });
      box.appendChild(b);
    }
    Object.keys(regions).forEach(function (l) { chip(l, regions[l], hiddenRegion); });
    Object.keys(tags).forEach(function (l) { chip(l, tags[l], hiddenTag); });
  }

  function fitCollection(st) {
    if (!st.length) return;
    // nudge the fitted region slightly down and to the left
    map.fitBounds(
      L.latLngBounds(st.map(function (x) { return [x.lat, x.lon]; })).pad(0.3),
      { maxZoom: 8, paddingTopLeft: [0, 60], paddingBottomRight: [80, 0] }
    );
  }

  var collectionFrom = "tg-browse";  // where the collection view was opened from
  function selectCollection(slug, stopId, from) {
    if (from) collectionFrom = from;
    return fetch("/api/tours/" + encodeURIComponent(slug), { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (t) {
        active = t; marking = true;
        var m = {}; (t.categories || []).forEach(function (c) { m[c.id] = c; }); catById[t.slug] = m;
        ensureGaz();
        openStopId = stopId || null;
        var sideEl0 = document.querySelector(".tour-globe-side");
        if (sideEl0) sideEl0.classList.remove("is-peek-stops");
        renderActive(); draw();
        var st = (t.stops || []).filter(function (x) { return x.lat != null; });
        if (stopId) {
          var el = document.querySelector('#tg-stops .tour-stop[data-stop-id="' + stopId + '"]');
          if (el) el.scrollIntoView({ block: "center" });
          var mk = markers[stopId];
          if (mk) mk.openPopup();
          if (st.length) fitCollection(st);
          return;
        }
        if (autoFollowCollection && st.length) fitCollection(st);
      }).catch(function () {});
  }

  // ---- remember/restore the exact view across book / author pages ---------
  var TOURS_STATE_KEY = "folio:toursState";
  function currentToursState() {
    if (!active) return null;
    return {
      slug: active.slug, stop: openStopId || null, detail: currentDetailKey || null,
      c: [map.getCenter().lat, map.getCenter().lng], z: map.getZoom(), t: Date.now()
    };
  }
  function applyToursState(s) {
    if (!s || !s.slug) return;
    selectCollection(s.slug, s.stop || null).then(function () {
      if (s.c && s.c.length === 2 && s.z != null) {
        setTimeout(function () { map.setView([dispLat(s.c[0]), s.c[1]], s.z, { animate: false }); }, 400);
      }
      if (s.detail) {
        var i = s.detail.indexOf(":");
        if (i > 0) openDetail(s.detail.slice(0, i), s.detail.slice(i + 1), false);
      }
    });
  }
  // stamp the state onto a link's back=/tours param so it survives a new tab too
  function withStateBack(href) {
    var s = currentToursState();
    if (!s) return href;
    var target = "/tours?r=" + encodeURIComponent(JSON.stringify(s));
    var qi = href.indexOf("?");
    var base = qi >= 0 ? href.slice(0, qi) : href;
    var q = qi >= 0 ? href.slice(qi + 1) : "";
    var keep = q.split("&").filter(function (kv) { return kv && kv.indexOf("back=") !== 0; });
    keep.push("back=" + encodeURIComponent(target));
    return base + "?" + keep.join("&");
  }
  function saveToursState() {
    var s = currentToursState();
    if (!s) return;
    try { sessionStorage.setItem(TOURS_STATE_KEY, JSON.stringify(s)); } catch (e) {}
  }
  function restoreToursState() {
    // 1) explicit ?r= state (works across tabs / new windows)
    var qp = new URLSearchParams(location.search);
    var r = qp.get("r");
    if (r) {
      var s = null;
      try { s = JSON.parse(r); } catch (e) {}
      if (s && s.slug) {
        try {
          qp.delete("r");
          var clean = location.pathname + (qp.toString() ? "?" + qp.toString() : "");
          history.replaceState(history.state, "", clean);
        } catch (e) {}
        applyToursState(s);
        return;
      }
    }
    // 2) sessionStorage fallback (same tab)
    var raw = null;
    try { raw = sessionStorage.getItem(TOURS_STATE_KEY); } catch (e) {}
    if (!raw) return;
    try { sessionStorage.removeItem(TOURS_STATE_KEY); } catch (e) {}
    var s2 = null;
    try { s2 = JSON.parse(raw); } catch (e) {}
    if (!s2 || !s2.slug) return;
    var ref = document.referrer || "";
    var fromBook = ref.indexOf("/books/") >= 0 || ref.indexOf("/authors/") >= 0;
    if (!fromBook && !(s2.t && Date.now() - s2.t < 120000)) return;
    applyToursState(s2);
  }

  // ---- left panel: search results (inline) --------------------------------
  function clearSearchResults() {
    var box = document.getElementById("globe-search-list");
    if (box) { box.hidden = true; box.innerHTML = ""; }
    if (isMobileGlobe()) setMobileCollapsed(true);
    var gq = document.getElementById("globe-q");
    if (gq) gq.value = "";
    var list = document.getElementById("globe-list"); if (list) list.hidden = false;
    var mine = document.getElementById("globe-mine"); if (mine) mine.hidden = false;
    var no = document.getElementById("globe-noresult"); if (no) no.hidden = true;
  }

  function renderResults(data) {
    var box = document.getElementById("globe-search-list");
    if (!box) return;
    box.innerHTML = "";
    function row(html) { var li = document.createElement("li"); li.innerHTML = html; box.appendChild(li); return li; }
    (data.tours || []).forEach(function (t) {
      var li = row('<span class="tour-result-level is-region">巡礼</span><span class="tour-result-name">' + FT.escapeHtml(t.title) + "</span>");
      li.addEventListener("click", function () { clearSearchResults(); selectCollection(t.slug); });
    });
    (data.stops || []).forEach(function (s) {
      var li = row('<span class="tour-result-level is-city">条目</span><span class="tour-result-name">' +
        FT.escapeHtml(s.map_title) + " › " + FT.escapeHtml(s.place_name || "") + "</span>" +
        (s.snippet ? '<span class="tour-result-snippet">' + FT.escapeHtml(s.snippet) + "</span>" : ""));
      li.addEventListener("click", function () { clearSearchResults(); selectCollection(s.map_slug, s.stop_id); });
    });
    (data.places || []).forEach(function (p) {
      var li = row('<span class="tour-result-level is-city">地点</span><span class="tour-result-name">' +
        FT.escapeHtml(p.name) + (p.city ? " · " + FT.escapeHtml(p.city) : "") + "</span>" +
        (p.snippet ? '<span class="tour-result-snippet">' + FT.escapeHtml(p.snippet) + "</span>" : ""));
      li.addEventListener("click", function () {
        // make sure the searched place is on the map (and zoomed enough for spots)
        if (p.lat != null && !places.some(function (x) { return x.id === p.id; })) {
          places.push({
            id: p.id, name: p.name, level: p.level || "spot", lat: p.lat, lon: p.lon,
            country: p.country || "", admin1: "", city_key: p.city || "", status: "published",
            stop_count: 0, view_count: 0, like_count: 0
          });
        }
        if (p.lat != null) map.setView([dispLat(p.lat), p.lon], Math.max(map.getZoom(), 9));
        draw();
        showPlaceInList(p.id);
      });
    });
    (data.books || []).forEach(function (b) {
      var li = row('<span class="tour-result-level is-city">书</span><span class="tour-result-name">' + FT.escapeHtml(b.chinese || b.title) + "</span>");
      if (b.linked_tours && b.linked_tours.length) {
        var sub = document.createElement("div"); sub.className = "tour-search-sub";
        b.linked_tours.forEach(function (t) {
          var a = document.createElement("a"); a.href = "javascript:void(0)"; a.textContent = "《" + t.title + "》";
          a.addEventListener("click", function () { clearSearchResults(); selectCollection(t.slug); });
          sub.appendChild(a);
        });
        li.appendChild(sub);
      } else {
        var cta = document.createElement("a"); cta.className = "tour-search-cta"; cta.href = "javascript:void(0)";
        cta.textContent = "创建/加入该书巡礼 →";
        cta.addEventListener("click", function () { clearSearchResults(); createCollection("book", b.id, b.chinese || b.title); });
        li.appendChild(cta);
      }
    });
    (data.authors || []).forEach(function (a) {
      var li = row('<span class="tour-result-level is-region">作者</span><span class="tour-result-name">' + FT.escapeHtml(a.name) + "</span>");
      if (a.linked_tours && a.linked_tours.length) {
        var sub = document.createElement("div"); sub.className = "tour-search-sub";
        a.linked_tours.forEach(function (t) {
          var x = document.createElement("a"); x.href = "javascript:void(0)"; x.textContent = "《" + t.title + "》";
          x.addEventListener("click", function () { clearSearchResults(); selectCollection(t.slug); });
          sub.appendChild(x);
        });
        li.appendChild(sub);
      } else {
        var c2 = document.createElement("a"); c2.className = "tour-search-cta"; c2.href = "javascript:void(0)";
        c2.textContent = "创建/加入该作者巡礼 →";
        c2.addEventListener("click", function () { clearSearchResults(); createCollection("author", a.id, a.name); });
        li.appendChild(c2);
      }
    });
    (data.genres || []).forEach(function (g) {
      var li = row('<span class="tour-result-level is-country">流派</span><span class="tour-result-name">' + FT.escapeHtml(g) + "</span>");
      var cta = document.createElement("a"); cta.className = "tour-search-cta"; cta.href = "javascript:void(0)";
      cta.textContent = "创建流派巡礼 →";
      cta.addEventListener("click", function () { clearSearchResults(); createCollection("genre", null, g + "巡礼"); });
      li.appendChild(cta);
    });
    box.hidden = box.children.length === 0;
    var no = document.getElementById("globe-noresult");
    if (no) no.hidden = box.children.length > 0;
  }
  // City results from the (full) gazetteer, shown under the map-pilgrimage search.
  function renderCityResults(q) {
    var box = document.getElementById("globe-search-list");
    if (!box || !q) return;
    ensureGaz().then(function () {
      var g = gazPlus();
      var lq = q.toLowerCase();
      var hits = (g || []).filter(function (x) {
        if (x.level !== "city") return false;
        var n = ((x.name || "") + " " + (x.nameZh || "") + " " + (x.nameEn || "") + " " + (x.alias || "")).toLowerCase();
        return n.indexOf(lq) >= 0;
      }).slice(0, 8);
      hits.forEach(function (x) {
        var li = document.createElement("li");
        li.innerHTML = '<span class="tour-result-level is-city">城市</span><span class="tour-result-name">' +
          FT.escapeHtml(x.name || x.nameZh || "") + (x.country ? " · " + FT.escapeHtml(x.country) : "") + "</span>" +
          '<span class="tour-result-snippet">' + (+x.lat).toFixed(4) + ", " + (+x.lon).toFixed(4) + "</span>";
        li.addEventListener("click", function () {
          if (active) {
            addPoint({ name: x.name || x.nameZh, lat: x.lat, lon: x.lon, level: "city", admin1: x.admin1 || "", country: x.country || "" });
            clearSearchResults();
          } else {
            map.setView([x.lat, x.lon], Math.max(map.getZoom(), 8));
          }
        });
        box.appendChild(li);
      });
      box.hidden = box.children.length === 0;
    });
  }

  function isMobileGlobe() { return window.matchMedia("(max-width: 900px)").matches; }
  function setMobileCollapsed(collapsed) {
    var sideEl = document.querySelector(".tour-globe-side");
    if (!sideEl) return;
    sideEl.classList.toggle("is-mobile-collapsed", !!collapsed);
    var t = document.getElementById("tg-mobile-toggle");
    if (t) t.classList.toggle("is-open", !collapsed);
  }
  function bindSearch() {
    var input = document.getElementById("globe-q");
    if (!input) return;
    var box = document.getElementById("globe-search-list");
    var timer = null;
    if (isMobileGlobe()) {
      setMobileCollapsed(true);
      var apb = document.getElementById("globe-add-place");
      if (apb) apb.textContent = "＋ 地点";
      var shortLabels = { "globe-all": "全部", "globe-drafts": "草稿", "globe-published": "发布" };
      Object.keys(shortLabels).forEach(function (id) {
        var e = document.getElementById(id);
        if (e) e.textContent = shortLabels[id];
      });
    }
    var mtog = document.getElementById("tg-mobile-toggle");
    if (mtog) mtog.addEventListener("click", function () {
      var sideEl = document.querySelector(".tour-globe-side");
      setMobileCollapsed(!(sideEl && sideEl.classList.contains("is-mobile-collapsed")));
    });
    input.addEventListener("input", function () {
      var q = input.value.trim();
      clearTimeout(timer);
      marksPinned = null; marksHover = null;
      var list = document.getElementById("globe-list");
      var mine = document.getElementById("globe-mine");
      var no = document.getElementById("globe-noresult");
      if (!q) {
        if (box) { box.hidden = true; box.innerHTML = ""; }
        if (list) list.hidden = false;
        if (mine) mine.hidden = false;
        if (no) no.hidden = true;
        return;
      }
      // searching: hide the normal list, show inline results
      if (list) list.hidden = true;
      if (mine) mine.hidden = true;
      if (no) no.hidden = true;
      timer = setTimeout(function () {
        fetch("/api/tours/search?q=" + encodeURIComponent(q), { credentials: "same-origin" })
          .then(function (r) { return r.json(); })
          .then(function (d) { renderResults(d); renderCityResults(q); })
          .catch(function () { renderCityResults(q); });
      }, 220);
    });
    input.addEventListener("focus", function () {
      var sideEl = document.querySelector(".tour-globe-side");
      if (sideEl) sideEl.classList.remove("is-peek", "is-peek-stops");
      if (isMobileGlobe()) setMobileCollapsed(false);
      if (active) return;
      showSide("tg-browse");
      setBrowseCollapsed(false);
      renderList();
    });
    var cn = document.getElementById("globe-create-new");
    if (cn) cn.addEventListener("click", function () {
      showSide("tg-create-sec");
    });
  }

  // ---- my places (list + detail + ⋯ menu) ---------------------------------
  function bindMyPlaces() {
    var openBtn = document.getElementById("globe-my-places");
    if (!openBtn) return;
    var back = document.getElementById("tmp-back");
    var LABEL = { pending: "待审核", published: "已发布", disputed: "待核实", rejected: "已驳回", draft: "草稿" };
    if (isMobileGlobe()) {
      var bc = document.getElementById("tmp-build-collection");
      if (bc) bc.textContent = "建为合集";
    }

    function placeAction(action, p) {
      if (action === "edit") { if (window.__folioOpenPlaceForm) window.__folioOpenPlaceForm(p, p.id); return; }
      if (action === "delete") {
        var isPub = p.status === "published";
        if (!confirm(isPub ? "已发布地点需提交删除审核，确定提交？" : "删除这个地点？")) return;
        api("/api/tours/places/" + p.id + "/delete", {}).then(function (res) {
          setHint(res && res.pending ? "已提交删除审核" : "已删除", true); loadMyPlaces();
        }).catch(function (e) { alert(e.message); });
        return;
      }
      if (action === "publish") {
        api("/api/tours/places/" + p.id + "/update", {
          name: p.name, lat: p.lat, lon: p.lon, city_key: p.city_key || "",
          country: p.country || "", description: p.footnote || "", source_url: p.source_url || "",
          book_ids: (p.books || []).map(function (b) { return b.id; }), draft: false
        }).then(function (res) {
          setHint(res.status === "pending" ? "已提交，等待审核" : "已发布", true); loadMyPlaces();
        }).catch(function (e) { alert(e.message); });
        return;
      }
    }

    function openPlaceDetail(p) {
      window.__folioCurrentPlace = p;
      var t = document.getElementById("tpd-title"); if (t) t.textContent = p.name || "地点";
      var body = document.getElementById("tpd-body");
      if (body) {
        body.innerHTML =
          '<p class="tg-my-place-meta"><span class="tg-status is-' + FT.escapeHtml(p.status) + '">' +
          (LABEL[p.status] || p.status) + "</span>" +
          (LEVEL_LABEL[p.level] ? " · " + LEVEL_LABEL[p.level] : "") +
          (p.lat != null ? " · " + p.lat.toFixed(5) + ", " + p.lon.toFixed(5) : "") + "</p>" +
          ((p.city_key || p.country) ? '<p class="tg-my-place-meta">' + FT.escapeHtml([p.city_key, p.country].filter(Boolean).join(" · ")) + "</p>" : "") +
          ((p.books && p.books.length) ? '<p class="tg-my-place-meta">书：' + p.books.map(function (b) { return FT.escapeHtml(b.title); }).join("、") + "</p>" : "") +
          (p.footnote ? "<p>" + FT.escapeHtml(p.footnote) + "</p>" : "") +
          (p.source_url ? '<p class="tg-my-place-meta"><a href="' + FT.escapeHtml(p.source_url) + '" target="_blank" rel="noopener">来源 ↗</a></p>' : "") +
          ((p.status === "rejected" && p.reject_reason) ? '<p class="tg-my-place-reason">驳回原因：' + FT.escapeHtml(p.reject_reason) + "</p>" : "");
      }
      var menu = document.getElementById("tpd-menu");
      if (menu) {
        var pub = menu.querySelector('[data-act="publish"]');
        if (pub) pub.hidden = p.status !== "draft";
      }
      showSide("tg-place-detail");
      if (p.lat != null) { setPickMarker(p.lat, p.lon); map.setView([dispLat(p.lat), p.lon], Math.max(map.getZoom(), 6)); }
    }

    function render(list) {
      var box = document.getElementById("tmp-list");
      if (!box) return;
      box.innerHTML = "";
      if (!list.length) { box.innerHTML = '<p class="empty">还没有添加过地点。</p>'; return; }
      list.forEach(function (p) {
        var el = document.createElement("div");
        el.className = "tg-my-place";
        el.innerHTML =
          '<div class="tg-my-place-head"><input type="checkbox" class="tg-mp-check" data-pid="' + p.id + '" />' +
          '<strong>' + FT.escapeHtml(p.name) + "</strong>" +
          '<span class="tg-status is-' + FT.escapeHtml(p.status) + '">' + (LABEL[p.status] || p.status) + "</span>" +
          '<span class="tour-stop-menu-wrap"><button type="button" class="tour-stop-menu-btn tg-mp-menu-btn" title="更多">⋯</button>' +
          '<span class="tour-stop-menu" hidden>' +
          '<button type="button" data-act="edit">编辑</button>' +
          (p.status === "draft" ? '<button type="button" data-act="publish">发布</button>' : "") +
          '<button type="button" data-act="delete">删除</button></span></span></div>' +
          (function () {
            var parts = [];
            if (LEVEL_LABEL[p.level]) parts.push(LEVEL_LABEL[p.level]);
            if (p.lat != null && p.lon != null) parts.push((+p.lat).toFixed(4) + ", " + (+p.lon).toFixed(4));
            var region = geoRegion(p.lat, p.lon); if (region) parts.push(region);
            var city = p.city_key && p.city_key.indexOf("|") < 0 ? p.city_key : "";
            if (p.country || city) parts.push([p.country, city].filter(Boolean).join(" · "));
            return '<p class="tg-my-place-meta">' + FT.escapeHtml(parts.join(" · ")) + "</p>";
          })() +
          (p.status === "rejected" && p.reject_reason
            ? '<p class="tg-my-place-reason">驳回原因：' + FT.escapeHtml(p.reject_reason) + "</p>" : "");
        var chk = el.querySelector(".tg-mp-check");
        if (chk) chk.addEventListener("click", function (ev) { ev.stopPropagation(); });
        el.querySelector(".tg-mp-menu-btn").addEventListener("click", function (ev) {
          ev.stopPropagation(); var m = el.querySelector(".tour-stop-menu"); m.hidden = !m.hidden;
        });
        Array.prototype.forEach.call(el.querySelectorAll(".tour-stop-menu [data-act]"), function (b) {
          b.addEventListener("click", function (ev) { ev.stopPropagation(); placeAction(b.getAttribute("data-act"), p); });
        });
        el.addEventListener("click", function () {
          closeDetail();
          if (p.status === "draft") {
            if (window.__folioOpenPlaceForm) window.__folioOpenPlaceForm(p, p.id);
          } else {
            openPlaceDetail(p);
          }
        });
        box.appendChild(el);
      });
    }

    var allPlaces = [];
    function renderFiltered() {
      var el = document.getElementById("tmp-q");
      var q = ((el && el.value) || "").trim().toLowerCase();
      var list = allPlaces;
      if (q) {
        list = allPlaces.filter(function (p) {
          return ((p.name || "") + " " + (p.city_key || "") + " " + (p.country || ""))
            .toLowerCase().indexOf(q) >= 0;
        });
      }
      render(list);
    }
    function loadMyPlaces() {
      showSide("tg-my-places");
      var box = document.getElementById("tmp-list");
      if (box) box.innerHTML = '<p class="empty">加载中…</p>';
      fetch("/api/tours/places/mine", { credentials: "same-origin" })
        .then(function (r) { return r.json(); })
        .then(function (d) { allPlaces = d.places || []; renderFiltered(); })
        .catch(function () { allPlaces = []; renderFiltered(); });
    }
    var tmpQ = document.getElementById("tmp-q");
    if (tmpQ) tmpQ.addEventListener("input", renderFiltered);

    var buildBtn = document.getElementById("tmp-build-collection");
    if (buildBtn) buildBtn.addEventListener("click", function () {
      var ids = Array.prototype.slice.call(document.querySelectorAll(".tg-mp-check:checked"))
        .map(function (c) { return parseInt(c.getAttribute("data-pid"), 10); });
      if (!ids.length) { alert("请先勾选至少一个地点。"); return; }
      var title = prompt("合集名称：") || "";
      if (!title.trim()) return;
      api("/api/tours/collection-from-places", { title: title.trim(), place_ids: ids }).then(function (res) {
        setHint("已创建合集《" + res.title + "》", true);
        if (res.slug) selectCollection(res.slug, null, "tg-my-places");
      }).catch(function (e) { alert(e.message); });
    });
    window.__folioLoadMyPlaces = loadMyPlaces;
    openBtn.addEventListener("click", loadMyPlaces);
    if (back) back.addEventListener("click", function () { clearPickMarker(); showSide("tg-browse"); });

    var tpdBack = document.getElementById("tpd-back");
    if (tpdBack) tpdBack.addEventListener("click", function () { loadMyPlaces(); });
    var tpdMenuBtn = document.getElementById("tpd-menu-btn");
    if (tpdMenuBtn) tpdMenuBtn.addEventListener("click", function () {
      var m = document.getElementById("tpd-menu"); m.hidden = !m.hidden;
    });
    var tpdMenu = document.getElementById("tpd-menu");
    if (tpdMenu) Array.prototype.forEach.call(tpdMenu.querySelectorAll("[data-act]"), function (b) {
      b.addEventListener("click", function () {
        tpdMenu.hidden = true;
        var p = window.__folioCurrentPlace; if (p) placeAction(b.getAttribute("data-act"), p);
      });
    });
  }

  // ---- add a specific place (UGC, needs review) ---------------------------
  var addPlaceState = { lat: null, lon: null, books: [], editId: null };
  function bindAddPlace() {
    var openBtn = document.getElementById("globe-add-place");
    if (!openBtn) return;
    var msg = document.getElementById("tap-msg");
    function setMsg(t) { if (msg) { msg.textContent = t || ""; msg.classList.remove("is-err"); } }
    function reset() {
      addPlaceState = { lat: null, lon: null, books: [], editId: null };
      clearPickMarker();
      ["tap-name", "tap-city", "tap-country", "tap-address", "tap-desc", "tap-source",
        "tap-book-q", "tap-lat", "tap-lon"].forEach(function (id) {
        var e = document.getElementById(id);
        if (e) { e.value = ""; if (e.dataset) delete e.dataset.touched; }
      });
      var mc = document.getElementById("tap-manual-loc");
      if (mc) mc.checked = false;
      var st = document.querySelector('input[name="tap-level"][value="spot"]');
      if (st) st.checked = true;
      addPlaceState.cityRef = null;
      var db2 = document.getElementById("tap-draft"); if (db2) db2.hidden = false;
      var sb = document.getElementById("tap-submit"); if (sb) sb.textContent = "提交";
      var box = document.getElementById("tap-books"); if (box) box.innerHTML = "";
      var br = document.getElementById("tap-book-results"); if (br) { br.innerHTML = ""; br.hidden = true; }
      setMsg("");
    }
    function renderChips() {
      var box = document.getElementById("tap-books"); if (!box) return;
      box.innerHTML = "";
      addPlaceState.books.forEach(function (b) {
        var s = document.createElement("span");
        s.className = "tg-chip";
        s.innerHTML = FT.escapeHtml(b.title) + ' <button type="button" title="移除">×</button>';
        s.querySelector("button").addEventListener("click", function () {
          addPlaceState.books = addPlaceState.books.filter(function (x) { return x.id !== b.id; });
          renderChips();
        });
        box.appendChild(s);
      });
      saveDraftLocal();
    }
    var DRAFT_KEY = "folio_place_draft";
    function fieldVal(id) { var e = document.getElementById(id); return e ? e.value : ""; }
    function setField(id, v) { var e = document.getElementById(id); if (e) e.value = v == null ? "" : v; }
    function clearDraftLocal() { try { localStorage.removeItem(DRAFT_KEY); } catch (e) {} }
    function saveDraftLocal() {
      try {
        var d = {
          name: fieldVal("tap-name"), city: fieldVal("tap-city"), country: fieldVal("tap-country"),
          desc: fieldVal("tap-desc"), source: fieldVal("tap-source"),
          lat: addPlaceState.lat, lon: addPlaceState.lon, books: addPlaceState.books
        };
        var empty = !d.name && !d.city && !d.country && !d.desc && !d.source &&
          d.lat == null && !(d.books || []).length;
        if (empty) { localStorage.removeItem(DRAFT_KEY); return; }
        localStorage.setItem(DRAFT_KEY, JSON.stringify(d));
      } catch (e) {}
    }
    function restoreDraftLocal() {
      try {
        var raw = localStorage.getItem(DRAFT_KEY);
        if (!raw) return false;
        var d = JSON.parse(raw);
        setField("tap-name", d.name); setField("tap-city", d.city); setField("tap-country", d.country);
        setField("tap-desc", d.desc); setField("tap-source", d.source);
        if (d.lat != null && d.lon != null) {
          addPlaceState.lat = d.lat; addPlaceState.lon = d.lon;
          setField("tap-lat", (+d.lat).toFixed(5)); setField("tap-lon", (+d.lon).toFixed(5));
          setPickMarker(d.lat, d.lon);
        }
        addPlaceState.books = d.books || [];
        renderChips();
        return true;
      } catch (e) { return false; }
    }

    function openPlaceForm(place, editId) {
      reset();
      addPlaceState.editId = editId || null;
      if (place) {
        addPlaceState.lat = place.lat; addPlaceState.lon = place.lon;
        var set = function (id, v) { var e = document.getElementById(id); if (e) e.value = v || ""; };
        set("tap-name", place.name); set("tap-city", place.city_key);
        set("tap-address", place.address); set("tap-desc", place.footnote);
        set("tap-source", place.source_url);
        if (place.lat != null) {
          addPlaceState.lat = place.lat; addPlaceState.lon = place.lon;
          setPickMarker(place.lat, place.lon);
          map.setView([dispLat(place.lat), place.lon], Math.max(map.getZoom(), 6));
          var la = document.getElementById("tap-lat"), lo = document.getElementById("tap-lon");
          if (la) la.value = place.lat.toFixed(5);
          if (lo) lo.value = place.lon.toFixed(5);
        }
        var co = document.getElementById("tap-country");
        if (co && place.country) co.value = place.country;
        var rl = document.querySelector('input[name="tap-level"][value="' + (place.level || "spot") + '"]');
        if (rl) rl.checked = true;
        (place.books || []).forEach(function (b) { addPlaceState.books.push({ id: b.id, title: b.title }); });
        renderChips();
      }
      var restored = (!place && restoreDraftLocal());
      // published places can only be re-submitted (no save-as-draft)
      var isPub = place && place.status === "published";
      var dbtn = document.getElementById("tap-draft"); if (dbtn) dbtn.hidden = !!isPub;
      var sbtn = document.getElementById("tap-submit"); if (sbtn) sbtn.textContent = isPub ? "重新提交" : "提交";
      showSide("tg-add-place"); setBrowseCollapsed(false);
      addPlaceMode = true;
      setMsg(editId ? (isPub ? "修改后重新提交（需审核）" : "编辑后提交")
        : (restored ? "已恢复上次未完成的编辑，可继续填写或修改" : "在地图上点一下选择精确位置"));
    }
    window.__folioOpenPlaceForm = openPlaceForm;
    openBtn.addEventListener("click", function () { openPlaceForm(null, null); });
    var back = document.getElementById("tap-back");
    if (back) back.addEventListener("click", function () {
      var fromEdit = !!addPlaceState.editId;
      addPlaceMode = false; clearPickMarker(); clearDraftLocal(); reset();
      if (fromEdit && window.__folioLoadMyPlaces) window.__folioLoadMyPlaces();
      else showSide("tg-browse");
    });
    var bq = document.getElementById("tap-book-q"), br = document.getElementById("tap-book-results");
    if (bq) bq.addEventListener("input", debounce(function () {
      var q = bq.value.trim(); br.innerHTML = "";
      if (!q) { br.hidden = true; return; }
      fetch("/api/tours/search?q=" + encodeURIComponent(q), { credentials: "same-origin" })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          (d.books || []).slice(0, 8).forEach(function (bk) {
            var li = document.createElement("li");
            li.textContent = bk.chinese || bk.title;
            li.addEventListener("click", function () {
              if (!addPlaceState.books.some(function (b) { return b.id === bk.id; })) {
                addPlaceState.books.push({ id: bk.id, title: bk.chinese || bk.title });
                renderChips();
              }
              br.hidden = true; bq.value = "";
            });
            br.appendChild(li);
          });
          br.hidden = br.children.length === 0;
        }).catch(function () {});
    }, 220));
    function autobindLocation(lat, lon) {
      var manual = document.getElementById("tap-manual-loc");
      if (manual && manual.checked) return;
      ensureGaz().then(function () {
        var best = nearestCity(lat, lon, 120) || FT.nearest(gaz || [], lat, lon, 99999);
        if (!best) return;
        addPlaceState.cityRef = best;
        var c = document.getElementById("tap-city"), co = document.getElementById("tap-country");
        if (c && !c.dataset.touched) c.value = best.name || "";
        if (co && !co.dataset.touched) co.value = best.country || "";
      });
    }
    function setCoord(lat, lon, center) {
      addPlaceState.lat = lat; addPlaceState.lon = lon;
      setPickMarker(lat, lon);
      if (center) map.setView([lat, lon], Math.max(map.getZoom(), 6));  // country scale
      var la = document.getElementById("tap-lat"), lo = document.getElementById("tap-lon");
      if (la && document.activeElement !== la) la.value = lat.toFixed(5);
      if (lo && document.activeElement !== lo) lo.value = lon.toFixed(5);
      autobindLocation(lat, lon);
      saveDraftLocal();
    }
    window.__folioAddPlaceCoord = function (lat, lon) {
      setCoord(lat, lon, true);
      setMsg("已选择坐标，可继续放大微调");
    };
    ["tap-lat", "tap-lon"].forEach(function (id) {
      var e = document.getElementById(id);
      if (!e) return;
      e.addEventListener("change", function () {
        var la = parseFloat(document.getElementById("tap-lat").value);
        var lo = parseFloat(document.getElementById("tap-lon").value);
        if (isNaN(la) || isNaN(lo) || Math.abs(la) > 90 || Math.abs(lo) > 180) return;
        setCoord(la, lo, true);
        setMsg("已定位到该经纬度");
      });
    });
    ["tap-city", "tap-country"].forEach(function (id) {
      var e = document.getElementById(id);
      if (e) e.addEventListener("input", function () { e.dataset.touched = "1"; saveDraftLocal(); });
    });
    ["tap-name", "tap-desc", "tap-source"].forEach(function (id) {
      var e = document.getElementById(id);
      if (e) e.addEventListener("input", saveDraftLocal);
    });
    function pickedLevel() {
      var el = document.querySelector('input[name="tap-level"]:checked');
      return el ? el.value : "spot";
    }
    function doSave(draft) {
      var lvl = pickedLevel();
      var pname = (document.getElementById("tap-name").value || "").trim();
      var body = {
        name: pname,
        lat: addPlaceState.lat, lon: addPlaceState.lon,
        level: lvl,
        address: "",
        city_key: lvl === "city" ? pname : (document.getElementById("tap-city").value || "").trim(),
        country: (document.getElementById("tap-country").value || "").trim(), admin1: "",
        description: (document.getElementById("tap-desc").value || "").trim(),
        source_url: (document.getElementById("tap-source").value || "").trim(),
        book_ids: addPlaceState.books.map(function (b) { return b.id; }),
        photos: [],
        draft: !!draft
      };
      function fail(t) { if (msg) { msg.textContent = t; msg.classList.add("is-err"); } }
      if (body.lat == null || body.lon == null) return fail("请先在地图上点选坐标。");
      if (!body.name) return fail("请填写地点名称。");
      var url = addPlaceState.editId
        ? "/api/tours/places/" + addPlaceState.editId + "/update"
        : "/api/tours/places";
      api(url, body).then(function (res) {
        addPlaceMode = false;
        clearDraftLocal();
        var np = res.place;
        if (np && np.status !== "draft" && np.status !== "deleted") {
          var i = -1;
          for (var k = 0; k < places.length; k++) if (places[k].id === np.id) { i = k; break; }
          if (i >= 0) places[i] = np; else places.push(np);
          placeByKey[pkey(np.level, np.lat, np.lon)] = np;
          if (np.name) placeByName[np.name] = np;
        }
        reset(); showSide("tg-browse");
        setHint(draft ? "已存为草稿（在「我的地点」里查看）"
          : (res.status === "pending" ? "已提交，等待审核" : "已发布"), true);
      }).catch(function (e) { fail(e.message); });
    }
    var submit = document.getElementById("tap-submit");
    if (submit) submit.addEventListener("click", function () { doSave(false); });
    var draftBtn = document.getElementById("tap-draft");
    if (draftBtn) draftBtn.addEventListener("click", function () { doSave(true); });
    var cancelBtn = document.getElementById("tap-cancel");
    if (cancelBtn) cancelBtn.addEventListener("click", function () {
      var fromEdit = !!addPlaceState.editId;
      addPlaceMode = false; clearPickMarker(); clearDraftLocal(); reset();
      if (fromEdit && window.__folioLoadMyPlaces) window.__folioLoadMyPlaces();
      else showSide("tg-browse");
    });
  }

  // ---- left panel: create / mark ------------------------------------------
  var createKind = "author";
  function createCollection(kind, refId, title) {
    api("/api/tours/collection", {
      kind: kind, ref_id: refId, title: title || "",
      visibility: "private",
      scope: "world"
    }).then(function (t) {
      active = t; marking = true;
      var m = {}; (t.categories || []).forEach(function (c) { m[c.id] = c; }); catById[t.slug] = m;
      var summary = { slug: t.slug, title: t.title, kind: t.kind, stop_count: t.stop_count, view_count: t.view_count, is_owner: true };
      if (t.visibility === "public") {
        if (!collections.some(function (c) { return c.slug === t.slug; })) collections.unshift(summary);
      } else if (!drafts.some(function (c) { return c.slug === t.slug; })) {
        drafts.unshift(summary);
      }
      renderActive(); renderList(); renderFilters(); draw();
      ensureGaz();
      setHint("已进入标记模式，点击地图上的城市添加。", true);
    }).catch(function (e) { alert(e.message); });
  }
  function ensureGaz() {
    if (gaz) return Promise.resolve(gaz);
    return FT.gazetteer("world").then(function (g) { gaz = g; return g; });
  }
  // 用户添加的「城市」级地点，加入城市系统，参与吸附/搜索/归区
  function userCityEntries() {
    return (places || []).filter(function (p) {
      return p.level === "city" && p.lat != null && p.lon != null &&
        (p.status === "published" || p.status === "disputed");
    }).map(function (p) {
      return {
        level: "city", name: p.name, nameZh: p.name, nameEn: "",
        country: p.country || "", admin1: p.admin1 || "",
        lat: p.lat, lon: p.lon, user: true
      };
    });
  }
  function gazPlus() {
    var users = userCityEntries();
    if (!users.length) return gaz || [];
    return users.concat(gaz || []);
  }
  // 归区时优先匹配用户新增的城市（进入城市系统的城市），再回退到内置地名库
  function nearestCity(lat, lon, km) {
    var u = FT.nearest(userCityEntries(), lat, lon, km);
    if (u) return u;
    return FT.nearest(gaz || [], lat, lon, km);
  }
  function snapKm(z) { return z <= 3 ? 400 : z === 4 ? 200 : z === 5 ? 120 : z === 6 ? 80 : z === 7 ? 50 : 35; }
  function addPoint(city) {
    if (!active) return;
    api("/api/tours/" + active.slug + "/stops", {
      lat: city.lat, lon: city.lon, place_name: city.name || "",
      city: city.level === "city" ? (city.name || "") : "",
      admin1: city.admin1 || "", country: city.country || "", level: city.level || "city"
    }).then(function (res) {
      active.stops = (active.stops || []).concat([res.stop]);
      active.stop_count = res.stop_count;
      var c = collections.find(function (x) { return x.slug === active.slug; });
      if (c) c.stop_count = res.stop_count;
      renderActive(); draw(); setHint("已添加：" + (city.name || "地点"), true);
    }).catch(function (e) { setHint(e.message, false); });
  }
  var LEVEL_LABEL = { country: "国家", region: "地区", city: "城市", town: "乡镇", street: "街道", spot: "具体地点" };

  function bindPlaceSearch() {
    var input = document.getElementById("tg-place-q");
    var box = document.getElementById("tg-place-results");
    if (!input || input.__bound) return;
    input.__bound = true;
    var t = null;
    input.addEventListener("input", function () {
      clearTimeout(t);
      var q = input.value.trim();
      // 1) filter this collection's existing entries inline
      var any = false;
      Array.prototype.forEach.call(document.querySelectorAll("#tg-stops .tour-stop"), function (li) {
        var nameEl = li.querySelector(".tour-stop-name-ro");
        var name = nameEl ? nameEl.textContent : "";
        var show = !q || name.indexOf(q) !== -1;
        li.hidden = !show;
        if (show) any = true;
      });
      if (!q || any) { box.hidden = true; box.innerHTML = ""; return; }
      // 2) nothing matches -> offer to add this place
      t = setTimeout(function () {
        ensureGaz().then(function () {
          var g = gazPlus();
          box.innerHTML = '<li class="tour-place-addhead">暂无此地标记，添加地点：</li>';
          FT.search(g, q, 20).forEach(function (city) {
            var ph = placeByKey[pkey(city.level, city.lat, city.lon)] || placeByName[city.name];
            var note = ph ? (ph.footnote && ph.footnote.trim()) ? ph.footnote
              : ((ph.sample_notes && ph.sample_notes[0]) || "") : "";
            var existing = !!note;
            var li = document.createElement("li");
            li.innerHTML = '<span class="tour-result-level is-' + (city.level || "city") + '">' +
              (LEVEL_LABEL[city.level] || "") + "</span>" +
              '<span class="tour-result-name">' + FT.escapeHtml(city.name || "") + "</span>" +
              '<span class="tour-result-meta">' + FT.escapeHtml([city.admin1, city.country].filter(Boolean).join(" · ")) + "</span>";
            if (existing) {
              li.insertAdjacentHTML("beforeend", '<span class="tour-result-note">' +
                FT.escapeHtml(note.slice(0, 80)) + (note.length > 80 ? "…" : "") + "</span>");
            }
            if (boot.isAuthed) {
              var btn = document.createElement("button");
              btn.type = "button";
              btn.className = "tour-add-btn" + (existing ? "" : " is-create");
              btn.textContent = existing ? "添加到此巡礼" : "此地暂无条目，是否创建并添加";
              btn.addEventListener("click", function () { addPoint(city); input.value = ""; box.hidden = true; });
              li.appendChild(btn);
            } else if (!existing) {
              li.insertAdjacentHTML("beforeend",
                '<span class="tour-result-note">此地暂无条目。<a href="/login?next=/tours">登录</a>后可创建并添加。</span>');
            }
            box.appendChild(li);
          });
          box.hidden = box.children.length <= 1;
        });
      }, 220);
    });
    document.addEventListener("click", function (ev) { if (!box.contains(ev.target) && ev.target !== input) box.hidden = true; });
  }

  function focusStop(s) {
    if (s.lat == null) return;
    map.panTo([s.lat, s.lon], { animate: true });  // show it, no zoom
    var mk = markers[s.id];
    if (mk) {
      var region = catOf(active.slug, s.category_id), tag = catOf(active.slug, s.tag_id);
      mk.setIcon(FT.pinIcon(region ? region.color : "#9BB3C9", tag ? tag.color : null, true, s.level));
      setTimeout(function () {
        mk.setIcon(FT.pinIcon(region ? region.color : "#9BB3C9", tag ? tag.color : null, false, s.level));
      }, 1400);
      mk.openPopup();
    }
  }

  function showSide(which) {
    ["tg-browse", "tg-collection", "tg-create-sec", "tg-add-place", "tg-my-places", "tg-place-detail"].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.hidden = (id !== which);
    });
  }

  function setBrowseCollapsed(v) {
    var b = document.getElementById("tg-browse");
    var list = document.getElementById("tg-browse-list");
    if (v && list && !browseCollapsed) list.__scroll = list.scrollTop;
    browseCollapsed = v;
    if (b) b.classList.toggle("is-collapsed", v);
    if (!v && list && list.__scroll != null) {
      var sv = list.__scroll;
      requestAnimationFrame(function () { list.scrollTop = sv; });
    }
  }

  function renderActive() {
    var col = document.getElementById("tg-collection");
    if (!col) return;
    if (!active) {
      showSide("tg-browse");
      return;
    }
    showSide("tg-collection");
    document.getElementById("tg-col-title").textContent = active.title;
    document.getElementById("tg-col-badge").innerHTML = FT.kindBadge(active.kind);
    var pubBtn = document.getElementById("tg-publish");
    if (pubBtn) pubBtn.hidden = !(active.is_owner && active.visibility !== "public");
    var isStaff = boot.role === "admin" || boot.role === "editor";
    var au = document.getElementById("tg-author");
    if (au) {
      if (isStaff && active.is_owner) {
        au.hidden = false;
        var opts = ["FOLIO编辑部", "fan"];
        if (active.owner_name && opts.indexOf(active.owner_name) === -1) opts.push(active.owner_name);
        au.innerHTML = opts.map(function (o) {
          return "<option" + (o === active.owner_name ? " selected" : "") + ">" + FT.escapeHtml(o) + "</option>";
        }).join("");
      } else {
        au.hidden = true;
      }
    }
    document.getElementById("tg-col-meta").textContent =
      (active.status === "pending" ? "待审核" : active.visibility === "public" ? "公开" : "未公开") + " · " + (active.stop_count || 0) + " 个地点" +
      (active.owner_name ? " · 由 " + active.owner_name + " 创建" : "");
    bindPlaceSearch();
    var list = document.getElementById("tg-stops");
    list.innerHTML = "";
    (active.stops || []).forEach(function (s, i) {
      var region = catOf(active.slug, s.category_id);
      var canEdit = s.is_contributor || (active && active.is_owner) || boot.role === "admin" || boot.role === "editor";
      var bookList = (s.books && s.books.length) ? s.books : (s.book_id ? [{ id: s.book_id, title: s.book_title || "", slug: s.book_slug || "" }] : []);
      s.books = bookList;
      var li = document.createElement("li");
      li.className = "tour-stop";
      li.setAttribute("data-stop-id", s.id);
      li.innerHTML =
        '<div class="tour-stop-head"><span class="tour-stop-idx">' + (i + 1) + "</span>" +
        '<span class="tour-stop-name-ro">' + FT.escapeHtml(s.place_name || s.city || "") + "</span>" +
        '<span class="tour-stop-caret" aria-hidden="true">▸</span>' +
        (canEdit ? '<span class="tour-stop-menu-wrap"><button type="button" class="tour-stop-menu-btn" title="更多">⋯</button><span class="tour-stop-menu" hidden><button type="button" data-act="edit">编辑介绍</button><button type="button" data-act="history">版本历史</button><button type="button" data-act="delete">删除条目</button></span></span>' : "") +
        "</div>" +
        '<div class="tour-stop-body">' +
        '<div class="tour-stop-row">' +
        (s.country ? '<span class="tour-stop-country">' + FT.escapeHtml(s.country) + "</span>" : "") +
        (region ? '<span class="tour-stop-region" style="--pin:' + region.color + '">' + FT.escapeHtml(region.label) + "</span>" : "") +
        (s.contributor_name ? '<span class="tour-stop-by">由 ' + FT.escapeHtml(s.contributor_name) + " 添加</span>" : "") +
        "</div>" +
        '<div class="tour-stop-text">' +
        '<div class="tour-stop-intro" data-intro>' + (((s.draft && s.draft.note) || s.note) ? FT.escapeHtml((s.draft && s.draft.note) || s.note) : '<em>暂无介绍</em>') + (s.has_draft ? ' <span class="tour-draft-tag">' + (s.pending_review ? "待审核" : "未提交草稿") + "</span>" : "") + "</div>" +
        '<div class="tour-stop-links">' +
        (s.author_id ? '<span class="tour-link-wrap" data-kind="author"><a class="tour-link" href="/authors/' + s.author_id + '?back=/tours">作者：' + FT.escapeHtml(s.author_name || "") + "</a>" + (canEdit ? '<button type="button" class="tour-unlink" data-kind="author" title="取消关联作者">×</button>' : "") + "</span>" : "") +
        bookList.map(function (b) {
          return '<span class="tour-link-wrap" data-bid="' + b.id + '"><a class="tour-link" href="/books/' + FT.escapeHtml(b.slug) + '?back=/tours">书：《' + FT.escapeHtml(b.title || "") + "》</a>" + (canEdit ? '<button type="button" class="tour-unlink" data-kind="book" data-bid="' + b.id + '" title="取消关联书籍">×</button>' : "") + "</span>";
        }).join("") +
        (boot.isAuthed ? '<button type="button" class="tour-link-btn">添加相关作者 / 书籍</button>' : "") +
        "</div>" +
        '<div class="tour-link-box" hidden><input placeholder="搜索作者或书籍…" /><ul></ul>' +
        '<div class="tour-rec-fallback" hidden><p>暂无此作者和书籍</p><a class="tour-rec-detail" href="/recommend">如果没有你相关联的作者作品，请到「推荐一本书」→</a></div></div>' +
        "</div>" +
        '<div class="tour-stop-photos">' +
        (s.photos || []).concat(s.__previewPhotos || []).map(function (u) { return '<span class="tour-photo-thumb"><img src="' + FT.escapeHtml(u) + '" alt="" /></span>'; }).join("") +
        (s.is_contributor ? '<label class="tour-photo-btn">+ 照片<input type="file" accept="image/*" multiple hidden /></label>' : "") +
        '<span class="tour-stop-actions" data-actions></span>' +
        "</div>" +
        '<div class="tour-stop-notes"><div class="tour-notes-body"></div></div>' +
        "</div>";
      var notesBody = li.querySelector(".tour-notes-body");
      var notesLoaded = false;
      // click the entry header -> expand/collapse + zoom map to this place + light up marker
      var head = li.querySelector(".tour-stop-head");
      head.style.cursor = "pointer";
      head.title = "展开查看全部留言，并在地图上定位";
      head.addEventListener("click", function (ev) {
        if (ev.target.closest("button")) return;
        var open = li.classList.toggle("is-open");
        openStopId = open ? s.id : null;
        if (open) {
          Array.prototype.forEach.call(document.querySelectorAll("#tg-stops .tour-stop.is-open"), function (o) {
            if (o !== li) o.classList.remove("is-open");
          });
          focusStop(s);
          if (!notesLoaded) { notesLoaded = true; loadStopNotes(s, notesBody); }
        }
      });
      // ⋯ menu: edit intro / delete entry
      var menuBtn = li.querySelector(".tour-stop-menu-btn");
      if (menuBtn) {
        var menu = li.querySelector(".tour-stop-menu");
        menuBtn.addEventListener("click", function (ev) { ev.stopPropagation(); menu.hidden = !menu.hidden; });
        menu.querySelector('[data-act="edit"]').addEventListener("click", function () {
          menu.hidden = true;
          li.classList.add("is-editing");
          var box = li.querySelector("[data-intro]");
          var ta = document.createElement("textarea");
          ta.className = "tour-stop-note"; ta.value = s.note || "";
          box.replaceWith(ta);
          var isPublic = active.visibility === "public";
          var actions = li.querySelector("[data-actions]");
          var primary = document.createElement("button");
          primary.type = "button"; primary.className = "tour-stop-edit"; primary.textContent = isPublic ? "提交" : "保存";
          var cancelBtn = document.createElement("button");
          cancelBtn.type = "button"; cancelBtn.className = "tour-stop-edit is-ghost"; cancelBtn.textContent = "取消";
          actions.appendChild(primary); actions.appendChild(cancelBtn);
          cancelBtn.addEventListener("click", function () {
            if (!confirm("本次修改作废？")) return;
            renderActive();
          });
          function saveBody() {
            var body = { note: ta.value, book_ids: (s.books || []).map(function (b) { return b.id; }) };
            if (s.__unlinkAuthor) body.author_id = 0;
            return body;
          }
          function bindPendingPhotos() {
            if (s.__pending && s.__pending.length) {
              return api("/api/tours/" + active.slug + "/stops/" + s.id + "/bind-media", { ids: s.__pending })
                .then(function (res) { s.photos = res.photos; s.media_url = s.photos[0] || s.media_url; s.__pending = []; s.__previewPhotos = []; });
            }
            return Promise.resolve();
          }
          primary.addEventListener("click", function () {
            bindPendingPhotos().then(function () {
              return api("/api/tours/" + active.slug + "/stops/" + s.id + "/draft", saveBody());
            }).then(function (res) {
              s.draft = res.draft; s.has_draft = true; s.__unlinkAuthor = false;
              if (!isPublic) { renderActive(); setHint("已保存到草稿（仅你可见）", true); return null; }
              return api("/api/tours/" + active.slug + "/stops/" + s.id + "/submit", {});
            }).then(function (res) {
              if (!res) return;
              if (res.pending) {
                s.pending_review = true; s.has_draft = true;
                renderActive(); setHint("已提交，审核通过后公开", true); return;
              }
              s.draft = null; s.has_draft = false; s.pending_review = false;
              renderActive(); setHint("已提交", true);
            }).catch(function (e) { setHint(e.message, false); });
          });
        });
        menu.querySelector('[data-act="history"]').addEventListener("click", function () {
          menu.hidden = true;
          fetch("/api/tours/stops/" + s.id + "/revisions", { credentials: "same-origin" }).then(function (r) { return r.json(); }).then(function (d) {
            var box = li.querySelector(".tour-rev-list");
            if (!box) { box = document.createElement("div"); box.className = "tour-rev-list"; li.querySelector(".tour-stop-body").appendChild(box); }
            box.innerHTML = '<p class="tour-rev-title">版本历史</p>';
            (d.revisions || []).forEach(function (rv) {
              var row = document.createElement("div");
              row.className = "tour-rev-row";
              row.innerHTML = '<span class="tour-rev-time">' + FT.escapeHtml((rv.created_at || "").replace("T", " ").slice(0, 16)) + "</span>" +
                '<span class="tour-rev-note">' + FT.escapeHtml((rv.note || "（空）").slice(0, 40)) + "</span>" +
                '<button type="button" class="tour-rev-rollback">回滚</button>';
              row.querySelector(".tour-rev-rollback").addEventListener("click", function () {
                api("/api/tours/stops/" + s.id + "/rollback", { rev_id: rv.id }).then(function () {
                  renderActive(); setHint("已回滚到该版本", true);
                }).catch(function (e) { alert(e.message); });
              });
              box.appendChild(row);
            });
            if (!(d.revisions || []).length) box.innerHTML += '<p class="clm-muted">暂无历史版本。</p>';
          }).catch(function () {});
        });
        menu.querySelector('[data-act="delete"]').addEventListener("click", function () {
          menu.hidden = true;
          if (!confirm("删除这个条目？")) return;
          api("/api/tours/" + active.slug + "/stops/" + s.id + "/delete", {}).then(function (res) {
            active.stops = active.stops.filter(function (x) { return x.id !== s.id; });
            active.stop_count = res.stop_count; renderActive(); draw();
          }).catch(function (e) { alert(e.message); });
        });
      }
      // photos (creator only)
      var pinput = li.querySelector('.tour-stop-photos input[type="file"]');
      if (pinput) pinput.addEventListener("change", function (ev) {
        var files = Array.prototype.slice.call(ev.target.files || []);
        if (!files.length) return;
        var seq = Promise.resolve();
        files.forEach(function (file) {
          seq = seq.then(function () {
            var fd = new FormData(); fd.append("file", file); fd.append("csrf", csrf);
            return fetch("/api/tours/media", { method: "POST", credentials: "same-origin", body: fd })
              .then(function (r) { if (!r.ok) throw new Error("上传失败"); return r.json(); })
              .then(function (res) {
                s.__pending = (s.__pending || []).concat([res.id]);
                s.__previewPhotos = (s.__previewPhotos || []).concat([res.url]);
              })
              .catch(function (e) { setHint(e.message, false); });
          });
        });
        seq.then(function () { renderActive(); setHint("照片已上传到暂存区，点「⋯→编辑介绍→保存」正式绑定", true); });
      });
      // link author / book
      var lb = li.querySelector(".tour-link-btn");
      if (lb) lb.addEventListener("click", function () {
        var box = li.querySelector(".tour-link-box");
        box.hidden = !box.hidden;
        var inp = box.querySelector("input"), ul = box.querySelector("ul");
        if (!box.hidden && inp) inp.focus();
        var fallback = box.querySelector(".tour-rec-fallback");
        inp.addEventListener("input", debounce(function () {
          var q = inp.value.trim();
          ul.innerHTML = "";
          if (fallback) fallback.hidden = true;
          if (!q) return;
          fetch("/api/tours/search?q=" + encodeURIComponent(q), { credentials: "same-origin" }).then(function (r) { return r.json(); }).then(function (d) {
            (d.authors || []).forEach(function (a) {
              var x = document.createElement("li"); x.textContent = "作者：" + a.name;
              x.addEventListener("click", function () {
                s.author_id = a.id; s.author_name = a.name; s.__unlinkAuthor = false;
                var linksRow = li.querySelector(".tour-stop-links");
                var old = linksRow.querySelector('.tour-link-wrap[data-kind="author"]');
                if (old) old.remove();
                var linkBtn = linksRow.querySelector(".tour-link-btn");
                var span = document.createElement("span");
                span.className = "tour-link-wrap"; span.setAttribute("data-kind", "author");
                span.innerHTML = '<a class="tour-link" href="/authors/' + a.id + '?back=/tours">作者：' + FT.escapeHtml(a.name) + "</a>" +
                  '<button type="button" class="tour-unlink" data-kind="author" title="取消关联作者">×</button>';
                linksRow.insertBefore(span, linkBtn);
                span.querySelector(".tour-unlink").addEventListener("click", function (ev) {
                  ev.preventDefault(); ev.stopPropagation();
                  s.__unlinkAuthor = true; span.remove();
                  setHint("已移除关联，点「保存」或「提交」后生效", true);
                });
                ul.innerHTML = ""; inp.value = "";
              });
              ul.appendChild(x);
            });
            (d.books || []).forEach(function (bk) {
              var x = document.createElement("li"); x.textContent = "书：" + (bk.chinese || bk.title);
              x.addEventListener("click", function () {
                s.books = s.books || [];
                if (!s.books.some(function (b) { return b.id === bk.id; })) {
                  s.books.push({ id: bk.id, title: bk.chinese || bk.title, slug: bk.slug || "" });
                  var linksRow = li.querySelector(".tour-stop-links");
                  var linkBtn = linksRow.querySelector(".tour-link-btn");
                  var span = document.createElement("span");
                  span.className = "tour-link-wrap"; span.setAttribute("data-bid", bk.id);
                  span.innerHTML = '<a class="tour-link" href="/books/' + FT.escapeHtml(bk.slug) + '?back=/tours">书：《' + FT.escapeHtml(bk.chinese || bk.title) + "》</a>" +
                    '<button type="button" class="tour-unlink" data-kind="book" data-bid="' + bk.id + '" title="取消关联书籍">×</button>';
                  linksRow.insertBefore(span, linkBtn);
                  span.querySelector(".tour-unlink").addEventListener("click", function (ev) {
                    ev.preventDefault(); ev.stopPropagation();
                    s.books = s.books.filter(function (b) { return b.id !== bk.id; });
                    span.remove();
                    setHint("已移除关联，点「保存」或「提交」后生效", true);
                  });
                }
                ul.innerHTML = ""; inp.value = "";
              });
              ul.appendChild(x);
            });
            if (!ul.children.length && fallback) fallback.hidden = false;
          }).catch(function () {});
        }, 250));
        var dt = box.querySelector(".tour-rec-detail");
        if (dt) dt.addEventListener("click", function () {
          dt.href = "/recommend?title=" + encodeURIComponent(inp.value || "") + "&back=" + encodeURIComponent(location.pathname);
        });
      });
      Array.prototype.forEach.call(li.querySelectorAll(".tour-unlink"), function (btn) {
        btn.addEventListener("click", function (ev) {
          ev.preventDefault();
          ev.stopPropagation();
          var kind = btn.getAttribute("data-kind");
          var wrap = btn.closest(".tour-link-wrap");
          if (kind === "book") {
            var bid = parseInt(btn.getAttribute("data-bid"), 10);
            s.books = (s.books || []).filter(function (b) { return b.id !== bid; });
          } else {
            s.__unlinkAuthor = true;
          }
          if (wrap) wrap.remove();
          setHint("已移除关联，点「保存」或「提交」后生效", true);
        });
      });
      if (openStopId === s.id) {
        li.classList.add("is-open");
        notesLoaded = true;
        loadStopNotes(s, notesBody);
      }
      list.appendChild(li);
    });
  }

  function keyFromHref(h) {
    h = h || "";
    if (h.indexOf("/books/") === 0) return { kind: "book", key: decodeURIComponent(h.slice(7).split("?")[0]) };
    if (h.indexOf("/authors/") === 0) return { kind: "author", key: decodeURIComponent(h.slice(9).split("?")[0]) };
    return null;
  }

  function updatePeekTab() {
    var peek = document.querySelector(".tg-detail-peek");
    if (!peek) return;
    if (pinnedData && pinnedData.type === "book" && pinnedData.cover) {
      peek.classList.add("has-cover");
      peek.innerHTML = '<img src="' + FT.escapeHtml(pinnedData.cover) + '" alt="" />';
    } else {
      peek.classList.remove("has-cover");
      peek.textContent = pinnedData
        ? (pinnedData.type === "book" ? "书籍" : pinnedData.type === "author" ? "作者" : "地点")
        : "书籍";
    }
  }

  function openDetail(kind, key, push, preview, keepPeek) {
    var det0 = document.getElementById("tg-detail");
    var k = kind + ":" + key;
    if (det0 && !det0.hidden && currentDetailKey === k) {
      // already showing this one; just record preview/pin state
      previewingDetail = !!preview;
      if (!preview) {
        pinnedDetail = { kind: kind, key: key };
        if (currentDetailData) { pinnedData = currentDetailData; updatePeekTab(); }
      }
      return;
    }
    currentDetailKey = k;
    previewingDetail = !!preview;
    detailPushed = (push !== false);
    var url = kind === "book" ? "/api/books/" + encodeURIComponent(key)
      : kind === "place" ? "/api/tours/places/" + encodeURIComponent(key) + "/stops"
      : "/api/authors/" + encodeURIComponent(key);
    function applyDetail(d) {
      var body = document.getElementById("tg-detail-body");
      if (!body) return;
      currentDetailData = d;
      if (kind === "place") {
        body.innerHTML = "<h2>" + FT.escapeHtml(d.name || "地点") + "</h2>" +
          "<h3>被标记的巡礼</h3><div class='tg-detail-places'>" + (d.collections || []).map(function (c) {
            return '<button type="button" class="tg-detail-place" data-detail-tour="' + FT.escapeHtml(c.slug) + '">' + FT.escapeHtml(c.title) + "</button>";
          }).join("") + "</div>" +
          "<h3>条目</h3><div class='tg-detail-places'>" + (d.stops || []).map(function (s) {
            return '<button type="button" class="tg-detail-place" data-detail-tour="' + FT.escapeHtml(s.map_slug) + '" data-detail-stop="' + s.stop_id + '">' +
              FT.escapeHtml(s.map_title) + " › " + FT.escapeHtml(s.place_name) + "</button>";
          }).join("") + "</div>";
        document.getElementById("tg-detail-full").href = "javascript:void(0)";
      } else if (d.type === "book") {
        body.innerHTML = '<img class="tg-detail-cover" src="' + FT.escapeHtml(d.cover) + '" alt="" />' +
          "<h2>" + FT.escapeHtml(d.chinese || d.title) + "</h2>" +
          '<p class="clm-muted">' + FT.escapeHtml(d.title) + "</p>" +
          (d.author ? '<p>作者：<a href="#" data-detail-author="' + (d.author_id || "") + '">' + FT.escapeHtml(d.author) + "</a></p>" : "") +
          (d.blurb ? "<p>" + FT.escapeHtml(d.blurb) + "</p>" : "");
        document.getElementById("tg-detail-full").href = withStateBack("/books/" + encodeURIComponent(d.slug) + "?back=/tours");
        if (push === false) history.replaceState({ book: d.slug }, "", "?book=" + encodeURIComponent(d.slug)); else history.pushState({ book: d.slug }, "", "?book=" + encodeURIComponent(d.slug));
      } else {
        body.innerHTML = "<h2>" + FT.escapeHtml(d.name) + "</h2>" +
          (d.localized ? '<p class="clm-muted">' + FT.escapeHtml(d.localized) + "</p>" : "") +
          (d.nationality ? '<p class="clm-muted">' + FT.escapeHtml(d.nationality) + "</p>" : "") +
          (d.bio ? "<p>" + FT.escapeHtml(d.bio) + "</p>" : "") +
          "<h3>作品</h3><div class='tg-detail-books'>" + (d.books || []).map(function (b) {
            return '<a href="#" class="tg-detail-book" data-detail-book="' + FT.escapeHtml(b.slug) + '">' +
              '<img src="' + FT.escapeHtml(b.cover) + '" alt="" /><span>' + FT.escapeHtml(b.chinese || b.title) + "</span></a>";
          }).join("") + "</div>";
        document.getElementById("tg-detail-full").href = withStateBack("/authors/" + d.id + "?back=/tours");
        if (push === false) history.replaceState({ author: d.id }, "", "?author=" + d.id); else history.pushState({ author: d.id }, "", "?author=" + d.id);
      }
      // related places + collections from the loaded globe points
      var related = points.filter(function (p) {
        return d.type === "book" ? p.book_id === d.id : p.author_id === d.id;
      });
      if (related.length) {
        var tourset = {};
        related.forEach(function (p) { tourset[p.title] = p.tour; });
        body.insertAdjacentHTML("beforeend",
          "<h3>关联地点</h3><div class='tg-detail-places'>" + related.map(function (p) {
            return '<button type="button" class="tg-detail-place" data-detail-place="' + p.id + '">' +
              FT.escapeHtml(p.place_name || p.city || "") + "</button>";
          }).join("") + "</div>" +
          "<h3>关联合集</h3><div class='tg-detail-places'>" + Object.keys(tourset).map(function (nm) {
            return '<button type="button" class="tg-detail-place" data-detail-tour="' + FT.escapeHtml(tourset[nm]) + '">' + FT.escapeHtml(nm) + "</button>";
          }).join("") + "</div>");
      }
      var det = document.getElementById("tg-detail");
      det.hidden = false;
      det.classList.remove("is-peek");
      if (!preview) { pinnedData = d; updatePeekTab(); }
      if (keepPeek) det.classList.add("is-peek");
      var shell = document.querySelector(".tour-globe");
      if (shell) shell.classList.add("has-detail");
      requestAnimationFrame(function () { det.classList.add("is-open"); });
    }
    if (detailCache[k]) { applyDetail(detailCache[k]); return; }
    fetch(url, { credentials: "same-origin" }).then(function (r) { return r.json(); })
      .then(function (d) { detailCache[k] = d; applyDetail(d); }).catch(function () {});
  }
  function closeDetail() {
    var d = document.getElementById("tg-detail");
    if (!d || d.hidden) return;
    d.classList.remove("is-open");
    d.classList.remove("is-peek");
    d.style.transform = "";
    var sideEl = document.querySelector(".tour-globe-side");
    if (sideEl) sideEl.classList.remove("is-peek");
    var shell = document.querySelector(".tour-globe");
    if (shell) shell.classList.remove("has-detail");
    if (window.matchMedia("(min-width: 901px)").matches) {
      d.hidden = true;
    } else {
      setTimeout(function () { if (!d.classList.contains("is-open")) d.hidden = true; }, 260);
    }
    detailPushed = false;
    currentDetailKey = null;
    previewingDetail = false;
    pinnedDetail = null;
    pinnedData = null;
    updatePeekTab();
  }
  function bindDetail() {
    document.addEventListener("click", function (ev) {
      var a = ev.target.closest && ev.target.closest(".tour-link");
      if (a) {
        ev.preventDefault();
        var kk = keyFromHref(a.getAttribute("href") || "");
        if (kk) { pinnedDetail = kk; openDetail(kk.kind, kk.key, true, false); }
        return;
      }
      var bk = ev.target.closest && ev.target.closest("[data-detail-book]");
      if (bk) { ev.preventDefault(); openDetail("book", bk.getAttribute("data-detail-book")); return; }
      var au = ev.target.closest && ev.target.closest("[data-detail-author]");
      if (au) { ev.preventDefault(); if (au.getAttribute("data-detail-author")) openDetail("author", au.getAttribute("data-detail-author")); return; }
      var pl = ev.target.closest && ev.target.closest("[data-detail-place]");
      if (pl) {
        var pid = parseInt(pl.getAttribute("data-detail-place"), 10);
        var pt = points.find(function (x) { return x.id === pid; });
        if (pt) { closeDetail(); if (map) { map.setView([pt.lat, pt.lon], Math.max(map.getZoom(), 7)); var mk = markers[pt.id]; if (mk) mk.openPopup(); } }
        return;
      }
      var tr = ev.target.closest && ev.target.closest("[data-detail-tour]");
      if (tr) {
        var sid = tr.getAttribute("data-detail-stop");
        closeDetail();
        selectCollection(tr.getAttribute("data-detail-tour"), sid ? parseInt(sid, 10) : null);
        return;
      }
    });
    var back = document.getElementById("tg-detail-back");
    if (back) back.addEventListener("click", function () { closeDetail(); history.replaceState(null, "", location.pathname + location.search.replace(/[?&](book|author)=[^&]*/g, "").replace(/^&/, "?").replace(/^\?$/, "")); });
    var handle = document.getElementById("tg-detail-handle");
    var det = document.getElementById("tg-detail");
    if (handle && det) {
      var sy = 0, dy = 0, dragging = false;
      handle.addEventListener("touchstart", function (e) { dragging = true; sy = e.touches[0].clientY; dy = 0; det.style.transition = "none"; }, { passive: true });
      handle.addEventListener("touchmove", function (e) {
        if (!dragging) return;
        dy = Math.max(0, e.touches[0].clientY - sy);
        det.style.transform = "translateY(" + dy + "px)";
      }, { passive: true });
      handle.addEventListener("touchend", function () {
        dragging = false; det.style.transition = "";
        if (dy > 120) closeDetail(); else det.style.transform = "";
      });
    }
    window.addEventListener("popstate", function () { if (!/[?&](book|author)=/.test(location.search)) { detailPushed = false; closeDetail(); } });
    // peek: collapse panels when the cursor is away; hover the slim tab to expand
    var sideEl = document.querySelector(".tour-globe-side");
    document.addEventListener("mousemove", function (ev) {
      var ae = document.activeElement;
      var typing = (ae && (ae.id === "globe-q" || ae.id === "tg-place-q"));
      if (sideEl) {
        sideEl.classList.remove("is-peek");
        var over = sideEl.contains(ev.target);
        if (active) {
          // a specific collection hides its entry list when the cursor is away,
          // remembering the scroll position so it does not jump back to the top
          var collapse = !over && !typing;
          var stops = document.getElementById("tg-stops");
          if (collapse && !sideEl.classList.contains("is-peek-stops") && stops) stops.__scroll = stops.scrollTop;
          sideEl.classList.toggle("is-peek-stops", collapse);
          if (!collapse && stops && stops.__scroll != null) {
            var sv = stops.__scroll;
            requestAnimationFrame(function () { stops.scrollTop = sv; });
          }
        } else {
          sideEl.classList.remove("is-peek-stops");
          // the browse list expands on hover, collapses when the cursor leaves
          // (kept open while a place's related list or the add-place form is active)
          setBrowseCollapsed(!over && !typing && !marksHover && !marksPinned && !addPlaceMode);
        }
      }
      if (det && !det.hidden) {
        var overLink = ev.target.closest && ev.target.closest(".tour-link");
        det.classList.toggle("is-peek", !det.contains(ev.target) && !previewingDetail && !overLink);
      }
    });
    document.addEventListener("focusin", function (ev) {
      if (ev.target && (ev.target.id === "globe-q" || ev.target.id === "tg-place-q")) {
        if (sideEl) sideEl.classList.remove("is-peek-stops", "is-peek");
      }
    });
    // hover a book/author link -> preview its detail; leaving reverts to the pinned one
    var hoverTimer = null;
    document.addEventListener("mouseover", function (ev) {
      var a = ev.target.closest && ev.target.closest(".tour-link");
      if (!a) return;
      var kk = keyFromHref(a.getAttribute("href") || "");
      if (!kk) return;
      if (currentDetailKey === kk.kind + ":" + kk.key) {
        if (hoverTimer) { clearTimeout(hoverTimer); hoverTimer = null; }
        var dd = document.getElementById("tg-detail");
        if (dd && !dd.hidden) dd.classList.remove("is-peek");
        return;
      }
      if (hoverTimer) clearTimeout(hoverTimer);
      hoverTimer = setTimeout(function () { hoverTimer = null; openDetail(kk.kind, kk.key, false, true); }, 90);
    });
    document.addEventListener("mouseout", function (ev) {
      var a = ev.target.closest && ev.target.closest(".tour-link");
      if (!a) return;
      if (hoverTimer) { clearTimeout(hoverTimer); hoverTimer = null; }
      var kk = keyFromHref(a.getAttribute("href") || "");
      if (!kk) return;
      var pinnedKey = pinnedDetail ? pinnedDetail.kind + ":" + pinnedDetail.key : null;
      if (currentDetailKey === pinnedKey) return;  // pinned one stays
      if (pinnedDetail) openDetail(pinnedDetail.kind, pinnedDetail.key, false, false, true);
      else closeDetail();
    });
  }

  function loadStopNotes(stop, box) {
    fetch("/api/tours/stops/" + stop.id + "/notes", { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        box.innerHTML = "";
        (d.notes || []).forEach(function (n) { box.appendChild(noteEl(stop, n)); });
        if (boot.isAuthed) {
          var wrap = document.createElement("div");
          wrap.className = "tour-note-add";
          wrap.innerHTML = '<textarea placeholder="写下你喜欢的文段、你知道的故事…"></textarea>' +
            '<button type="button">发表</button>';
          wrap.querySelector("button").addEventListener("click", function () {
            var ta = wrap.querySelector("textarea");
            if (!ta.value.trim()) return;
            api("/api/tours/stops/" + stop.id + "/notes", { body: ta.value }).then(function (res) {
              ta.value = "";
              box.insertBefore(noteEl(stop, res.note), wrap);
            }).catch(function (e) { alert(e.message); });
          });
          box.appendChild(wrap);
        } else {
          box.insertAdjacentHTML("beforeend", '<p class="tour-note-hint"><a href="/login?next=/tours">登录</a>后可留言。</p>');
        }
      }).catch(function () {});
  }
  function noteEl(stop, n) {
    var el = document.createElement("div");
    el.className = "tour-note";
    el.innerHTML =
      (n.avatar ? '<img class="tour-note-avatar" src="' + FT.escapeHtml(n.avatar) + '" alt="" />' : '<span class="tour-note-avatar is-empty"></span>') +
      '<div class="tour-note-main"><span class="tour-note-author">' + FT.escapeHtml(n.author || "访客") + "</span>" +
      '<span class="tour-note-body">' + FT.escapeHtml(n.body) + "</span>" +
      '<span class="tour-note-actions"><button type="button" class="tour-note-like' + (n.liked ? " is-on" : "") + '">♥ ' + (n.like_count || 0) + "</button>" +
      (n.mine ? '<button type="button" class="tour-note-menu-btn" title="更多">⋯</button><span class="tour-note-menu" hidden><button type="button" data-act="edit">编辑</button><button type="button" data-act="delete">删除</button><button type="button" data-act="private">设为私密</button></span>' : "") +
      "</span></div>";
    var menuBtn = el.querySelector(".tour-note-menu-btn");
    if (menuBtn) {
      var menu = el.querySelector(".tour-note-menu");
      menuBtn.addEventListener("click", function (ev) { ev.stopPropagation(); menu.hidden = !menu.hidden; });
      menu.querySelector('[data-act="edit"]').addEventListener("click", function () {
        var v = prompt("修改留言：", n.body);
        if (v == null) return;
        api("/api/tours/notes/" + n.id + "/edit", { body: v }).then(function (res) {
          n.body = res.body; el.querySelector(".tour-note-body").textContent = res.body; menu.hidden = true;
        }).catch(function (e) { alert(e.message); });
      });
      menu.querySelector('[data-act="delete"]').addEventListener("click", function () {
        if (!confirm("删除这条留言？")) return;
        api("/api/tours/notes/" + n.id + "/delete", {}).then(function () { el.remove(); }).catch(function (e) { alert(e.message); });
      });
      menu.querySelector('[data-act="private"]').addEventListener("click", function () {
        api("/api/tours/notes/" + n.id + "/edit", { is_private: true }).then(function () { el.remove(); }).catch(function (e) { alert(e.message); });
      });
    }
    var likeBtn = el.querySelector(".tour-note-like");
    likeBtn.addEventListener("click", function () {
      api("/api/tours/notes/" + n.id + "/like", {}).then(function (res) {
        n.liked = res.liked; n.like_count = res.like_count;
        likeBtn.textContent = "♥ " + res.like_count; likeBtn.classList.toggle("is-on", res.liked);
      }).catch(function (e) { alert(e.message); });
    });
    return el;
  }
  function bindCreate() {
    Array.prototype.forEach.call(document.querySelectorAll("[data-create-kind]"), function (b) {
      b.addEventListener("click", function () {
        createKind = b.getAttribute("data-create-kind");
        Array.prototype.forEach.call(document.querySelectorAll("[data-create-kind]"), function (x) { x.classList.toggle("is-active", x === b); });
        var q = document.getElementById("tg-create-q");
        var ph = {
          author: "输入作者名", book: "输入书名",
          region: "输入地域名称（如 北欧、苏格兰）", genre: "输入流派名称（如 悬疑、科幻）",
          custom: "输入自定义名称"
        };
        q.placeholder = ph[createKind] || "输入名称";
      });
    });
    var input = document.getElementById("tg-create-q"), box = document.getElementById("tg-create-results"), t = null;
    var go = document.getElementById("tg-create-go");
    if (go) go.addEventListener("click", function () {
      var q = input.value.trim();
      if (!q) { input.focus(); return; }
      if (createKind === "custom" || createKind === "region" || createKind === "genre") {
        createCollection(createKind, null, q); input.value = ""; box.hidden = true;
      } else {
        input.dispatchEvent(new Event("input"));
      }
    });
    input.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter" && go) { ev.preventDefault(); go.click(); }
    });
    input.addEventListener("input", function () {
      clearTimeout(t);
      var q = input.value.trim();
      if (!q) { box.hidden = true; return; }
      if (createKind === "custom" || createKind === "region" || createKind === "genre") {
        box.innerHTML = "";
        var li = document.createElement("li");
        li.innerHTML = '<span class="tour-result-level is-country">创建</span><span class="tour-result-name">' + FT.escapeHtml(q) + "</span>";
        li.addEventListener("click", function () { box.hidden = true; createCollection(createKind, null, q); input.value = ""; });
        box.appendChild(li); box.hidden = false;
        return;
      }
      t = setTimeout(function () {
        fetch("/api/tours/search?q=" + encodeURIComponent(q), { credentials: "same-origin" })
          .then(function (r) { return r.json(); })
          .then(function (d) {
            box.innerHTML = "";
            var items = createKind === "author" ? (d.authors || []) : (d.books || []);
            items.forEach(function (it) {
              var li = document.createElement("li");
              var name = createKind === "author" ? it.name : (it.chinese || it.title);
              li.innerHTML = '<span class="tour-result-level is-' + (createKind === "author" ? "region" : "city") + '">' +
                (createKind === "author" ? "作者" : "书") + '</span><span class="tour-result-name">' + FT.escapeHtml(name) + "</span>";
              li.addEventListener("click", function () { box.hidden = true; createCollection(createKind, it.id, name); input.value = ""; });
              box.appendChild(li);
            });
            box.hidden = box.children.length === 0;
          }).catch(function () {});
      }, 250);
    });
    document.addEventListener("click", function (ev) { if (!box.contains(ev.target) && ev.target !== input) box.hidden = true; });
    var back = document.getElementById("tg-back");
    if (back) back.addEventListener("click", function () {
      marking = false; active = null;
      if (collectionFrom === "tg-my-places" && window.__folioLoadMyPlaces) {
        collectionFrom = "tg-browse";
        window.__folioLoadMyPlaces();
      } else {
        collectionFrom = "tg-browse";
        renderActive(); renderList(); draw();
      }
    });
    var gaf = document.getElementById("globe-autofollow");
    if (gaf) {
      gaf.checked = autoFollowCollection;
      gaf.addEventListener("change", function () {
        autoFollowCollection = gaf.checked;
        localStorage.setItem("folio_af_collection", autoFollowCollection ? "1" : "0");
      });
    }
    var gall = document.getElementById("globe-all");
    if (gall) gall.addEventListener("click", function () { setMode("all"); });
    var db = document.getElementById("globe-drafts"), pb = document.getElementById("globe-published");
    var ga = document.getElementById("globe-all");
    var tb = document.getElementById("globe-trash");
    function setMode(m) {
      if (listMode === m && !browseCollapsed) {
        // clicking the selected mode again collapses the list
        listMode = "all";
        setBrowseCollapsed(true);
        active = null; marking = false;
        if (db) db.classList.remove("is-on");
        if (pb) pb.classList.remove("is-on");
        if (ga) ga.classList.remove("is-on");
        if (tb) tb.classList.remove("is-on");
        renderActive(); renderList(); draw();
        return;
      }
      listMode = m;
      setBrowseCollapsed(false);
      active = null; marking = false;
      if (db) db.classList.toggle("is-on", listMode === "draft");
      if (pb) pb.classList.toggle("is-on", listMode === "published");
      if (ga) ga.classList.toggle("is-on", listMode === "all");
      if (tb) tb.classList.toggle("is-on", listMode === "trash");
      if (listMode === "trash") {
        fetch("/api/tours/trash", { credentials: "same-origin" }).then(function (r) { return r.json(); }).then(function (d) {
          trashItems = d.trash || []; renderActive(); renderList();
        }).catch(function () { trashItems = []; renderList(); });
      } else {
        renderActive(); renderList(); draw();
      }
    }
    if (db) db.addEventListener("click", function () { setMode("draft"); });
    if (tb) tb.addEventListener("click", function () { setMode("trash"); });
    if (pb) pb.addEventListener("click", function () { setMode("published"); });
    var au = document.getElementById("tg-author");
    if (au) au.addEventListener("change", function () {
      if (!active) return;
      api("/api/tours/" + active.slug + "/meta", { author_name: au.value }).then(function () {
        active.owner_name = au.value;
        [collections, published, drafts].forEach(function (arr) {
          arr.forEach(function (x) { if (x.slug === active.slug) x.owner_name = au.value; });
        });
        renderActive(); renderList(); setHint("署名已更新", true);
      }).catch(function (e) { alert(e.message); });
    });
    var pub = document.getElementById("tg-publish");
    if (pub) pub.addEventListener("click", function () {
      if (!active) return;
      api("/api/tours/" + active.slug + "/publish", {}).then(function () {
        active.visibility = "public"; active.status = (boot.role === "admin" || boot.role === "editor") ? "published" : "pending";
        drafts = drafts.filter(function (x) { return x.slug !== active.slug; });
        if (!published.some(function (x) { return x.slug === active.slug; })) {
          published.unshift({ slug: active.slug, title: active.title, kind: active.kind, stop_count: active.stop_count, view_count: active.view_count, is_owner: true });
        }
        if (!collections.some(function (x) { return x.slug === active.slug; })) {
          collections.unshift({ slug: active.slug, title: active.title, kind: active.kind, stop_count: active.stop_count, view_count: active.view_count, is_owner: true });
        }
        renderActive(); setHint("已发布", true);
      }).catch(function (e) { alert(e.message); });
    });
  }

  (async function init() {
    function setHeaderH() {
      var h = document.querySelector(".site-header");
      if (h) document.documentElement.style.setProperty("--header-h", h.offsetHeight + "px");
    }
    setHeaderH();
    window.addEventListener("resize", function () { setHeaderH(); if (map) map.invalidateSize(); });
    map = await FT.baseMap(mapEl, "world", { lat: 22, lon: 8, zoom: 2 });
    window.__tourGlobeMap = map;
    map.on("zoomend", function () { if (!active) draw(); });
    map.on("click", function () {
      var q = document.getElementById("globe-q");
      if (q && document.activeElement === q) q.blur();
      if (!active) setBrowseCollapsed(true);
    });
    map.on("click", function (e) {
      if (addPlaceMode && window.__folioAddPlaceCoord) {
        window.__folioAddPlaceCoord(e.latlng.lat, e.latlng.lng);
        return;
      }
      if (!marking || !active) return;
      ensureGaz().then(function () {
        var hit = nearestCity(e.latlng.lat, e.latlng.lng, snapKm(map.getZoom()));
        if (!hit) { setHint("附近没有可标记的城市，请放大后再点。", false); return; }
        var html = '<div class="tour-confirm"><p>确认在此处添加「' + FT.escapeHtml(hit.name || "地点") + '」？</p>' +
          '<button type="button" class="tc-yes">确认添加</button><button type="button" class="tc-no">取消</button></div>';
        var pop = L.popup({ closeButton: true, className: "tour-confirm-pop" })
          .setLatLng([hit.lat, hit.lon]).setContent(html).openOn(map);
        var el = pop.getElement();
        el.querySelector(".tc-yes").addEventListener("click", function () { map.closePopup(pop); addPoint(hit); });
        el.querySelector(".tc-no").addEventListener("click", function () { map.closePopup(pop); });
      });
    });
    bindSearch(); bindCreate();
    try {
      var data = await fetch("/api/tours/globe", { credentials: "same-origin" }).then(function (r) { return r.json(); });
      collections = data.tours || [];
      points = data.points || [];
      mine = data.mine || []; drafts = data.mine || []; published = data.published || [];
      collections.forEach(function (t) {
        var m = {}; (t.categories || []).forEach(function (c) { m[c.id] = c; }); catById[t.slug] = m;
      });
      var pd = await fetch("/api/tours/places", { credentials: "same-origin" }).then(function (r) { return r.json(); });
      places = pd.places || [];
      places.forEach(function (p) {
        placeByKey[pkey(p.level, p.lat, p.lon)] = p;
        if (p.name && !placeByName[p.name]) placeByName[p.name] = p;
      });
    } catch (e) { /* empty */ }
    bindDetail(); bindAddPlace(); bindMyPlaces(); renderList(); renderActive(); setBrowseCollapsed(browseCollapsed); draw();
    // remember the exact collection/stop/view before leaving to a book or author page
    document.addEventListener("click", function (e) {
      var a = e.target && e.target.closest ? e.target.closest('a[href^="/books/"], a[href^="/authors/"]') : null;
      if (a) saveToursState();
    }, true);
    restoreToursState();
    var qs = new URLSearchParams(location.search);
    if (qs.get("book")) openDetail("book", qs.get("book"), false);
    else if (qs.get("author")) openDetail("author", qs.get("author"), false);
    var ep = qs.get("edit_place");
    if (ep) {
      fetch("/api/tours/places/" + encodeURIComponent(ep), { credentials: "same-origin" })
        .then(function (r) { return r.json(); })
        .then(function (place) {
          if (place && window.__folioOpenPlaceForm) window.__folioOpenPlaceForm(place, place.id);
        }).catch(function () {});
    }
  })();
})();
