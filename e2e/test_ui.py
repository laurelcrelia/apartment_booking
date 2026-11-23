"""Browser tests for the web UI, run with Playwright in Chromium.

Each test class starts the app on a free local port; every test gets fresh
in-memory data and a fresh browser context.

Setup (once):  pip install -r requirements-e2e.txt && playwright install chromium
Run:           python -m unittest discover -s e2e -v
Watch it run:  HEADED=1 python -m unittest discover -s e2e -v

This folder has no __init__.py on purpose, so the plain `python -m unittest`
run (and the coverage job) does not pick these tests up.
"""
from __future__ import annotations

import os
import re
import unittest

from playwright.sync_api import Page, expect, sync_playwright

import devstack

HEADED = os.environ.get("HEADED") == "1"
WEB_FONTS = re.compile(r"https://fonts\.(googleapis|gstatic)\.com/.*")


class BrowserTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=not HEADED, slow_mo=250 if HEADED else 0)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        # The whole app (devstack) with fresh in-memory data for every test.
        stack = devstack.start()
        self.addCleanup(stack.stop)
        self.api = stack.call
        self.base_url = stack.url
        self.context = self.browser.new_context(base_url=self.base_url)
        self.context.route(WEB_FONTS, lambda route: route.abort())  # system fonts; no internet needed
        self.page: Page = self.context.new_page()

    def tearDown(self):
        self.context.close()

    def add_apartment(self, name="Canal Loft", address="Via Museo 1", rooms=3, price=240.0) -> dict:
        return self.api("POST", "/api/apartments", {"name": name, "address": address, "rooms": rooms, "price": price})

    def add_booking(self, apt_id, check_in="2030-05-01", check_out="2030-05-05", guest="Sarah") -> dict:
        return self.api("POST", "/api/bookings",
                        {"apartment_id": apt_id, "guest": guest, "check_in": check_in, "check_out": check_out})

    def get_booking(self, booking_id) -> dict:
        return self.api("GET", f"/api/bookings/{booking_id}")

    def expect_toast(self, message):
        expect(self.page.locator("#flash")).to_be_visible()
        expect(self.page.locator("#flash")).to_contain_text(message)


