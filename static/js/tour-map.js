/* FOLIO 地图巡礼 — shared Leaflet base map, markers, gazetteer.
 * world = Natural Earth (WGS-84) / china = DataV (GCJ-02). Never mix. */
(function () {
  "use strict";

  function metaContent(name) {
    var el = document.querySelector('meta[name="' + name + '"]');
    return el ? (el.getAttribute("content") || "").trim() : "";
  }
  // Optional CDN origin for map assets (R2 + Cloudflare). Falls back to local static.
  var MAP_CDN = metaContent("folio-map-cdn").replace(/\/$/, "");
  var MAP_PMTILES = metaContent("folio-map-pmtiles");
  function asset(p) {
    return MAP_CDN ? (MAP_CDN + "/tour-map" + p) : ("/static/data/tour-map" + p);
  }

  var DATA = {
    world: {
      countries: asset("/world/countries.geojson"),
      admin1: asset("/world/admin1.geojson"),
      places: asset("/world/places.geojson"),
      countryIndex: asset("/world/country-index.json"),
      regionIndex: asset("/world/region-index.json"),
      regionAliases: asset("/world/region-aliases.json"),
      chinaPlaces: asset("/world/china-places.json"),
      antarcticaPlaces: asset("/world/antarctica-places.json"),
      minZoom: 2, maxZoom: 9, center: [22, 8], zoom: 2
    },
    china: {
      provinces: asset("/china/provinces.geojson"),
      cityIndex: asset("/china/city-index.json"),
      citiesDir: asset("/china/cities/"),
      minZoom: 3, maxZoom: 9, center: [35, 104], zoom: 4
    }
  };

  // Bump when tour-map data files change (static data gets a 1-day cache).
  var DATA_VERSION = "20260925h";

  var cache = {};
  function loadJSON(url) {
    var u = url + (url.indexOf("?") < 0 ? "?" : "&") + "v=" + DATA_VERSION;
    if (!cache[u]) {
      cache[u] = fetch(u, { credentials: "same-origin" }).then(function (r) {
        if (!r.ok) throw new Error(url + " -> " + r.status);
        return r.json();
      });
    }
    return cache[u];
  }

  var pmtilesReady = null;
  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      var s = document.createElement("script");
      s.src = src; s.async = true;
      s.onload = function () { resolve(); };
      s.onerror = function () { reject(new Error(src)); };
      document.head.appendChild(s);
    });
  }
  function ensurePmtiles() {
    if (window.protomapsL) return Promise.resolve(true);
    if (!pmtilesReady) {
      pmtilesReady = loadScript("/static/vendor/pmtiles/pmtiles.js")
        .then(function () { return loadScript("/static/vendor/pmtiles/protomaps-leaflet.js"); })
        .then(function () { return !!window.protomapsL; })
        .catch(function () { return false; });
    }
    return pmtilesReady;
  }

  function haversine(aLat, aLon, bLat, bLon) {
    var R = 6371, dLat = (bLat - aLat) * Math.PI / 180, dLon = (bLon - aLon) * Math.PI / 180;
    var s = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
      Math.cos(aLat * Math.PI / 180) * Math.cos(bLat * Math.PI / 180) *
      Math.sin(dLon / 2) * Math.sin(dLon / 2);
    return 2 * R * Math.asin(Math.min(1, Math.sqrt(s)));
  }

  function pinIcon(color, ring, active, level) {
    return L.divIcon({
      className: "tour-pin tour-pin-" + (level || "city") + (active ? " is-active" : ""),
      html: '<span class="tour-pin-dot" style="--pin:' + color + ';--ring:' + (ring || "#fff") + '"></span>',
      iconSize: [22, 22], iconAnchor: [11, 11], popupAnchor: [0, -12]
    });
  }

  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  var LEVEL_LABEL = { country: "国家", region: "地区", city: "城市" };

  function popupHtml(stop, cat, tag) {
    var bits = ['<div class="tour-pop">'];
    var level = stop.level || "city";
    bits.push("<h4>" + escapeHtml(stop.place_name || stop.city || "地点") +
      ' <span class="tour-level-badge">' + (LEVEL_LABEL[level] || "") + "</span></h4>");
    var meta;
    if (level === "country") meta = stop.country || "";
    else if (level === "region") meta = [stop.admin1, stop.country].filter(Boolean).join(" · ");
    else meta = [stop.city, stop.admin1, stop.country].filter(Boolean).join(" · ");
    if (meta) bits.push('<p class="tour-pop-meta">' + escapeHtml(meta) + "</p>");
    if (stop.period) bits.push('<p class="tour-pop-meta">' + escapeHtml(stop.period) + "</p>");
    if (cat) bits.push('<p class="tour-pop-cat"><i style="background:' + cat.color + '"></i>' + escapeHtml(cat.label) + "</p>");
    if (tag) bits.push('<p class="tour-pop-cat"><i style="background:' + tag.color + '"></i>' + escapeHtml(tag.label) + "</p>");
    var photos = (stop.photos && stop.photos.length) ? stop.photos : (stop.media_url ? [stop.media_url] : []);
    if (photos.length) {
      bits.push('<div class="tour-pop-photos">' + photos.slice(0, 4).map(function (u) {
        return '<img src="' + escapeHtml(u) + '" alt="" loading="lazy" />';
      }).join("") + "</div>");
    }
    if (stop.book_id && stop.book_title) {
      bits.push('<p class="tour-pop-book"><a href="/books/' + escapeHtml(stop.book_slug || "") + '">📖 ' +
        escapeHtml(stop.book_title) + "</a></p>");
    }
    if (stop.note) bits.push('<p class="tour-pop-note">' + escapeHtml(stop.note) + "</p>");
    bits.push("</div>");
    return bits.join("");
  }

  // Street-level tiles kick in past TILE_MIN_ZOOM; below that the custom
  // GeoJSON basemap is shown (keeps the literary look at overview zooms).
  var TILE_MIN_ZOOM = 8;
  var TILE_URL = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";
  var TILE_ATTR = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
  // pale base shown at low zoom so the jump to street tiles is smoother
  var LOW_TILE_URL = "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}";
  var LOW_TILE_ATTR = "Tiles &copy; Esri";
  // terrain relief overlay: gives shape to sparse regions (Greenland, Antarctica)
  var HILLSHADE_URL = "https://server.arcgisonline.com/ArcGIS/rest/services/Elevation/World_Hillshade/MapServer/tile/{z}/{y}/{x}";
  var HILLSHADE_ATTR = "Hillshade &copy; Esri";

  async function baseMap(el, scope, view) {
    var cfg = DATA[scope] || DATA.world;
    var map = L.map(el, {
      zoomControl: true,
      attributionControl: true,
      minZoom: cfg.minZoom,
      maxZoom: 19,
      maxBounds: [[-85.0511, -180], [85.0511, 180]],
      maxBoundsViscosity: 0.7,
      worldCopyJump: false,
      preferCanvas: true
    });
    var lat = view && view.lat != null ? view.lat : cfg.center[0];
    var lon = view && view.lon != null ? view.lon : cfg.center[1];
    var z = view && view.zoom != null ? view.zoom : cfg.zoom;
    map.setView([lat, lon], z);

    var baseGroup = L.layerGroup();
    var lowTiles = L.tileLayer(LOW_TILE_URL, {
      minZoom: cfg.minZoom, maxZoom: TILE_MIN_ZOOM - 1,
      attribution: LOW_TILE_ATTR, opacity: 0.9
    });
    // Prefer self-hosted PMTiles (single file + Range, served from R2/CDN).
    function osmFallback() {
      return L.tileLayer(TILE_URL, {
        subdomains: "abc", minZoom: TILE_MIN_ZOOM, maxZoom: 19,
        attribution: TILE_ATTR, detectRetina: true
      });
    }
    var highLayer = null;
    if (MAP_PMTILES && await ensurePmtiles()) {
      // validate the PMTiles file is reachable before committing to it
      var reachable = false;
      try {
        var head = await fetch(MAP_PMTILES, { headers: { Range: "bytes=0-15" } });
        reachable = head.ok || head.status === 206;
      } catch (e) { reachable = false; }
      if (reachable) {
        try {
          highLayer = protomapsL.leafletLayer({
            url: MAP_PMTILES, flavor: "light", lang: "zh",
            minZoom: TILE_MIN_ZOOM, maxZoom: 19, attribution: TILE_ATTR
          });
          highLayer.on("tileerror", function () {
            var wasOn = map.hasLayer(highLayer);
            if (wasOn) map.removeLayer(highLayer);
            highLayer = osmFallback();
            if (wasOn) highLayer.addTo(map);
          });
        } catch (e) { highLayer = null; }
      }
    }
    if (!highLayer) highLayer = osmFallback();
    // relief overlay (above tiles, below markers) for terrain in sparse areas
    map.createPane("hillshade");
    var hPane = map.getPane("hillshade");
    hPane.style.zIndex = 250;
    hPane.style.mixBlendMode = "multiply";
    hPane.style.pointerEvents = "none";
    var hillshade = L.tileLayer(HILLSHADE_URL, {
      pane: "hillshade", opacity: 0.45, minZoom: TILE_MIN_ZOOM, maxZoom: 16,
      attribution: HILLSHADE_ATTR
    });

    if (scope === "china") await chinaBase(map, baseGroup);
    else await worldBase(map, baseGroup);
    baseGroup.addTo(map);

    function syncBase() {
      if (map.getZoom() >= TILE_MIN_ZOOM) {
        if (map.hasLayer(baseGroup)) map.removeLayer(baseGroup);
        if (map.hasLayer(lowTiles)) map.removeLayer(lowTiles);
        if (!map.hasLayer(highLayer)) highLayer.addTo(map);
        if (!map.hasLayer(hillshade)) hillshade.addTo(map);
      } else {
        if (map.hasLayer(highLayer)) map.removeLayer(highLayer);
        if (map.hasLayer(hillshade)) map.removeLayer(hillshade);
        if (!map.hasLayer(lowTiles)) lowTiles.addTo(map);
        if (!map.hasLayer(baseGroup)) baseGroup.addTo(map);
      }
    }
    map.on("zoomend", syncBase);
    syncBase();
    return map;
  }

  async function worldBase(map, baseGroup) {
    var countries = await loadJSON(DATA.world.countries);
    L.geoJSON(countries, {
      interactive: false,
      style: { color: "#d9d3c4", weight: 0.7, fillColor: "#f5f1e6", fillOpacity: 1 }
    }).addTo(baseGroup);

    var admin1 = await loadJSON(DATA.world.admin1);
    L.geoJSON(admin1, {
      interactive: false,
      style: { color: "#e7e1d2", weight: 0.4, fillOpacity: 0 }
    }).addTo(baseGroup);

    var labelEntries = [];
    countries.features.forEach(function (f) {
      var p = f.properties || {};
      if (p.LABEL_HIDDEN) return;
      if (p.LABEL_X == null || p.LABEL_Y == null) return;
      var text = p.NAME_ZH || p.NAME || "";
      if (!text) return;
      labelEntries.push({
        p: p,
        m: L.marker([p.LABEL_Y, p.LABEL_X], {
          interactive: false,
          icon: L.divIcon({ className: "tour-country-label", html: escapeHtml(text), iconSize: null })
        })
      });
    });
    var labels = L.layerGroup().addTo(baseGroup);
    function labelVisible(p, z) {
      var minz = p.MIN_ZOOM || 0, maxz = p.MAX_LABEL || 10, rank = p.LABELRANK || 6;
      if (z < minz || z > maxz) return false;
      if (z <= 2) return rank <= 2;
      if (z <= 3) return rank <= 3;
      if (z <= 4) return rank <= 5;
      return true;
    }
    function syncLabels(z) {
      labelEntries.forEach(function (e) {
        var show = labelVisible(e.p, z), has = labels.hasLayer(e.m);
        if (show && !has) labels.addLayer(e.m);
        else if (!show && has) labels.removeLayer(e.m);
      });
    }

    var places = await loadJSON(DATA.world.places);
    var placeLayer = L.layerGroup();
    places.features.forEach(function (f) {
      var c = f.geometry && f.geometry.coordinates;
      if (!c) return;
      L.circleMarker([c[1], c[0]], {
        radius: 2.1, color: "#c3bcab", weight: 1, fillColor: "#d6cfbf", fillOpacity: 0.85, interactive: false
      }).addTo(placeLayer);
    });

    function sync() {
      var z = map.getZoom();
      syncLabels(z);
      if (z >= 6) { if (!baseGroup.hasLayer(placeLayer)) placeLayer.addTo(baseGroup); }
      else if (baseGroup.hasLayer(placeLayer)) baseGroup.removeLayer(placeLayer);
    }
    map.on("zoomend", sync);
    sync();
  }

  async function chinaBase(map, baseGroup) {
    var provinces = await loadJSON(DATA.china.provinces);
    var cityLayers = {};
    var provLayer = L.geoJSON(provinces, {
      interactive: false,
      style: { color: "#d9d3c4", weight: 0.8, fillColor: "#f5f1e6", fillOpacity: 1 },
      onEachFeature: function (f, layer) { layer.__adcode = f.properties && f.properties.adcode; }
    }).addTo(baseGroup);
    async function loadCities(adcode) {
      if (!adcode || cityLayers[adcode]) return;
      cityLayers[adcode] = true;
      try {
        var data = await loadJSON(DATA.china.citiesDir + adcode + ".geojson");
        L.geoJSON(data, { interactive: false, style: { color: "#e7e1d2", weight: 0.6, fillOpacity: 0 } }).addTo(baseGroup);
      } catch (e) { cityLayers[adcode] = false; }
    }
    function sync() {
      if (map.getZoom() < 7) return;
      var c = map.getCenter();
      provLayer.eachLayer(function (l) { if (l.getBounds && l.getBounds().contains(c)) loadCities(l.__adcode); });
    }
    map.on("moveend", sync);
    sync();
  }

  async function gazetteer(scope) {
    if (scope === "china") {
      var prov = await loadJSON(DATA.china.provinces);
      var idx = await loadJSON(DATA.china.cityIndex);
      var out = [{ level: "country", name: "中国", nameZh: "中国", nameEn: "China", country: "中国", lat: 35, lon: 104 }];
      (prov.features || []).forEach(function (f) {
        var p = f.properties || {};
        var c = p.center || p.centroid || [0, 0];
        if (!c[0] || !c[1]) return;
        out.push({ level: "region", name: p.name, nameZh: p.name, nameEn: "", admin1: p.name, country: "中国", lat: c[1], lon: c[0] });
      });
      idx.forEach(function (x) {
        var c = x.center || [0, 0];
        if (!c[0] || !c[1]) return;
        out.push({ level: "city", name: x.name, nameZh: x.name, nameEn: "", admin1: x.province || "", country: "中国", lat: c[1], lon: c[0] });
      });
      return out;
    }
    var res = await Promise.all([
      loadJSON(DATA.world.countryIndex),
      loadJSON(DATA.world.regionIndex),
      loadJSON(DATA.world.places),
      loadJSON(DATA.world.regionAliases).catch(function () { return []; }),
      loadJSON(DATA.world.chinaPlaces).catch(function () { return []; }),
      loadJSON(DATA.world.antarcticaPlaces).catch(function () { return []; })
    ]);
    var countries = res[0], regions = res[1], places = res[2], aliases = res[3], chinaPlaces = res[4], antarctica = res[5];
    var out = [];
    (countries || []).forEach(function (c) {
      out.push({ level: "country", name: c.nameZh || c.name, nameZh: c.nameZh || "", nameEn: c.name || "", country: c.name || "", lat: c.lat, lon: c.lon });
    });
    (regions || []).forEach(function (r) {
      out.push({
        level: "region", name: r.nameZh || r.name, nameZh: r.nameZh || "", nameEn: r.nameEn || r.name || "",
        admin1: r.name || "", country: r.admin || "", lat: r.lat, lon: r.lon
      });
    });
    (places.features || []).forEach(function (f) {
      var p = f.properties || {};
      out.push({
        level: "city", name: p.NAME_ZH || p.NAME, nameZh: p.NAME_ZH || "", nameEn: p.NAME || "",
        admin1: p.ADM1NAME || "", country: p.ADM0NAME || "", lat: +p.LATITUDE, lon: +p.LONGITUDE,
        pop: +p.POP_MAX || 0
      });
    });
    (aliases || []).forEach(function (a) {
      (a.aliases || []).forEach(function (al) {
        out.push({
          level: "region", name: a.nameZh || a.name, nameZh: a.nameZh || "", nameEn: a.name || "",
          alias: al, admin1: a.name || "", country: a.admin || "", lat: a.lat, lon: a.lon
        });
      });
    });
    // Taiwan / Hong Kong / Macao and China's islands are regions of China.
    (chinaPlaces || []).forEach(function (a) {
      (a.aliases || []).forEach(function (al) {
        out.push({
          level: "region", name: a.nameZh || a.name, nameZh: a.nameZh || "", nameEn: a.name || "",
          alias: al, admin1: "", country: "China", lat: a.lat, lon: a.lon
        });
      });
    });
    // Antarctica research stations / expedition sites (sparse OSM detail there).
    (antarctica || []).forEach(function (a) {
      out.push({
        level: "city", name: a.nameZh || a.name, nameZh: a.nameZh || "", nameEn: a.nameEn || a.name || "",
        admin1: "", country: "南极洲", lat: a.lat, lon: a.lon
      });
    });
    return out.filter(function (x) {
      return x.lat != null && x.lon != null && !isNaN(x.lat) && !isNaN(x.lon);
    });
  }

  function nearest(list, lat, lon, maxKm) {
    var best = null, bestD = Infinity;
    for (var i = 0; i < list.length; i++) {
      var d = haversine(lat, lon, list[i].lat, list[i].lon);
      if (d < bestD) { bestD = d; best = list[i]; }
    }
    if (best && bestD <= maxKm) { best.distance = bestD; return best; }
    return null;
  }

  var LEVEL_RANK = { country: 0, region: 1, city: 2 };
  function normPlaceName(n) {
    return String(n || "").replace(/(特别行政区|自治区|自治州|市|省|区|县|盟|地区)$/, "").trim();
  }

  function search(list, q, limit, level) {
    q = (q || "").trim().toLowerCase();
    if (!q) return [];
    var seen = {}, out = [];
    for (var i = 0; i < list.length; i++) {
      var it = list[i];
      if (level && it.level !== level) continue;
      var hay = (it.name || "") + "|" + (it.nameZh || "") + "|" + (it.nameEn || "") + "|" + (it.alias || "");
      if (hay.toLowerCase().indexOf(q) === -1) continue;
      var key = (it.level || "") + "|" + Math.round((it.lat || 0) * 50) + "," + Math.round((it.lon || 0) * 50);
      if (seen[key]) continue;
      seen[key] = 1;
      out.push(it);
    }
    // A city and its admin-1 region share a name (北京 / 北京市): keep the city.
    var byName = {};
    out.forEach(function (it) {
      var nk = normPlaceName(it.name) + "|" + (it.country || "");
      var cur = byName[nk];
      if (!cur || (LEVEL_RANK[it.level] || 3) > (LEVEL_RANK[cur.level] || 3)) byName[nk] = it;
    });
    out = out.filter(function (it) { return byName[normPlaceName(it.name) + "|" + (it.country || "")] === it; });
    out.sort(function (a, b) {
      var r = (LEVEL_RANK[a.level] || 3) - (LEVEL_RANK[b.level] || 3);
      if (r) return r;
      return (b.pop || 0) - (a.pop || 0);
    });
    return out.slice(0, limit || 20);
  }

  function categoryMap(cats) {
    var m = {};
    (cats || []).forEach(function (c) { m[c.id] = c; });
    return m;
  }

  // 足迹连线：按顺序连接所有点
  function routeLayer(stops, opts) {
    opts = opts || {};
    var pts = (stops || []).filter(function (s) { return s.lat != null && s.lon != null; })
      .map(function (s) { return [s.lat, s.lon]; });
    if (pts.length < 2) return null;
    return L.polyline(pts, {
      color: opts.color || "#c5a35a",
      weight: opts.weight || 2,
      opacity: opts.opacity || 0.75,
      dashArray: opts.dashArray || "3 7",
      lineJoin: "round",
      interactive: false
    });
  }

  var KIND_META = {
    author: { label: "作者", color: "#8FA9C9" },
    book: { label: "书籍", color: "#9BBE9A" },
    region: { label: "地域", color: "#D2A06E" },
    genre: { label: "流派", color: "#C98AA0" },
    custom: { label: "自定义", color: "#B0A6C0" }
  };
  function kindBadge(kind) {
    var m = KIND_META[kind] || KIND_META.custom;
    return '<span class="tour-kind-badge" style="--kc:' + m.color + '">' + m.label + "</span>";
  }

  window.FolioTour = {
    DATA: DATA,
    kindBadge: kindBadge,
    KIND_META: KIND_META,
    baseMap: baseMap,
    gazetteer: gazetteer,
    nearest: nearest,
    search: search,
    haversine: haversine,
    pinIcon: pinIcon,
    popupHtml: popupHtml,
    escapeHtml: escapeHtml,
    categoryMap: categoryMap,
    routeLayer: routeLayer
  };
})();
