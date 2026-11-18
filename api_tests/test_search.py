from support import ApiTestCase, day, eventually


class AvailabilitySearchTests(ApiTestCase):
    """GET /api/apartments?from=&to= combines apartment and booking data."""

    def setUp(self):
        self.small = self.add_apartment(rooms=1)
        self.big = self.add_apartment(rooms=3)
        self.booking = self.booked(self.small["id"], day(6, 1), day(6, 5))

    def assertAvailable(self, check_in, check_out, expected, not_expected=(), **query):
        def check():
            ids = self.search(**{"from": check_in, "to": check_out, **query})
            for a in expected:
                self.assertIn(a["id"], ids)
            for a in not_expected:
                self.assertNotIn(a["id"], ids)
        eventually(check)

    def test_excludes_booked_apartments(self):
        self.assertAvailable(day(6, 3), day(6, 4), [self.big], [self.small])
        self.assertAvailable(day(5, 30), day(6, 2), [self.big], [self.small])

    def test_back_to_back_is_available(self):
        self.assertAvailable(day(6, 5), day(6, 7), [self.small, self.big])
        self.assertAvailable(day(5, 28), day(6, 1), [self.small, self.big])

    def test_min_rooms(self):
        self.assertAvailable(day(7, 1), day(7, 2), [self.big], [self.small], min_rooms=2)

    def test_cancelled_booking_does_not_block(self):
        self.patch(f"/api/bookings/{self.booking['id']}", {"status": "cancelled"})
        self.assertAvailable(day(6, 3), day(6, 4), [self.small, self.big])

    def test_moved_booking_frees_old_dates(self):
        self.patch(f"/api/bookings/{self.booking['id']}", {"check_in": day(6, 10), "check_out": day(6, 12)})
        self.assertAvailable(day(6, 3), day(6, 4), [self.small])
        self.assertAvailable(day(6, 10), day(6, 11), [self.big], [self.small])

    def test_results_have_full_apartment_fields_in_id_order(self):
        def check():
            r = self.get("/api/apartments", query={"from": day(7, 1), "to": day(7, 2)})
            self.assertEqual(r.status, 200)
            self.assertIn(self.big, r.json)
            ids = [a["id"] for a in r.json]
            self.assertEqual(ids, sorted(ids))
        eventually(check)

    def test_invalid_queries(self):
        cases = [
            ({"from": day(6, 1)}, "given together"),
            ({"to": day(6, 1)}, "given together"),
            ({"from": day(6, 5), "to": day(6, 1)}, "after check-in"),
            ({"from": day(6, 5), "to": day(6, 5)}, "after check-in"),
            ({"from": "yesterday", "to": day(6, 1)}, "Invalid date"),
            ({"from": day(6, 1), "to": day(6, 2), "min_rooms": "two"}, "must be an integer"),
        ]
        for query, message in cases:
            with self.subTest(query=query):
                self.assertError(self.get("/api/apartments", query=query), 400, "validation_error", message)
