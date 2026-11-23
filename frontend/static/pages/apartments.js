// "/" - all apartments, availability search and the add form.
loadPage(async () => {
  const [apartments, activeBookings] = await Promise.all([api("/api/apartments"), api("/api/bookings")]);
  const activeCounts = new Map();
  for (const b of activeBookings) activeCounts.set(b.apartment_id, (activeCounts.get(b.apartment_id) || 0) + 1);

  document.getElementById("apartment-count").textContent = plural(apartments.length, "apartment");
  document.getElementById("active-count").textContent = plural(activeBookings.length, "active booking");
  document.getElementById("apartment-total").textContent = `${apartments.length} total`;

  const list = document.getElementById("apartment-list");
  if (apartments.length === 0) {
    const empty = el("div", "empty-state");
    empty.append(el("h3", "", "No apartments yet."), el("p", "", "Add an apartment to start taking bookings."),
                 link("#add-apartment", "button", "Add first apartment"));
    list.replaceChildren(empty);
    return;
  }
  const headRow = el("tr");
  for (const [title, cls] of [["Apartment"], ["Address"], ["Rooms", "num"], ["Rate / night", "num"], ["Bookings"]]) {
    headRow.append(el("th", cls || "", title));
  }
  const action = el("th");
  action.append(el("span", "visually-hidden", "Action"));
  headRow.append(action);
  const thead = el("thead");
  thead.append(headRow);
  const tbody = el("tbody");
  for (const a of apartments) {
    const n = activeCounts.get(a.id) || 0;
    const row = el("tr");
    row.append(cell("", link(`/apartments/${a.id}`, "primary", a.name), el("span", "secondary", `ID ${a.id}`)),
               cell("", a.address || "–"),
               cell("num", String(a.rooms)),
               cell("num", euro(a.price)),
               cell("", el("span", n ? "badge active" : "badge", `${n} active`)),
               cell("", link(`/apartments/${a.id}`, "row-link", "Details")));
    tbody.append(row);
  }
  const table = el("table");
  table.append(thead, tbody);
  const wrap = el("div", "table-wrap");
  wrap.append(table);
  list.replaceChildren(wrap);
});
