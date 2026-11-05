// Forms with a data-api attribute are sent to the REST API as JSON.
//   data-api       URL to call             data-method   HTTP method (GET sends a query string)
//   data-redirect  URL to open on success, "{id}" is replaced with the returned id
//   data-render    id of an element to render GET results into (otherwise the page reloads)
//   data-flash     message shown after the redirect or reload
//   data-confirm   ask before sending
// Inputs with data-type="int" or "number" are sent as numbers and left out when empty.

function readForm(form) {
  const values = {};
  for (const el of form.elements) {
    if (!el.name || el.disabled) continue;
    if (el.type === "checkbox") { values[el.name] = el.checked; continue; }
    let value = el.value.trim();
    if (el.dataset.type === "int" || el.dataset.type === "number") {
      if (value === "") continue;
      value = Number(value);
    }
    values[el.name] = value;
  }
  return values;
}

function setFlash(message) {
  try { sessionStorage.setItem("flash", message); } catch (e) { /* storage unavailable */ }
}

function showFlash() {
  let message = null;
  try {
    message = sessionStorage.getItem("flash");
    sessionStorage.removeItem("flash");
  } catch (e) { /* storage unavailable */ }
  const el = document.getElementById("flash");
  if (message && el) { el.textContent = message; el.hidden = false; }
}

async function submitToApi(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const errorBox = form.querySelector(".form-error");
  const button = form.querySelector("button[type=submit]");
  if (form.dataset.confirm && !window.confirm(form.dataset.confirm)) return;

  const method = (form.dataset.method || "POST").toUpperCase();
  const values = readForm(form);
  let url = form.dataset.api;
  const options = { method, headers: { Accept: "application/json" } };
  if (method === "GET") {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(values)) if (value !== "") params.set(key, value);
    url += "?" + params;
  } else if (method !== "DELETE") {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(values);
  }

  errorBox.hidden = true;
  button.disabled = true;
  try {
    const response = await fetch(url, options);
    const data = response.status === 204 ? null : await response.json();
    if (!response.ok) {
      errorBox.textContent = data && data.error ? data.error.message : `Request failed (${response.status})`;
      errorBox.hidden = false;
      return;
    }
    if (form.dataset.render) {
      renderers[form.dataset.render](document.getElementById(form.dataset.render), data, values);
      return;
    }
    if (form.dataset.flash) setFlash(form.dataset.flash);
    if (form.dataset.redirect) {
      window.location.href = form.dataset.redirect.replace("{id}", data ? data.id : "");
    } else {
      window.location.reload();
    }
  } catch (err) {
    errorBox.textContent = "Could not reach the server. Please try again.";
    errorBox.hidden = false;
  } finally {
    button.disabled = false;
  }
}

function cell(row, content) {
  const td = row.insertCell();
  if (content instanceof Node) td.append(content); else td.textContent = content;
}

const renderers = {
  "search-results"(target, apartments, query) {
    target.replaceChildren();
    if (apartments.length === 0) {
      const p = document.createElement("p");
      p.className = "empty";
      p.textContent = "No apartments available for these dates.";
      target.append(p);
      return;
    }
    const table = document.createElement("table");
    table.createTHead().insertRow().append(
      ...["Apartment", "Rooms", "Price / night", ""].map((text) => {
        const th = document.createElement("th"); th.textContent = text; return th;
      }));
    const body = table.createTBody();
    for (const a of apartments) {
      const row = body.insertRow();
      cell(row, `${a.id} · ${a.name}`);
      cell(row, String(a.rooms));
      cell(row, Number(a.price).toFixed(2));
      const link = document.createElement("a");
      link.href = `/apartments/${a.id}?` + new URLSearchParams({ from: query.from, to: query.to });
      link.textContent = "Book";
      cell(row, link);
    }
    target.append(table);
  },
};

document.addEventListener("DOMContentLoaded", () => {
  showFlash();
  for (const form of document.querySelectorAll("form[data-api]")) {
    form.addEventListener("submit", submitToApi);
  }
});
