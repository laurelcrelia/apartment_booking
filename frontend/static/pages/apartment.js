// "/apartments/{id}" - one apartment: its bookings, edit and remove, and a booking form.
loadPage(async () => {
  const id = pathId();
  const [apt, bookings] = await Promise.all([
    api(`/api/apartments/${id}`),
    api(`/api/bookings?apartment_id=${id}&include_cancelled=true`),
  ]);
  const active = bookings.filter((b) => b.status === "active");
  const activeNights = active.reduce((sum, b) => sum + bookingNights(b), 0);

  document.title = `${apt.name} · Apartment Booking`;
  for (const node of document.querySelectorAll("[data-field=name]")) node.textContent = apt.name;
  document.getElementById("apartment-id").textContent = `#${apt.id}`;
  document.getElementById("apartment-address").textContent = apt.address || "No address";
  document.getElementById("apartment-rooms").textContent = plural(apt.rooms, "room");
  document.getElementById("apartment-rate").textContent = `${euro(apt.price)} / night`;
  document.getElementById("stat-bookings").textContent = bookings.length;
  document.getElementById("stat-active").textContent = active.length;
  document.getElementById("stat-nights").textContent = `${activeNights} nights booked`;
  document.getElementById("stat-value").textContent = euro(apt.price * activeNights);
  document.getElementById("booking-count").textContent = plural(bookings.length, "record");
  document.getElementById("booking-list").replaceChildren(
    bookingsTable(bookings, { apartment: apt, emptyHint: "Use the form to book this apartment." }));

  const edit = document.getElementById("edit-form");
  edit.dataset.api = `/api/apartments/${apt.id}`;
  setField(edit, "name", apt.name);
  setField(edit, "address", apt.address);
  setField(edit, "rooms", apt.rooms);
  setField(edit, "price", apt.price);

  const remove = document.getElementById("remove-form");
  remove.dataset.api = `/api/apartments/${apt.id}`;
  remove.dataset.confirm = `Remove ${apt.name}? This cannot be undone.`;
  if (active.length) {
    const notice = document.getElementById("active-notice");
    notice.append(`This apartment has ${plural(active.length, "active booking")} (`);
    active.forEach((b, i) => notice.append(...(i ? [", "] : []), link(`/bookings/${b.id}`, "", `#${b.id}`)));
    notice.append(`). Cancel ${active.length === 1 ? "it" : "them"} first.`);
    notice.hidden = false;
    remove.querySelector("button[type=submit]").disabled = true;
  }

  // Coming from availability search, the stay is already chosen.
  const book = document.getElementById("book-form");
  const query = new URLSearchParams(window.location.search);
  book.dataset.price = apt.price;
  setField(book, "apartment_id", apt.id);
  setField(book, "check_in", query.get("from") || "");
  setField(book, "check_out", query.get("to") || "");
});
