// 레시피 찾기 (고정 사이트용): 서버 없이 브라우저에서 거르고 쪽을 나눈다.
// 조건은 주소의 ?lang=&cat=&ing=&q=&page= 에 담아 두어, 링크로 주고받을 수 있다.
(function () {
  var PER = 20;
  var rows = Array.prototype.slice.call(document.querySelectorAll("tr[data-id]"));
  var form = document.querySelector("form.filter");
  var total = document.getElementById("total");
  var pageInfo = document.getElementById("page-info");
  var pager = document.getElementById("pager");
  var table = document.getElementById("list");
  var empty = document.getElementById("empty");
  if (!form || !rows.length) return;
  var KEYS = ["lang", "cat", "ing", "q"];

  function state() {
    var p = new URLSearchParams(location.search), s = {};
    KEYS.forEach(function (k) { s[k] = (p.get(k) || "").trim(); });
    s.page = Math.max(1, parseInt(p.get("page") || "1", 10) || 1);
    return s;
  }

  function url(s, page) {
    var p = new URLSearchParams();
    KEYS.forEach(function (k) { if (s[k]) p.set(k, s[k]); });
    if (page > 1) p.set("page", page);
    var qs = p.toString();
    return location.pathname + (qs ? "?" + qs : "");
  }

  function go(s, page) {
    history.pushState(null, "", url(s, page));
    render();
    window.scrollTo(0, 0);
  }

  function link(label, s, page) {
    var a = document.createElement("a");
    a.href = url(s, page);
    a.textContent = label;
    a.addEventListener("click", function (e) { e.preventDefault(); go(s, page); });
    return a;
  }

  function render() {
    var s = state(), q = s.q.toLowerCase();
    KEYS.forEach(function (k) { if (form.elements[k]) form.elements[k].value = s[k]; });
    var hit = rows.filter(function (r) {
      var d = r.dataset;
      return (!s.lang || d.lang === s.lang) && (!s.cat || d.cat === s.cat) &&
             (!s.ing || (" " + d.ing + " ").indexOf(" " + s.ing + " ") >= 0) &&
             (!q || d.text.indexOf(q) >= 0);
    });
    var pages = Math.max(1, Math.ceil(hit.length / PER)), page = Math.min(s.page, pages);
    rows.forEach(function (r) { r.hidden = true; });
    hit.forEach(function (r, i) {
      r.hidden = i < (page - 1) * PER || i >= page * PER;
      r.cells[0].textContent = i + 1;
    });
    total.textContent = hit.length;
    pageInfo.textContent = pages > 1 ? " ／ " + page + " / " + pages + " 쪽" : "";
    table.hidden = !hit.length;
    empty.hidden = !!hit.length;
    pager.textContent = "";
    if (pages > 1) {
      if (page > 1) pager.appendChild(link("<<이전", s, page - 1));
      for (var p = 1; p <= pages; p++) {
        if (p === page) { var b = document.createElement("b"); b.textContent = "[" + p + "]"; pager.appendChild(b); }
        else pager.appendChild(link("[" + p + "]", s, p));
      }
      if (page < pages) pager.appendChild(link("다음>>", s, page + 1));
    }
  }

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var s = {};
    KEYS.forEach(function (k) { s[k] = form.elements[k] ? form.elements[k].value.trim() : ""; });
    go(s, 1);
  });
  window.addEventListener("popstate", render);
  render();
})();
