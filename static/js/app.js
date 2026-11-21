/* Vatel Smart Canteen — Interactions client & États de chargement UX/UI CSP-safe */
(function () {
  "use strict";

  document.addEventListener("DOMContentLoaded", function () {
    var topLoader = document.getElementById("vsc-top-loader");

    var startTopLoader = function () {
      if (!topLoader) return;
      topLoader.classList.remove("is-active");
      void topLoader.offsetWidth;
      topLoader.classList.add("is-active");
    };

    var stopTopLoader = function () {
      if (!topLoader) return;
      topLoader.style.width = "100%";
      setTimeout(function () {
        topLoader.classList.remove("is-active");
        topLoader.style.width = "0%";
      }, 220);
    };

    /* 1. Barre de progression supérieure sur navigation interne & requêtes HTMX */
    document.addEventListener("click", function (ev) {
      var link = ev.target.closest("a[href]");
      if (!link) return;
      var href = link.getAttribute("href") || "";
      if (
        href.startsWith("/") &&
        !href.startsWith("//") &&
        !link.hasAttribute("download") &&
        link.target !== "_blank" &&
        !ev.ctrlKey &&
        !ev.metaKey
      ) {
        startTopLoader();
      }
    });

    document.body.addEventListener("htmx:beforeRequest", function (ev) {
      startTopLoader();
      var target = ev.detail && ev.detail.target;
      if (target && target.classList) {
        target.classList.add("is-loading");
      }
    });

    document.body.addEventListener("htmx:afterRequest", function (ev) {
      stopTopLoader();
      var target = ev.detail && ev.detail.target;
      if (target && target.classList) {
        target.classList.remove("is-loading");
      }
    });

    /* 2. Salutation selon l'heure & Compte à rebours vers 18h00 */
    var greetingEl = document.querySelector("[data-greeting-name]");
    if (greetingEl) {
      var name = greetingEl.getAttribute("data-greeting-name") || "";
      var hour = new Date().getHours();
      var prefix = hour >= 12 ? "Bon après-midi" : "Bonjour";
      greetingEl.textContent = name ? prefix + " " + name : prefix;
    }

    var countdownEl = document.getElementById("cutoff-countdown");
    if (countdownEl) {
      var now = new Date();
      var cutoff = new Date();
      cutoff.setHours(18, 0, 0, 0);
      if (now < cutoff) {
        var diffMin = Math.max(1, Math.floor((cutoff - now) / 60000));
        var h = Math.floor(diffMin / 60);
        var m = diffMin % 60;
        countdownEl.textContent =
          "Réservez pour demain avant 18h00 — encore " +
          h +
          " h " +
          (m < 10 ? "0" + m : m);
      } else {
        countdownEl.textContent = "Réservez votre prochain déjeuner avant la veille à 18h00";
      }
    }

    /* 3. Filtres allergènes sur /menu/ */
    var filterChips = document.querySelectorAll(".filter-chip[data-allergen-filter]");
    if (filterChips.length > 0) {
      var dishCards = document.querySelectorAll("[data-allergen-ids]");
      var filterCounter = document.getElementById("filter-count");

      var applyAllergenFilters = function () {
        var activeIds = [];
        filterChips.forEach(function (chip) {
          if (chip.classList.contains("is-active")) {
            activeIds.push(chip.getAttribute("data-allergen-filter"));
          }
        });
        if (filterCounter) {
          filterCounter.textContent = String(activeIds.length);
        }
        dishCards.forEach(function (card) {
          var raw = card.getAttribute("data-allergen-ids") || "";
          var ids = raw.split(",").map(function (s) { return s.trim(); }).filter(Boolean);
          var shouldHide = activeIds.some(function (id) {
            return ids.indexOf(id) !== -1;
          });
          var col = card.closest("[data-dish-col]") || card;
          col.hidden = shouldHide;
        });
      };

      filterChips.forEach(function (chip) {
        chip.addEventListener("click", function () {
          chip.classList.toggle("is-active");
          var pressed = chip.classList.contains("is-active");
          chip.setAttribute("aria-pressed", pressed ? "true" : "false");
          applyAllergenFilters();
        });
      });
    }

    /* 4. Synchronisation visuelle des cartes de sélection + envol vers Mon plateau (250 ms) */
    var updateTrayPreview = function (input) {
      var card = input.closest("[data-dish-name]");
      if (!card || !input.checked) return;
      var slot = card.getAttribute("data-dish-slot");
      var dishName = card.getAttribute("data-dish-name");
      var target = slot ? document.getElementById("tray-slot-" + slot) : null;
      if (target) {
        target.textContent = dishName;
        var trayPanel = document.getElementById("mon-plateau-panel");
        if (trayPanel) {
          trayPanel.classList.remove("tray-pulse");
          void trayPanel.offsetWidth;
          trayPanel.classList.add("tray-pulse");
        }
      }
    };

    var syncSelectionGroup = function (selector, activeClass) {
      var inputs = document.querySelectorAll(selector + ' input[type="radio"]');
      inputs.forEach(function (input) {
        var updateGroup = function () {
          var name = input.name;
          if (!name) return;
          document.querySelectorAll('input[name="' + name + '"]').forEach(function (peer) {
            var card = peer.closest(selector);
            if (card) {
              card.classList.toggle(activeClass, peer.checked);
            }
          });
          updateTrayPreview(input);
        };
        input.addEventListener("change", updateGroup);
        updateGroup();
      });
    };

    syncSelectionGroup(".choice-card", "is-selected");
    syncSelectionGroup(".dish-select-card", "is-selected");
    syncSelectionGroup(".amount-chip", "is-active");
    syncSelectionGroup(".pay-option", "is-active");

    /* 5. Bascule du champ lieu de livraison (ON_SITE vs DELIVERY) */
    var deliveryBox = document.getElementById("delivery-location-box");
    var deliveryInput = document.getElementById("id_delivery_location");
    var fulfillmentRadios = document.querySelectorAll('input[name="fulfillment"]');
    var trayFulfillmentLabel = document.getElementById("tray-fulfillment-label");
    if (fulfillmentRadios.length > 0) {
      var toggleDeliveryBox = function () {
        var selected = document.querySelector('input[name="fulfillment"]:checked');
        var isDelivery = selected && selected.value === "DELIVERY";
        if (deliveryBox) {
          deliveryBox.hidden = !isDelivery;
        }
        if (deliveryInput) {
          deliveryInput.required = Boolean(isDelivery);
        }
        if (trayFulfillmentLabel) {
          var loc = deliveryInput && deliveryInput.value ? deliveryInput.value : "Lieu à préciser";
          trayFulfillmentLabel.textContent = isDelivery ? "Livraison · " + loc : "Retrait au comptoir";
        }
      };
      fulfillmentRadios.forEach(function (radio) {
        radio.addEventListener("change", toggleDeliveryBox);
      });
      if (deliveryInput) {
        deliveryInput.addEventListener("input", toggleDeliveryBox);
      }
      toggleDeliveryBox();
    }

    /* 6. État de chargement UX/UI instantané sur les boutons & anti-double-clic */
    document.querySelectorAll("form").forEach(function (form) {
      form.addEventListener("submit", function (ev) {
        var submitter = ev.submitter || form.querySelector('button[type="submit"]');
        if (submitter && !submitter.dataset.submitted) {
          submitter.dataset.submitted = "true";
          startTopLoader();
          var loadingText = submitter.getAttribute("data-loading-text") || "Traitement en cours…";
          var minW = submitter.offsetWidth;
          if (minW) {
            submitter.style.minWidth = minW + "px";
          }
          submitter.classList.add("is-loading");
          submitter.setAttribute("aria-busy", "true");
          submitter.innerHTML =
            '<span class="vsc-btn-spinner" aria-hidden="true"></span><span>' +
            loadingText +
            "</span>";
          setTimeout(function () {
            submitter.disabled = true;
          }, 15);
        }
      });
    });

    /* 7. Confirmation explicite via data-confirm */
    document.addEventListener("click", function (ev) {
      var trigger = ev.target.closest("[data-confirm]");
      if (!trigger) return;
      var msg = trigger.getAttribute("data-confirm");
      if (msg && !window.confirm(msg)) {
        ev.preventDefault();
      }
    });
  });
})();
