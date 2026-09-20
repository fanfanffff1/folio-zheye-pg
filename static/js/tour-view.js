/* FOLIO 地图巡礼 — public viewer: markers, route, legend, stats, filters. */
(function () {
  "use strict";
  var dataEl = document.getElementById("tour-data");
  var mapEl = document.getElementById("tour-map");
  if (!dataEl || !mapEl || !window.FolioTour) return;

  var tour = JSON.parse(dataEl.textContent || "{}");
  var FT = window.FolioTour;
  var catById = FT.categoryMap(tour.categories);
  var stops = (tour.stops || []).slice();
  var map, markers = {}, routeLine = null;
  var hiddenRegion = {}, hiddenTag = {};

  function markerFor(stop) {
    var region = catById[stop.category_id] || null;
    var tag = stop.tag_id ? catById[stop.tag_id] : null;
    var m = L.marker([stop.lat, stop.lon], {
      icon: FT.pinIcon(region ? region.color : "#9BB3C9", tag ? tag.color : null),
      riseOnHover: true
    });
    m.bindPopup(FT.popupHtml(stop, region, tag));
    m.addTo(map);
    markers[stop.id] = m;
    return m;
  }

  function isHidden(s) {
    if (s.category_id && hiddenRegion[s.category_id]) return true;
    if (s.tag_id && hiddenTag[s.tag_id]) return true;
    return false;
  }

  function refreshVisibility() {
    stops.forEach(function (s) {
      if (!markers[s.id]) return;
      if (isHidden(s)) map.removeLayer(markers[s.id]); else markers[s.id].addTo(map);
    });
  }

  function legendItem(cat, count, group) {
    var el = document.createElement("button");
    el.type = "button";
    el.className = "tour-legend-item" + (count ? "" : " is-empty");
    el.innerHTML = '<i style="background:' + cat.color + '"></i><span>' + FT.escapeHtml(cat.label) +
      '</span><b>' + count + "</b>";
    el.addEventListener("click", function () {
      var store = group === "tag" ? hiddenTag : hiddenRegion;
      store[cat.id] = !store[cat.id];
      el.classList.toggle("is-off", store[cat.id]);
      refreshVisibility();
    });
    return el;
  }

  function renderLegend() {
    var box = document.getElementById("tour-legend");
    if (!box) return;
    box.innerHTML = "";
    var regionCounts = {}, tagCounts = {};
    stops.forEach(function (s) {
      if (s.category_id) regionCounts[s.category_id] = (regionCounts[s.category_id] || 0) + 1;
      if (s.tag_id) tagCounts[s.tag_id] = (tagCounts[s.tag_id] || 0) + 1;
    });
    var autoCats = (tour.categories || []).filter(function (c) { return c.kind !== "custom"; });
    var customCats = (tour.categories || []).filter(function (c) { return c.kind === "custom"; });
    if (autoCats.length) {
      var h1 = document.createElement("p"); h1.className = "tour-legend-title"; h1.textContent = "地域（自动）";
      box.appendChild(h1);
      autoCats.forEach(function (c) { box.appendChild(legendItem(c, regionCounts[c.id] || 0, "region")); });
    }
    if (customCats.length) {
      var h2 = document.createElement("p"); h2.className = "tour-legend-title"; h2.textContent = "自定义标签";
      box.appendChild(h2);
      customCats.forEach(function (c) { box.appendChild(legendItem(c, tagCounts[c.id] || 0, "tag")); });
    }
  }

  function renderStats() {
    var total = document.getElementById("tour-total");
    if (total) total.textContent = stops.length;
  }

  function renderList() {
    var box = document.getElementById("tour-stop-cards");
    if (!box) return;
    box.innerHTML = "";
    stops.forEach(function (s, i) {
      var region = catById[s.category_id] || { color: "#9BB3C9", label: "" };
      var tag = s.tag_id ? catById[s.tag_id] : null;
      var card = document.createElement("button");
      card.type = "button";
      card.className = "tour-card";
      card.innerHTML =
        '<span class="tour-card-idx" style="--pin:' + region.color + '">' + (i + 1) + "</span>" +
        '<span class="tour-card-body"><strong>' + FT.escapeHtml(s.place_name || s.city || "地点") + "</strong>" +
        '<em>' + FT.escapeHtml([s.city, s.country].filter(Boolean).join(" · ")) + "</em>" +
        (tag ? '<span class="tour-card-tag"><i style="background:' + tag.color + '"></i>' + FT.escapeHtml(tag.label) + "</span>" : "") +
        (s.book_title ? '<span class="tour-card-tag">📖 ' + FT.escapeHtml(s.book_title) + "</span>" : "") +
        ((s.photos && s.photos.length)
          ? '<span class="tour-card-photos">' + s.photos.slice(0, 3).map(function (u) {
              return '<img src="' + FT.escapeHtml(u) + '" alt="" loading="lazy" />';
            }).join("") + "</span>"
          : (s.media_url ? '<img class="tour-card-img" src="' + FT.escapeHtml(s.media_url) + '" alt="" loading="lazy" />' : "")) +
        (s.note ? '<span class="tour-card-note">' + FT.escapeHtml(s.note) + "</span>" : "") +
        "</span>";
      card.addEventListener("click", function () {
        map.flyTo([s.lat, s.lon], Math.max(map.getZoom(), 6));
        if (markers[s.id]) markers[s.id].openPopup();
      });
      box.appendChild(card);
    });
  }

  (async function init() {
    map = await FT.baseMap(mapEl, tour.scope, tour.center ? { lat: tour.center.lat, lon: tour.center.lon, zoom: tour.zoom } : null);
    window.__tourView = map;
    stops.forEach(markerFor);
    routeLine = FT.routeLayer(stops);
    if (routeLine) routeLine.addTo(map);
    renderLegend();
    renderStats();
    renderList();
    if (stops.length) {
      var bounds = L.latLngBounds(stops.map(function (s) { return [s.lat, s.lon]; }));
      map.fitBounds(bounds.pad(0.25), { maxZoom: 6 });
    }
  })();
})();
