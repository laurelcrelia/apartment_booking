// "/bookings" - all bookings with filters (from the page's query string) and a booking form.
loadPage(async () => {
  const query = new URLSearchParams(window.location.search);
  const filters = {
    apartment_id: /^\d+$/.test(query.get("apartment_id") || "") ? query.get("apartment_id") : "",
    guest: (query.get("guest") || "").trim(),
    include_cancelled: query.get("include_cancelled") === "true",
  };
  const params = new URLSearchParams();
  if (filters.apartment_id) params.set("apartment_id", filters.apartment_id);
  if (filters.guest) params.set("guest", filters.guest);
  if (filters.include_cancelled) params.set("include_cancelled", "true");
  const [apartments, bookings] = await Promise.all([api("/api/apartments"), api(`/api/bookings?${params}`)]);

  const filterForm = document.querySelector("form.filters");
  const select = filterForm.elements.apartment_id;
  const all = el("option", "", `All apartments (${apartments.length})`);
  all.value = "";
  select.replaceChildren(all, ...apartments.map((a) => {
    const option = el("option", "", a.name);
    option.value = a.id;
    option.selected = String(a.id) === filters.apartment_id;
    return option;
  }));
  filterForm.elements.guest.value = filters.guest;
  filterForm.elements.include_cancelled.checked = filters.include_cancelled;
  document.getElementById("clear-filters").hidden = !(filters.apartment_id || filters.guest || filters.include_cancelled);

  document.getElementById("booking-count").textContent = `${bookings.length} shown`;
  document.getElementById("booking-list").replaceChildren(bookingsTable(bookings, {
    apartmentsById: new Map(apartments.map((a) => [a.id, a])),
    emptyHint: "Try different filters, or create a booking.",
  }));
  document.getElementById("cancelled-hint").hidden = filters.include_cancelled;

  const create = document.querySelector("#create-booking form");
  if (apartments.length) {
    fillApartmentSelect(create.elements.apartment_id, apartments, null);
  } else {
    create.hidden = true;
    document.getElementById("no-apartments").hidden = false;
    document.getElementById("new-booking-link").hidden = true;
  }
});
