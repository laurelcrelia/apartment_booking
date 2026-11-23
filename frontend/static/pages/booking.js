// "/bookings/{id}" - one booking: change or cancel it while it's active.
loadPage(async () => {
  const id = pathId();
  const [booking, apartments] = await Promise.all([api(`/api/bookings/${id}`), api("/api/apartments")]);
  const apt = apartments.find((a) => a.id === booking.apartment_id) || null;
  const nights = bookingNights(booking);
  const dates = `${niceDate(booking.check_in)} → ${niceDate(booking.check_out)}`;

  document.title = `Booking ${booking.id} · Apartment Booking`;
  document.querySelector("[data-field=number]").textContent = `#${booking.id}`;
  document.getElementById("booking-title").textContent = `Booking #${booking.id}`;
  const status = document.getElementById("booking-status");
  status.className = `badge ${booking.status}`;
  status.textContent = booking.status;

  document.getElementById("apartment-initials").textContent = apt ? initials(apt.name) : "?";
  const heading = el("h2", "", apt ? apt.name : `Apartment ${booking.apartment_id}`);
  if (apt) {
    const a = link(`/apartments/${apt.id}`, "primary");
    a.append(heading);
    document.getElementById("apartment-heading").replaceChildren(a);
  } else {
    document.getElementById("apartment-heading").replaceChildren(heading);
  }
  for (const node of document.querySelectorAll("[data-field=dates]")) node.textContent = dates;
  for (const node of document.querySelectorAll("[data-field=nights]")) node.textContent = plural(nights, "night");
  if (apt) {
    document.getElementById("total-stat").hidden = false;
    document.getElementById("stat-total").textContent = euro(apt.price * nights);
    document.getElementById("stat-rate").textContent = `${euro(apt.price)} / night`;
  }

  if (booking.status !== "active") {
    document.getElementById("fact-apartment").textContent = apt ? apt.name : booking.apartment_id;
    document.getElementById("fact-guest").textContent = booking.guest || "–";
    document.getElementById("fact-dates").textContent = `${dates} (${plural(nights, "night")})`;
    document.getElementById("cancelled-view").hidden = false;
    document.getElementById("active-view").remove();  // so its forms can't be found or sent
    return;
  }

  document.getElementById("active-view").hidden = false;
  document.getElementById("cancelled-view").remove();
  const change = document.getElementById("change-form");
  change.dataset.api = `/api/bookings/${booking.id}`;
  fillApartmentSelect(change.elements.apartment_id, apartments, booking.apartment_id);
  setField(change, "guest", booking.guest);
  setField(change, "check_in", booking.check_in);
  setField(change, "check_out", booking.check_out);

  const cancel = document.getElementById("cancel-form");
  cancel.dataset.api = `/api/bookings/${booking.id}`;
  cancel.dataset.confirm = `Cancel booking #${booking.id}${booking.guest ? ` for ${booking.guest}` : ""}? `
    + "The dates will be released immediately.";
  document.getElementById("guest-initials").textContent = booking.guest ? initials(booking.guest) : "?";
  document.querySelector("[data-field=guest]").textContent = booking.guest || "No guest name";
});
