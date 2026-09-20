(function () {
  const root = document.querySelector("[data-clm-timeline]");
  if (!root) return;
  const nodes = Array.prototype.slice.call(root.querySelectorAll("[data-timeline]"));
  const details = Array.prototype.slice.call(root.querySelectorAll("[data-timeline-detail]"));
  nodes.forEach(function (btn) {
    btn.addEventListener("click", function () {
      const id = btn.getAttribute("data-timeline");
      nodes.forEach(function (n) {
        const on = n === btn;
        n.classList.toggle("is-active", on);
        n.setAttribute("aria-selected", on ? "true" : "false");
      });
      details.forEach(function (d) {
        const on = d.getAttribute("data-timeline-detail") === id;
        d.classList.toggle("is-active", on);
        d.hidden = !on;
      });
    });
  });
})();