class ApartmentPagesTests(BrowserTestCase):
    def test_empty_state(self):
        self.page.goto("/")
        expect(self.page.get_by_role("heading", name="No apartments yet.")).to_be_visible()

    def test_add_apartment(self):
        self.page.goto("/")
        form = self.page.locator("#add-apartment form")
        form.get_by_label("Name").fill("Skyline Terrace")
        form.get_by_label("Address").fill("Piazza Walther 2")
        form.get_by_label("Rooms").fill("2")
        form.get_by_label("Price per night").fill("120.50")
        form.get_by_role("button", name="Add apartment").click()

        expect(self.page).to_have_url(re.compile(r"/apartments/1$"))
        expect(self.page.get_by_role("heading", name="Skyline Terrace")).to_be_visible()
        expect(self.page.get_by_text("€120.50 / night")).to_be_visible()
        self.expect_toast("Apartment added")

    def test_add_apartment_shows_server_error(self):
        self.page.goto("/")
        form = self.page.locator("#add-apartment form")
        form.get_by_label("Name").fill("   ")  # passes the browser's `required`, rejected by the API
        form.get_by_label("Address").fill("Somewhere 1")
        form.get_by_role("button", name="Add apartment").click()

        expect(form.locator(".form-error")).to_be_visible()
        expect(self.page).to_have_url(f"{self.base_url}/")

    def test_list_shows_active_booking_count(self):
        apt = self.add_apartment()
        self.add_booking(apt["id"])
        self.page.goto("/")
        row = self.page.get_by_role("row", name=re.compile("Canal Loft"))
        expect(row).to_contain_text("€240")
        expect(row).to_contain_text("1 active")

    def test_search_availability_and_book(self):
        free = self.add_apartment("Free Studio", rooms=2, price=100)
        booked = self.add_apartment("Booked Loft", rooms=2, price=150)
        self.add_booking(booked["id"], "2030-06-01", "2030-06-10")

        self.page.goto("/")
        search = self.page.locator("form[data-render=search-results]")
        search.get_by_label("Check-in").fill("2030-06-03")
        search.get_by_label("Check-out").fill("2030-06-06")
        expect(search.locator("[data-nights-label]")).to_have_text("3 nights · check-out exclusive")
        search.get_by_label("Minimum rooms").fill("2")
        search.get_by_role("button", name="Check availability").click()

        results = self.page.locator("#search-results")
        expect(results).to_contain_text("1 available for 3 nights")
        expect(results.locator(".result")).to_have_count(1)
        expect(results).to_contain_text("Free Studio")
        expect(results).to_contain_text("€300")  # 3 nights × €100

        results.get_by_role("link", name="Book").click()
        expect(self.page).to_have_url(re.compile(rf"/apartments/{free['id']}\?from=2030-06-03&to=2030-06-06$"))
        expect(self.page.get_by_label("Check-in")).to_have_value("2030-06-03")
        expect(self.page.get_by_label("Check-out")).to_have_value("2030-06-06")

    def test_search_with_no_results(self):
        apt = self.add_apartment()
        self.add_booking(apt["id"], "2030-06-01", "2030-06-10")
        self.page.goto("/")
        search = self.page.locator("form[data-render=search-results]")
        search.get_by_label("Check-in").fill("2030-06-02")
        search.get_by_label("Check-out").fill("2030-06-04")
        search.get_by_role("button", name="Check availability").click()
        expect(self.page.locator("#search-results")).to_contain_text("No apartments available for these dates.")

    def test_book_apartment_with_live_total(self):
        apt = self.add_apartment(price=240)
        self.page.goto(f"/apartments/{apt['id']}")
        form = self.page.locator("form[data-api='/api/bookings']")
        form.get_by_label("Guest name").fill("Maria Rossi")
        form.get_by_label("Check-in").fill("2030-07-01")
        form.get_by_label("Check-out").fill("2030-07-06")
        expect(form.locator("[data-nights-label]")).to_have_text("5 nights · check-out exclusive")
        expect(form.locator("[data-total]")).to_have_text("€1,200 (€240 × 5)")
        form.get_by_role("button", name="Create booking").click()

        expect(self.page).to_have_url(re.compile(r"/bookings/1$"))
        expect(self.page.get_by_role("heading", name="Booking #1")).to_be_visible()
        self.expect_toast("Booking created")

    def test_overlapping_booking_is_rejected(self):
        apt = self.add_apartment()
        self.add_booking(apt["id"], "2030-05-01", "2030-05-05")
        self.page.goto(f"/apartments/{apt['id']}")
        form = self.page.locator("form[data-api='/api/bookings']")
        form.get_by_label("Check-in").fill("2030-05-03")
        form.get_by_label("Check-out").fill("2030-05-08")
        form.get_by_role("button", name="Create booking").click()

        expect(form.locator(".form-error")).to_contain_text("already booked")
        self.assertEqual(len(self.api("GET", "/api/bookings")), 1)

    def test_edit_apartment(self):
        apt = self.add_apartment()
        self.page.goto(f"/apartments/{apt['id']}")
        form = self.page.locator("form[data-method=PATCH]")
        form.get_by_label("Name").fill("Canal Loft Deluxe")
        form.get_by_label("Price per night").fill("260")
        form.get_by_role("button", name="Save changes").click()

        expect(self.page.get_by_role("heading", name="Canal Loft Deluxe")).to_be_visible()
        expect(self.page.get_by_text("€260 / night")).to_be_visible()
        self.expect_toast("Apartment updated")

    def test_remove_is_blocked_while_bookings_are_active(self):
        apt = self.add_apartment()
        self.add_booking(apt["id"])
        self.page.goto(f"/apartments/{apt['id']}")
        expect(self.page.get_by_role("button", name="Remove apartment")).to_be_disabled()
        expect(self.page.get_by_text("This apartment has 1 active booking")).to_be_visible()

    def test_remove_apartment_after_confirming(self):
        apt = self.add_apartment()
        self.page.goto(f"/apartments/{apt['id']}")
        self.page.get_by_role("button", name="Remove apartment").click()

        dialog = self.page.locator("#confirm-dialog")
        expect(dialog).to_be_visible()
        expect(dialog).to_contain_text("Remove Canal Loft?")
        dialog.get_by_role("button", name="Confirm").click()

        expect(self.page).to_have_url(f"{self.base_url}/")
        self.expect_toast("Apartment removed")
        expect(self.page.get_by_role("heading", name="No apartments yet.")).to_be_visible()


