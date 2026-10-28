/* AttendSmart -- main.js
   Global utilities: tab switcher, progress bar animation, toast auto-dismiss.
*/
(function() {
  "use strict";

  // ── Auth tab switcher (intro page) ────────────────────────────
  var tabLogin  = document.getElementById("tab-login");
  var tabSignup = document.getElementById("tab-signup");
  var panelLogin  = document.getElementById("panel-login");
  var panelSignup = document.getElementById("panel-signup");

  function switchTab(show, hide, showPanel, hidePanel, showBtn, hideBtn) {
    showPanel.classList.remove("hidden");
    hidePanel.classList.add("hidden");
    showBtn.classList.add("auth-tab--active");
    hideBtn.classList.remove("auth-tab--active");
    var inp = showPanel.querySelector("input");
    if (inp) inp.focus();
  }

  if (tabLogin && tabSignup) {
    tabLogin.addEventListener("click", function() {
      switchTab(panelLogin, panelSignup, panelLogin, panelSignup, tabLogin, tabSignup);
    });
    tabSignup.addEventListener("click", function() {
      switchTab(panelSignup, panelLogin, panelSignup, panelLogin, tabSignup, tabLogin);
    });
  }

  // ── Progress bar count-up on page load ───────────────────────
  document.querySelectorAll(".js-fill").forEach(function(el) {
    var target = parseFloat(el.dataset.target) || 0;
    el.style.width = "0%";
    requestAnimationFrame(function() {
      setTimeout(function() {
        el.style.transition = "width 0.8s ease";
        el.style.width = Math.min(target, 100) + "%";
      }, 80);
    });
  });

  // ── Percentage count-up ───────────────────────────────────────
  document.querySelectorAll(".js-pct").forEach(function(el) {
    var target = parseFloat(el.dataset.target) || 0;
    var text = el.textContent;
    if (!text.includes("%")) return;
    var start = 0;
    var duration = 700;
    var startTime = null;
    function step(timestamp) {
      if (!startTime) startTime = timestamp;
      var progress = Math.min((timestamp - startTime) / duration, 1);
      el.textContent = (start + (target - start) * progress).toFixed(1) + "%";
      if (progress < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  });

  // ── Toast auto-dismiss ────────────────────────────────────────
  document.querySelectorAll(".toast").forEach(function(el) {
    setTimeout(function() {
      el.style.transition = "opacity 0.4s ease";
      el.style.opacity = "0";
      setTimeout(function() { el.remove(); }, 400);
    }, 4000);
  });

})();
