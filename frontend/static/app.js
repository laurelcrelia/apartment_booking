// Shared code for the pages. Each page is a static HTML file; its own script in
// pages/ loads the data from the REST API with loadPage() and fills it in.
// All data goes in as text (never as HTML), so names can't inject markup.
//
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

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

// "2030-05-01" -> "May 1, 2030"
function niceDate(iso) {
  const [year, month, day] = iso.split("-").map(Number);
  return `${MONTHS[month - 1]} ${day}, ${year}`;
}

// Up to two capital letters from the first words of a name, or "?".
function initials(name) {
  return (name || "").split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase() || "?";
}

const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
const bookingNights = (b) => countNights(b.check_in, b.check_out);

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

class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

// GET a JSON resource from the REST API; throws ApiError for error responses.
async function api(path) {
  let response;
  try {
    response = await fetch(path, { headers: { Accept: "application/json" } });
  } catch (err) {
    throw new ApiError(0, "Could not reach the server.");
  }
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    throw new ApiError(response.status, data && data.error ? data.error.message : `Request failed (${response.status})`);
  }
  return data;
}

// The number at the end of the page's path, e.g. 3 for /apartments/3.
const pathId = () => Number(window.location.pathname.split("/").pop());

// Fill a page: run render(), then wire up its forms and show it. <main> stays
// hidden until then, so nobody types into a form that is about to be filled in.
async function loadPage(render) {
  const main = document.querySelector("main");
  try {
    await render();
    bindForms(document);
  } catch (err) {
    showProblem(main, err);
  }
  main.classList.remove("loading");
}

function showProblem(main, err) {
  const notFound = err instanceof ApiError && err.status === 404;
  const card = el("div", "card");
  const box = el("div", "empty-state");
  box.append(el("h3", "", notFound ? "Not found" : "This page can't be loaded right now"),
             el("p", "", err.message || String(err)));
  const link = el("a", "button", notFound ? "Back to apartments" : "Try again");
  link.href = notFound ? "/" : window.location.href;
  box.append(link);
  card.append(box);
  main.replaceChildren(card);
}

// Set a form field's value and make it what the form's reset button restores.
function setField(form, name, value) {
  const field = form.elements[name];
  field.value = value;
  field.defaultValue = value;
}

// <option>s for an apartment <select>, with each apartment's price for the stay summary.
function fillApartmentSelect(select, apartments, selectedId) {
  select.replaceChildren(...apartments.map((a) => {
    const option = el("option", "", `${a.name} · ${euro(a.price)}/night`);
    option.value = a.id;
    option.dataset.price = a.price;
    option.selected = option.defaultSelected = a.id === selectedId;
    return option;
  }));
}

function link(href, className, text) {
  const a = el("a", className, text);
  a.href = href;
  return a;
}

function cell(className, ...children) {
  const td = el("td", className);
  td.append(...children);
  return td;
}

// A table of bookings. With apartmentsById it has an apartment column; otherwise
// every booking belongs to `apartment`.
function bookingsTable(bookings, { apartmentsById = null, apartment = null, emptyHint }) {
  if (bookings.length === 0) {
    const empty = el("div", "empty-state");
    empty.append(el("h3", "", "No bookings."), el("p", "", emptyHint));
    return empty;
  }
  const head = ["Booking", ...(apartmentsById ? ["Apartment"] : []), "Guest", "Dates & stay", "Est. total", "Status"];
  const headRow = el("tr");
  for (const title of head) headRow.append(el("th", title === "Est. total" ? "num" : "", title));
  const action = el("th");
  action.append(el("span", "visually-hidden", "Action"));
  headRow.append(action);
  const thead = el("thead");
  thead.append(headRow);

  const tbody = el("tbody");
  for (const b of bookings) {
    const apt = apartmentsById ? apartmentsById.get(b.apartment_id) : apartment;
    const nights = bookingNights(b);
    const row = el("tr", b.status);
    row.append(cell("", link(`/bookings/${b.id}`, "primary num", `#${b.id}`)));
    if (apartmentsById) {
      const who = el("div", "with-avatar");
      const info = el("div");
      info.append(apt ? link(`/apartments/${apt.id}`, "primary", apt.name) : el("span", "primary", `Apartment ${b.apartment_id}`),
                  el("span", "secondary", apt ? plural(apt.rooms, "room") : "removed"));
      const avatar = el("span", "avatar", initials(apt ? apt.name : ""));
      avatar.setAttribute("aria-hidden", "true");
      who.append(avatar, info);
      row.append(cell("", who));
    }
    row.append(cell("", el("span", "primary", b.guest || "No guest name")));
    row.append(cell("", el("span", "primary num", `${niceDate(b.check_in)} → ${niceDate(b.check_out)}`),
                    el("span", "secondary", plural(nights, "night"))));
    row.append(apt ? cell("num", el("span", "primary", euro(apt.price * nights)), el("span", "secondary", `${euro(apt.price)}/night`))
                   : cell("num", el("span", "secondary", "–")));
    row.append(cell("", el("span", `badge ${b.status}`, b.status)));
    row.append(cell("", link(`/bookings/${b.id}`, "row-link", b.status === "active" ? "Manage" : "View")));
    tbody.append(row);
  }
  const table = el("table");
  table.append(thead, tbody);
  const wrap = el("div", "table-wrap");
  wrap.append(table);
  return wrap;
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

function bindForms(root) {
  for (const form of root.querySelectorAll("form[data-api]")) {
    form.addEventListener("submit", submitToApi);
  }
  for (const form of root.querySelectorAll("form[data-nights]")) {
    form.addEventListener("input", () => updateNights(form));
    form.addEventListener("reset", () => setTimeout(() => updateNights(form)));
    updateNights(form);
  }
}

document.addEventListener("DOMContentLoaded", showFlash);