class StaticPageTests(BrowserTestCase):
    """The pages are static files that load their data from the API."""

    def test_unknown_apartment_shows_not_found(self):
        self.page.goto("/apartments/999")
        expect(self.page.get_by_role("heading", name="Not found")).to_be_visible()
        expect(self.page.get_by_text("Apartment 999 not found")).to_be_visible()

    def test_unreachable_service_shows_a_message(self):
        self.context.route("**/api/apartments", lambda route: route.fulfill(
            status=503, json={"error": {"code": "service_unavailable",
                                        "message": "The service is unavailable; try again later"}}))
        self.page.goto("/")
        expect(self.page.get_by_role("heading", name="This page can't be loaded right now")).to_be_visible()
        expect(self.page.get_by_text("The service is unavailable; try again later")).to_be_visible()
        expect(self.page.get_by_role("link", name="Try again")).to_be_visible()

    def test_names_are_shown_as_text(self):
        apt = self.add_apartment("<b>Bold</b> <img src=x onerror=alert(1)>")
        self.page.goto(f"/apartments/{apt['id']}")
        expect(self.page.get_by_role("heading", name="<b>Bold</b> <img src=x onerror=alert(1)>")).to_be_visible()
        expect(self.page.locator("main b, main img")).to_have_count(0)


class BookingPagesTests(BrowserTestCase):
    def setUp(self):
        super().setUp()
        self.loft = self.add_apartment("Canal Loft", price=240)
        self.studio = self.add_apartment("Studio", rooms=1, price=90)
        self.booking = self.add_booking(self.loft["id"], "2030-05-01", "2030-05-05", "Sarah Jenkins")

    def test_navigation_highlights_current_section(self):
        self.page.goto("/bookings")
        expect(self.page.get_by_role("link", name="Bookings", exact=True)).to_have_attribute("aria-current", "page")
        self.page.get_by_role("link", name="Apartments", exact=True).click()
        expect(self.page.get_by_role("link", name="Apartments", exact=True)).to_have_attribute("aria-current", "page")

    def test_bookings_table(self):
        self.page.goto("/bookings")
        row = self.page.get_by_role("row", name=re.compile("Sarah Jenkins"))
        expect(row).to_contain_text("Canal Loft")
        expect(row).to_contain_text("May 1, 2030 → May 5, 2030")
        expect(row).to_contain_text("4 nights")
        expect(row).to_contain_text("€960")
        expect(row).to_contain_text("active")

    def test_filters(self):
        self.add_booking(self.studio["id"], "2030-05-01", "2030-05-03", "Bob")
        self.page.goto("/bookings")
        filters = self.page.locator("form.filters")

        filters.get_by_label("Guest", exact=True).fill("bob")
        filters.get_by_role("button", name="Filter").click()
        expect(self.page.locator("tbody tr")).to_have_count(1)
        expect(self.page.locator("tbody")).to_contain_text("Bob")

        self.page.get_by_role("link", name="Clear").click()
        filters.get_by_label("Apartment").select_option(label="Canal Loft")
        filters.get_by_role("button", name="Filter").click()
        expect(self.page.locator("tbody tr")).to_have_count(1)
        expect(self.page.locator("tbody")).to_contain_text("Sarah Jenkins")

    def test_cancelled_bookings_are_hidden_unless_requested(self):
        self.api("PATCH", f"/api/bookings/{self.booking['id']}", {"status": "cancelled"})
        self.page.goto("/bookings")
        expect(self.page.get_by_role("heading", name="No bookings.")).to_be_visible()

        self.page.get_by_label("Show cancelled").check()
        self.page.locator("form.filters").get_by_role("button", name="Filter").click()
        row = self.page.get_by_role("row", name=re.compile("Sarah Jenkins"))
        expect(row).to_contain_text("cancelled")
        expect(row.get_by_role("link", name="View")).to_be_visible()

    def test_create_booking_from_bookings_page(self):
        self.page.goto("/bookings")
        self.page.get_by_role("link", name="+ New booking").click()
        form = self.page.locator("#create-booking form")
        form.get_by_label("Apartment").select_option(label="Studio · €90/night")
        form.get_by_label("Check-in").fill("2030-08-10")
        form.get_by_label("Check-out").fill("2030-08-12")
        expect(form.locator("[data-total]")).to_have_text("€180 (€90 × 2)")
        form.get_by_role("button", name="Create booking").click()

        expect(self.page).to_have_url(re.compile(r"/bookings/2$"))
        expect(self.page.get_by_role("heading", name="Studio")).to_be_visible()

    def test_change_booking(self):
        self.page.goto(f"/bookings/{self.booking['id']}")
        form = self.page.locator("form[data-flash='Booking changed']")
        form.get_by_label("Apartment").select_option(label="Studio · €90/night")
        form.get_by_label("Check-out").fill("2030-05-07")
        expect(form.locator("[data-total]")).to_have_text("€540 (€90 × 6)")
        form.get_by_role("button", name="Save changes").click()

        self.expect_toast("Booking changed")
        expect(self.page.get_by_text("6 nights").first).to_be_visible()
        changed = self.get_booking(self.booking["id"])
        self.assertEqual((changed["apartment_id"], changed["check_out"]), (self.studio["id"], "2030-05-07"))

    def test_reset_restores_original_values(self):
        self.page.goto(f"/bookings/{self.booking['id']}")
        form = self.page.locator("form[data-flash='Booking changed']")
        form.get_by_label("Check-out").fill("2030-05-20")
        form.get_by_role("button", name="Reset to original").click()
        expect(form.get_by_label("Check-out")).to_have_value("2030-05-05")
        expect(form.locator("[data-nights-label]")).to_have_text("4 nights · check-out exclusive")

    def test_keep_it_does_not_cancel(self):
        self.page.goto(f"/bookings/{self.booking['id']}")
        self.page.get_by_role("button", name="Cancel booking").click()
        dialog = self.page.locator("#confirm-dialog")
        expect(dialog).to_contain_text("Cancel booking #1 for Sarah Jenkins?")
        dialog.get_by_role("button", name="Keep it").click()

        expect(dialog).to_be_hidden()
        self.assertEqual(self.get_booking(self.booking["id"])["status"], "active")

    def test_cancel_booking(self):
        self.page.goto(f"/bookings/{self.booking['id']}")
        self.page.get_by_role("button", name="Cancel booking").click()
        self.page.locator("#confirm-dialog").get_by_role("button", name="Confirm").click()

        self.expect_toast("Booking cancelled")
        expect(self.page.get_by_text("This booking is cancelled and can no longer be changed.")).to_be_visible()
        expect(self.page.get_by_role("button", name="Save changes")).to_have_count(0)

        # The dates are free again, so the apartment can now be removed.
        self.page.get_by_role("link", name="Canal Loft").click()
        expect(self.page.get_by_role("button", name="Remove apartment")).to_be_enabled()


if __name__ == "__main__":
    unittest.main()
