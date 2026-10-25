/**
 * AllBAL — Application Frontend JavaScript
 * Méta-annuaire et cartographie interactive des Boîtes à Livres
 */

document.addEventListener("DOMContentLoaded", () => {
  // --- Emplacement par défaut : Domicile CP 31540 (Saint-Julia) ---
  const DEFAULT_LOCATION = {
    lat: 43.490037,
    lon: 1.898538,
    label: "18 Rue du Presbytère, 31540 Saint-Julia",
    radiusKm: 20,
  };

  // --- État de l'application ---
  const state = {
    currentCenter: [DEFAULT_LOCATION.lat, DEFAULT_LOCATION.lon],
    currentRadiusKm: DEFAULT_LOCATION.radiusKm,
    activeMarkerMap: new Map(), // id -> { marker, item }
    searchCircle: null,
    centerMarker: null,
    cachedStats: null,
  };

  // --- Sélecteurs DOM ---
  const mapElement = document.getElementById("map");
  const addressInput = document.getElementById("address-input");
  const clearSearchBtn = document.getElementById("clear-search-btn");
  const autocompleteList = document.getElementById("autocomplete-list");
  const locateBtn = document.getElementById("locate-btn");
  const radiusSelect = document.getElementById("radius-select");
  const exportBtn = document.getElementById("export-btn");
  const filterPhotoCheckbox = document.getElementById("filter-photo");
  const syncOnlineCheckbox = document.getElementById("sync-online");
  const sourceCheckboxes = document.querySelectorAll('input[name="source"]');
  const itemsContainer = document.getElementById("items-container");
  const resultsCountEl = document.getElementById("results-count");
  const resultsPerimeterEl = document.getElementById("results-perimeter");
  const loadingSpinner = document.getElementById("loading-spinner");
  const zoneStatusBanner = document.getElementById("zone-status-banner");
  const photoModal = document.getElementById("photo-modal");
  const modalImg = document.getElementById("modal-img");
  const modalCaption = document.getElementById("modal-caption");
  const modalClose = document.getElementById("modal-close");
  const modalBackdrop = document.getElementById("modal-backdrop");
  const modalSpinner = document.getElementById("modal-spinner");
  const modalSourceLink = document.getElementById("modal-source-link");
  const modalDirectImgLink = document.getElementById("modal-direct-img-link");
  const toggleListBtn = document.getElementById("toggle-list-btn");
  const toggleMapBtn = document.getElementById("toggle-map-btn");
  const mainLayout = document.querySelector(".main-layout");

  // --- 1. Initialisation de la carte Leaflet centrée sur le domicile (31540) ---
  const map = L.map(mapElement, {
    center: [DEFAULT_LOCATION.lat, DEFAULT_LOCATION.lon],
    zoom: 12,
    zoomControl: true,
  });

  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(map);

  const markerClusterGroup = L.markerClusterGroup({
    maxClusterRadius: 45,
    spiderfyOnMaxZoom: true,
    showCoverageOnHover: false,
    zoomToBoundsOnClick: true,
  });
  map.addLayer(markerClusterGroup);

  // Recalcul forcé de la taille Leaflet (indispensable sous Firefox / Flexbox)
  function invalidateMapSize() {
    map.invalidateSize();
  }
  setTimeout(invalidateMapSize, 100);
  setTimeout(invalidateMapSize, 300);

  if (window.ResizeObserver) {
    const ro = new ResizeObserver(() => {
      invalidateMapSize();
    });
    ro.observe(mapElement);
  }

  // --- 2. Initialisation des statistiques globales ---
  async function loadGlobalStats() {
    try {
      const res = await fetch("/api/stats");
      if (!res.ok) return;
      const stats = await res.json();
      state.cachedStats = stats;

      // Mise à jour de la bannière
      document.getElementById("stat-total-bookcases").textContent = stats.total_bookcases.toLocaleString("fr-FR");
      document.getElementById("stat-multi-sources").textContent = stats.multi_source_bookcases.toLocaleString("fr-FR");
      document.getElementById("stat-with-photo").textContent = stats.bookcases_with_photo.toLocaleString("fr-FR");

      // Mise à jour des compteurs individuels par source
      if (stats.raw_by_source) {
        for (const [source, count] of Object.entries(stats.raw_by_source)) {
          const el = document.getElementById(`count-${source}`);
          if (el) {
            el.textContent = `(${count.toLocaleString("fr-FR")})`;
          }
        }
      }
    } catch (err) {
      console.warn("Impossible de charger les statistiques globales :", err);
    }
  }

  // --- 3. Autocomplétion BAN (Base Adresse Nationale) ---
  let debounceTimeout = null;

  addressInput.addEventListener("input", (e) => {
    const query = e.target.value.trim();
    clearSearchBtn.style.display = query.length > 0 ? "block" : "none";

    clearTimeout(debounceTimeout);
    if (query.length < 3) {
      autocompleteList.style.display = "none";
      autocompleteList.innerHTML = "";
      return;
    }

    debounceTimeout = setTimeout(() => {
      fetchBANSuggestions(query);
    }, 280);
  });

  clearSearchBtn.addEventListener("click", () => {
    addressInput.value = "";
    clearSearchBtn.style.display = "none";
    autocompleteList.style.display = "none";
    addressInput.focus();
  });

  async function fetchBANSuggestions(query) {
    try {
      const url = `https://api-adresse.data.gouv.fr/search/?q=${encodeURIComponent(query)}&autocomplete=1&limit=5`;
      const res = await fetch(url);
      if (!res.ok) return;
      const data = await res.json();

      autocompleteList.innerHTML = "";
      if (!data.features || data.features.length === 0) {
        autocompleteList.style.display = "none";
        return;
      }

      data.features.forEach((feat) => {
        const li = document.createElement("li");
        li.className = "autocomplete-item";
        li.innerHTML = `
          <span class="item-label">${escapeHtml(feat.properties.label)}</span>
          <span class="item-context">${escapeHtml(feat.properties.context || "")}</span>
        `;
        li.addEventListener("click", () => {
          const [lon, lat] = feat.geometry.coordinates;
          addressInput.value = feat.properties.label;
          autocompleteList.style.display = "none";
          triggerSearch(lat, lon, feat.properties.label);
        });
        autocompleteList.appendChild(li);
      });

      autocompleteList.style.display = "block";
    } catch (err) {
      console.warn("Erreur autocomplétion BAN :", err);
    }
  }

  // Fermer la liste de suggestions au clic extérieur
  document.addEventListener("click", (e) => {
    if (!addressInput.contains(e.target) && !autocompleteList.contains(e.target)) {
      autocompleteList.style.display = "none";
    }
  });

  // --- 4. Géolocalisation « Autour de moi » ---
  locateBtn.addEventListener("click", () => {
    if (!navigator.geolocation) {
      alert("La géolocalisation n'est pas supportée par votre navigateur.");
      return;
    }

    locateBtn.disabled = true;
    locateBtn.classList.add("loading");
    locateBtn.querySelector("span:last-child").textContent = "Localisation...";

    navigator.geolocation.getCurrentPosition(
      (pos) => {
        locateBtn.disabled = false;
        locateBtn.querySelector("span:last-child").textContent = "Autour de moi";
        const lat = pos.coords.latitude;
        const lon = pos.coords.longitude;
        addressInput.value = `Ma position GPS (${lat.toFixed(4)}, ${lon.toFixed(4)})`;
        clearSearchBtn.style.display = "block";
        triggerSearch(lat, lon, "Ma position");
      },
      (err) => {
        locateBtn.disabled = false;
        locateBtn.querySelector("span:last-child").textContent = "Autour de moi";
        let msg = "Impossible d'obtenir votre position GPS.";
        if (err.code === 1) msg = "Accès à la géolocalisation refusé.";
        else if (err.code === 2) msg = "Position indisponible.";
        else if (err.code === 3) msg = "Délai de géolocalisation dépassé.";
        alert(msg);
      },
      { timeout: 10000, enableHighAccuracy: true }
    );
  });

  // --- 5. Lancement d'une recherche par périmètre ---
  radiusSelect.addEventListener("change", () => {
    state.currentRadiusKm = parseFloat(radiusSelect.value);
    if (state.currentCenter) {
      triggerSearch(state.currentCenter[0], state.currentCenter[1]);
    }
  });

  filterPhotoCheckbox.addEventListener("change", () => {
    if (state.currentCenter) {
      triggerSearch(state.currentCenter[0], state.currentCenter[1]);
    }
  });

  sourceCheckboxes.forEach((cb) => {
    cb.addEventListener("change", () => {
      if (state.currentCenter) {
        triggerSearch(state.currentCenter[0], state.currentCenter[1]);
      }
    });
  });

  function getSelectedSources() {
    return Array.from(sourceCheckboxes)
      .filter((cb) => cb.checked)
      .map((cb) => cb.value);
  }

  async function triggerSearch(lat, lon, locationLabel = "") {
    state.currentCenter = [lat, lon];
    state.currentRadiusKm = parseFloat(radiusSelect.value);

    loadingSpinner.style.display = "inline-block";
    zoneStatusBanner.style.display = "none";

    const sources = getSelectedSources();
    const hasPhoto = filterPhotoCheckbox.checked;
    const syncOnline = syncOnlineCheckbox.checked;

    // Construction de l'URL
    const params = new URLSearchParams({
      lat: lat.toString(),
      lon: lon.toString(),
      radius_km: state.currentRadiusKm.toString(),
      sync: syncOnline ? "true" : "false",
      limit: "500",
    });

    if (sources.length > 0) {
      params.set("sources", sources.join(","));
    }
    if (hasPhoto) {
      params.set("has_photo", "true");
    }

    try {
      const res = await fetch(`/api/bookcases?${params.toString()}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();

      renderResults(data, locationLabel);
    } catch (err) {
      console.error("Erreur lors de la recherche :", err);
      itemsContainer.innerHTML = `
        <div class="empty-state">
          <div class="empty-icon">⚠️</div>
          <h3>Erreur de recherche</h3>
          <p>Impossible de récupérer les boîtes à livres pour cette zone. Vérifiez que le serveur est bien démarré.</p>
        </div>
      `;
      resultsCountEl.textContent = "Erreur de chargement";
    } finally {
      loadingSpinner.style.display = "none";
    }
  }

  // --- 6. Rendu des résultats (Carte + Liste) ---
  function renderResults(data, locationLabel) {
    const { count, center, radius_km, zone_cached, items } = data;

    // Mise à jour de l'en-tête de résultats
    resultsCountEl.textContent = `${count} boîte${count > 1 ? "s" : ""} trouvée${count > 1 ? "s" : ""}`;
    resultsPerimeterEl.textContent = `dans un rayon de ${radius_km} km`;

    // Notification Fair-Use / Cache
    if (!zone_cached && syncOnlineCheckbox.checked) {
      zoneStatusBanner.style.display = "flex";
      zoneStatusBanner.innerHTML = `<span>⚡</span> Zone synchronisée en direct avec les sources distantes (fair-use).`;
    } else {
      zoneStatusBanner.style.display = "none";
    }

    // Réinitialisation de la carte
    markerClusterGroup.clearLayers();
    state.activeMarkerMap.clear();

    if (state.searchCircle) {
      map.removeLayer(state.searchCircle);
    }
    if (state.centerMarker) {
      map.removeLayer(state.centerMarker);
    }

    // Dessin du périmètre circulaire
    state.searchCircle = L.circle([center.lat, center.lon], {
      radius: radius_km * 1000,
      color: "#2563eb",
      fillColor: "#3b82f6",
      fillOpacity: 0.08,
      weight: 2,
      dashArray: "5, 5",
    }).addTo(map);

    // Marqueur du centre de recherche
    const centerIcon = L.divIcon({
      className: "center-search-icon",
      html: `<div style="background-color:#ef4444; width:16px; height:16px; border-radius:50%; border:3px solid #fff; box-shadow:0 0 6px rgba(0,0,0,0.5);"></div>`,
      iconSize: [16, 16],
      iconAnchor: [8, 8],
    });
    state.centerMarker = L.marker([center.lat, center.lon], { icon: centerIcon, title: locationLabel || "Centre de recherche" }).addTo(map);

    // Zoom adapté au rayon avec invalidation de taille garantie
    invalidateMapSize();
    map.fitBounds(state.searchCircle.getBounds(), { padding: [30, 30] });
    setTimeout(invalidateMapSize, 100);

    // Vider le conteneur de liste
    itemsContainer.innerHTML = "";

    if (items.length === 0) {
      itemsContainer.innerHTML = `
        <div class="empty-state">
          <div class="empty-icon">🔍</div>
          <h3>Aucune boîte trouvée</h3>
          <p>Aucune boîte à livres dans ce rayon de ${radius_km} km. Essayez d'élargir le rayon à 20 ou 50 km, ou réactivez toutes les sources.</p>
        </div>
      `;
      return;
    }

    // Création des marqueurs et des cartes
    items.forEach((item) => {
      const isMulti = item.source_count > 1;

      // Marqueur Leaflet personnalisé
      const markerIcon = L.divIcon({
        className: "custom-marker-wrapper",
        html: `<div class="custom-pin ${isMulti ? "multi" : "single"}" title="${isMulti ? "Confirmée par " + item.source_count + " sources" : "Source unique"}">
                <span>${isMulti ? "★" : "📖"}</span>
               </div>`,
        iconSize: [28, 28],
        iconAnchor: [14, 14],
        popupAnchor: [0, -14],
      });

      const marker = L.marker([item.lat, item.lon], { icon: markerIcon });
      const popupContent = createPopupHtml(item);
      marker.bindPopup(popupContent, { maxWidth: 320 });

      markerClusterGroup.addLayer(marker);
      state.activeMarkerMap.set(item.id, { marker, item });

      // Carte latérale
      const card = createCardElement(item);
      card.addEventListener("click", () => {
        // Enlever la sélection précédente
        document.querySelectorAll(".bookcase-card.active").forEach((c) => c.classList.remove("active"));
        card.classList.add("active");

        // Centrer et ouvrir le popup
        markerClusterGroup.zoomToShowLayer(marker, () => {
          marker.openPopup();
        });

        // Sur mobile, basculer sur la carte automatiquement
        if (window.innerWidth <= 860) {
          showMapMobile();
        }
      });

      itemsContainer.appendChild(card);
    });
  }

  // --- 7. Création du HTML Popup et Cartes ---
  function createPopupHtml(item) {
    const isMulti = item.source_count > 1;
    const distanceFormatted = formatDistance(item.distance_m);
    const sourcesBadges = (item.sources_list || [])
      .map((s) => `<span class="source-badge badge-${escapeHtml(s)}">${escapeHtml(formatSourceName(s))}</span>`)
      .join(" ");

    const safePhotoUrl = sanitizeUrl(item.photo_url || "");
    const hasPhoto = Boolean(safePhotoUrl);
    const photoUrl = safePhotoUrl;
    const pageUrlEncoded = encodeURIComponent(sanitizeUrl(item.photo_source_url || item.source_url || ""));
    const titleEncoded = encodeURIComponent(item.title || item.address || "");
    const photoUrlEncoded = encodeURIComponent(photoUrl);

    const photoHtml = hasPhoto
      ? `<div class="popup-photo-container" onclick="window.allbalOpenPhoto('${photoUrlEncoded}', '${titleEncoded}', '${pageUrlEncoded}')" title="Cliquer pour voir la photo en grand">
           <img src="${escapeHtml(photoUrl)}" alt="Photo de ${escapeHtml(item.title || "boîte")}" class="popup-photo" loading="lazy" onerror="this.parentElement.style.display='none'" />
           <div class="popup-photo-overlay">🔍 Agrandir</div>
         </div>`
      : "";

    const descHtml = item.description ? `<p class="card-desc">${escapeHtml(item.description)}</p>` : "";
    const statusHtml = item.status ? `<div style="font-size:0.75rem; color:#b45309; font-weight:600; margin:0.2rem 0;">État : ${escapeHtml(item.status)}</div>` : "";

    const navUrl = `https://www.google.com/maps/dir/?api=1&destination=${item.lat},${item.lon}`;

    return `
      <div class="popup-header">
        <div class="popup-title">${escapeHtml(item.title || "Boîte à Livres")}</div>
        <div class="popup-address">${escapeHtml([item.address, item.postcode, item.city].filter(Boolean).join(", "))}</div>
        <span class="popup-distance">${distanceFormatted}</span>
      </div>
      ${photoHtml}
      ${descHtml}
      ${statusHtml}
      <div class="popup-badges">
        ${isMulti ? `<span class="multi-badge">★ Recoupée (${item.source_count} sources)</span>` : ""}
        ${sourcesBadges}
      </div>
      <div class="popup-footer">
        <a href="${navUrl}" target="_blank" rel="noopener noreferrer" class="btn-itinerary">🧭 Y aller</a>
        ${hasPhoto ? `<button type="button" class="btn-photo-popup" onclick="window.allbalOpenPhoto('${photoUrlEncoded}', '${titleEncoded}', '${pageUrlEncoded}')">📷 Photo en grand</button>` : ""}
      </div>
    `;
  }

  function createCardElement(item) {
    const card = document.createElement("div");
    card.className = "bookcase-card";
    card.id = `card-${item.id}`;

    const isMulti = item.source_count > 1;
    const distanceFormatted = formatDistance(item.distance_m);
    const sourcesBadges = (item.sources_list || [])
      .map((s) => `<span class="source-badge badge-${escapeHtml(s)}">${escapeHtml(formatSourceName(s))}</span>`)
      .join(" ");

    const safePhotoUrl = sanitizeUrl(item.photo_url || "");
    const pageUrlEncoded = encodeURIComponent(sanitizeUrl(item.photo_source_url || item.source_url || ""));
    const photoThumb = safePhotoUrl
      ? `<img src="${escapeHtml(safePhotoUrl)}" alt="Miniature" class="card-thumbnail" title="Cliquer pour agrandir" loading="lazy" onerror="this.style.display='none'" onclick="event.stopPropagation(); window.allbalOpenPhoto('${encodeURIComponent(safePhotoUrl)}', '${encodeURIComponent(item.title || item.address || "")}', '${pageUrlEncoded}')" />`
      : "";

    const addressLine = [item.address, item.postcode, item.city].filter(Boolean).join(", ") || "Emplacement non précisé";
    const descLine = item.description ? `<div class="card-desc">${escapeHtml(item.description)}</div>` : "";

    card.innerHTML = `
      <div class="card-top">
        <div class="card-title">${escapeHtml(item.title || "Boîte à Livres")}</div>
        <span class="card-distance">${distanceFormatted}</span>
      </div>
      <div class="card-address">${escapeHtml(addressLine)}</div>
      ${descLine}
      <div class="card-bottom">
        <div class="card-sources">
          ${isMulti ? `<span class="multi-badge">★ ${item.source_count} sources</span>` : ""}
          ${sourcesBadges}
        </div>
        <div class="card-actions">
          ${photoThumb}
        </div>
      </div>
    `;

    return card;
  }

  // --- 8. Export GeoJSON ---
  exportBtn.addEventListener("click", () => {
    let url = "/api/export.geojson";
    if (state.currentCenter) {
      const [lat, lon] = state.currentCenter;
      url += `?lat=${lat}&lon=${lon}&radius_km=${state.currentRadiusKm}`;
    }
    window.location.href = url;
  });

  // --- 9. Modal Photo ---
  window.allbalOpenPhoto = (encodedUrl, encodedTitle, encodedPageUrl = "") => {
    const url = sanitizeUrl(decodeURIComponent(encodedUrl));
    const title = decodeURIComponent(encodedTitle);
    const pageUrl = encodedPageUrl ? sanitizeUrl(decodeURIComponent(encodedPageUrl)) : "";
    if (!url) return;

    modalImg.style.display = "none";
    if (modalSpinner) modalSpinner.style.display = "block";
    modalCaption.textContent = title;

    if (modalDirectImgLink) {
      modalDirectImgLink.href = url;
      modalDirectImgLink.style.display = "inline-flex";
    }

    if (modalSourceLink) {
      if (pageUrl) {
        modalSourceLink.href = pageUrl;
        modalSourceLink.style.display = "inline-flex";
      } else {
        modalSourceLink.style.display = "none";
      }
    }

    modalImg.src = url;
    photoModal.style.display = "flex";

    // Clic sur l'image elle-même : ouverture de l'image en pleine résolution dans un nouvel onglet
    modalImg.onclick = () => {
      window.open(url, "_blank");
    };

    modalImg.onload = () => {
      if (modalSpinner) modalSpinner.style.display = "none";
      modalImg.style.display = "block";
    };
    modalImg.onerror = () => {
      if (modalSpinner) modalSpinner.style.display = "none";
      modalCaption.textContent = `${title} — (Image indisponible ou en cours de chargement)`;
    };
  };

  function closePhotoModal() {
    photoModal.style.display = "none";
    modalImg.src = "";
    modalImg.onclick = null;
    if (modalSpinner) modalSpinner.style.display = "none";
  }

  modalClose.addEventListener("click", closePhotoModal);
  modalBackdrop.addEventListener("click", closePhotoModal);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && photoModal.style.display === "flex") {
      closePhotoModal();
    }
  });

  // --- 10. Bascule Mobile (Carte / Liste) ---
  function showMapMobile() {
    mainLayout.classList.remove("show-list");
    mainLayout.classList.add("show-map");
    toggleMapBtn.classList.add("active");
    toggleListBtn.classList.remove("active");
    setTimeout(invalidateMapSize, 100);
  }

  function showListMobile() {
    mainLayout.classList.add("show-list");
    mainLayout.classList.remove("show-map");
    toggleListBtn.classList.add("active");
    toggleMapBtn.classList.remove("active");
  }

  toggleMapBtn.addEventListener("click", showMapMobile);
  toggleListBtn.addEventListener("click", showListMobile);

  // --- Utilitaires ---
  function formatDistance(meters) {
    if (meters === undefined || meters === null) return "";
    if (meters < 1000) {
      return `${Math.round(meters)} m`;
    }
    return `${(meters / 1000).toFixed(1).replace(".", ",")} km`;
  }

  function formatSourceName(source) {
    const map = {
      osm: "OSM",
      boites_a_livres_fr: "OSM / Boîtes-à-livres.fr",
      zonelivre: "ZoneLivre",
      lebouquinfrancais: "Le Bouquin Français",
      boitesalivres_com: "Boîtes-à-livres.com",
      nonmarchand: "Non-Marchand",
    };
    return map[source] || source;
  }

  function sanitizeUrl(url) {
    if (!url) return "";
    const trimmed = String(url).trim();
    if (
      trimmed.startsWith("https://") ||
      trimmed.startsWith("http://") ||
      (trimmed.startsWith("/") && !trimmed.startsWith("//"))
    ) {
      return trimmed;
    }
    return "";
  }

  function escapeHtml(str) {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  // Lancement du chargement des statistiques et de la recherche par défaut sur le domicile (31540)
  loadGlobalStats();
  triggerSearch(DEFAULT_LOCATION.lat, DEFAULT_LOCATION.lon, DEFAULT_LOCATION.label);
});
