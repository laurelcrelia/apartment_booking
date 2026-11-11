// Forms with a data-api attribute are sent to the REST API as JSON.
//   data-api       URL to call             data-method   HTTP method (GET sends a query string)
//   data-redirect  URL to open on success, "{id}" is replaced with the returned id
//   data-render    id of an element to render GET results into (otherwise the page reloads)
//   data-flash     message shown after the redirect or reload
//   data-confirm   ask before sending
//   data-nights    show the number of nights (and, with a price, the estimated total) as dates change
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
  if (!message || !el) return;
  el.querySelector("[data-message]").textContent = message;
  el.hidden = false;
  el.querySelector("[data-dismiss]").addEventListener("click", () => { el.hidden = true; });
  setTimeout(() => { el.hidden = true; }, 5000);
}

// Resolves to true if the user confirms. Falls back to window.confirm without <dialog> support.
function askConfirm(message) {
  const dialog = document.getElementById("confirm-dialog");
  if (!dialog || typeof dialog.showModal !== "function") return Promise.resolve(window.confirm(message));
  dialog.querySelector("[data-message]").textContent = message;
  dialog.returnValue = "";
  dialog.showModal();
  dialog.querySelector("[data-ok]").focus();
  return new Promise((resolve) => {
    dialog.addEventListener("close", () => resolve(dialog.returnValue === "ok"), { once: true });
  });
}

const euro = (value) => "€" + Number(value).toLocaleString("en", {
  minimumFractionDigits: Number.isInteger(Number(value)) ? 0 : 2, maximumFractionDigits: 2 });

function countNights(from, to) {
  if (!from || !to) return null;
  return Math.round((Date.parse(to) - Date.parse(from)) / 86400000);
}

// Price per night for a data-nights form: its own data-price, or the selected apartment's.
function formPrice(form) {
  if (form.dataset.price) return Number(form.dataset.price);
  const option = form.querySelector("select[name=apartment_id]")?.selectedOptions[0];
  return option && option.dataset.price ? Number(option.dataset.price) : null;
}

function updateNights(form) {
  const [from, to] = [...form.querySelectorAll("input[type=date]")].map((el) => el.value);
  const nights = countNights(from, to);
  const label = form.querySelector("[data-nights-label]");
  const rate = form.querySelector("[data-rate]");
  const total = form.querySelector("[data-total]");
  const price = formPrice(form);
  if (rate) rate.textContent = price === null ? "–" : euro(price);
  if (nights === null) {
    if (label) label.textContent = rate ? "Pick check-in and check-out" : "Check-out is exclusive.";
    if (total) total.textContent = "–";
  } else if (nights < 1) {
    if (label) label.textContent = "Check-out must be after check-in";
    if (total) total.textContent = "–";
  } else {
    if (label) label.textContent = `${nights} night${nights === 1 ? "" : "s"} · check-out exclusive`;
    if (total) total.textContent = price === null ? "–" : `${euro(price * nights)} (${euro(price)} × ${nights})`;
  }
}

async function submitToApi(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const errorBox = form.querySelector(".form-error");
  const button = form.querySelector("button[type=submit]");
  if (form.dataset.confirm && !(await askConfirm(form.dataset.confirm))) return;

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

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

const renderers = {
  "search-results"(target, apartments, query) {
    target.replaceChildren();
    const box = el("div", "results");
    const nights = countNights(query.from, query.to);
    if (apartments.length === 0) {
      box.append(el("p", "empty", "No apartments available for these dates."));
      target.append(box);
      return;
    }
    const head = el("div", "results-head");
    head.append(
      el("span", "", `${apartments.length} available for ${nights} night${nights === 1 ? "" : "s"}`),
      el("span", "secondary", `${query.from} → ${query.to}`));
    box.append(head);
    for (const a of apartments) {
      const item = el("div", "result");
      const info = el("div");
      info.append(el("span", "primary", a.name),
        el("span", "secondary", `${a.rooms} room${a.rooms === 1 ? "" : "s"} · ${nights} × ${euro(a.price)}`));
      const end = el("div", "result-end");
      const price = el("span", "price", euro(a.price * nights));
      price.append(el("small", "", "est. total"));
      const link = el("a", "button", "Book");
      link.href = `/apartments/${a.id}?` + new URLSearchParams({ from: query.from, to: query.to });
      end.append(price, link);
      item.append(info, end);
      box.append(item);
    }
    target.append(box);
  },
};

document.addEventListener("DOMContentLoaded", () => {
  showFlash();
  for (const form of document.querySelectorAll("form[data-api]")) {
    form.addEventListener("submit", submitToApi);
  }
  for (const form of document.querySelectorAll("form[data-nights]")) {
    form.addEventListener("input", () => updateNights(form));
    form.addEventListener("reset", () => setTimeout(() => updateNights(form)));
    updateNights(form);
  }
});
