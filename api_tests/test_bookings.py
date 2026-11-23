from support import ApiTestCase, day, unique

# An apartment ID no test ever creates.
NEVER_EXISTED = 999_999_999


class CreateBookingTests(ApiTestCase):
    def setUp(self):
        self.apt = self.add_apartment()

    def test_create_returns_201_with_location_and_body(self):
        r = self.book(self.apt["id"], day(1, 1), day(1, 5), guest="Ann")
        self.assertEqual(r.status, 201, r.body)
        self.assertLocation(r, f"/api/bookings/{r.json['id']}")
        self.assertEqual({k: v for k, v in r.json.items() if k != "id"},
                         {"apartment_id": self.apt["id"], "guest": "Ann",
                          "check_in": day(1, 1), "check_out": day(1, 5), "status": "active"})
        self.assertEqual(self.get(f"/api/bookings/{r.json['id']}").json, r.json)

    def test_booking_right_after_creating_the_apartment(self):
        # Must work immediately, even once apartment data reaches bookings via events.
        fresh = self.add_apartment()
        self.assertEqual(self.book(fresh["id"], day(1, 1), day(1, 2)).status, 201)

    def test_guest_is_optional_and_trimmed(self):
        r = self.post("/api/bookings", {"apartment_id": self.apt["id"],
                                        "check_in": day(1, 1), "check_out": day(1, 2)})
        self.assertEqual((r.status, r.json["guest"]), (201, ""))
        r = self.book(self.apt["id"], day(1, 2), day(1, 3), guest="  Bob  ")
        self.assertEqual(r.json["guest"], "Bob")

    def test_overlap_is_409(self):
        first = self.booked(self.apt["id"], day(1, 1), day(1, 5))
        r = self.book(self.apt["id"], day(1, 4), day(1, 6))
        self.assertError(r, 409, "conflict", "already booked")
        self.assertIn(f"booking {first['id']}", r.json["error"]["message"])
        self.assertError(self.book(self.apt["id"], day(1, 2), day(1, 3)), 409, "conflict")
        self.assertError(self.book(self.apt["id"], day(1, 1), day(1, 5)), 409, "conflict")

    def test_back_to_back_and_other_apartment_allowed(self):
        other = self.add_apartment()
        self.booked(self.apt["id"], day(1, 5), day(1, 10))
        self.assertEqual(self.book(self.apt["id"], day(1, 10), day(1, 12)).status, 201)
        self.assertEqual(self.book(self.apt["id"], day(1, 1), day(1, 5)).status, 201)
        self.assertEqual(self.book(other["id"], day(1, 5), day(1, 10)).status, 201)

    def test_unknown_apartment_is_404(self):
        # An ID that never existed, not a just-deleted apartment: the booking
        # side learns about deletions through events, so for a moment after a
        # delete it may still accept the apartment (a documented trade-off).
        self.assertError(self.book(NEVER_EXISTED, day(1, 1), day(1, 5)),
                         404, "not_found", f"Apartment {NEVER_EXISTED}")

    def test_validation_errors(self):
        a = self.apt["id"]
        self.assertError(self.book(a, day(1, 5), day(1, 5)), 400, "validation_error", "after check-in")
        self.assertError(self.book(a, day(1, 5), day(1, 1)), 400, "validation_error", "after check-in")
        self.assertError(self.book(a, f"{2098}-13-01", day(1, 5)), 400, "validation_error", "Invalid date")
        self.assertError(self.book(a, "soon", day(1, 5)), 400, "validation_error", "Invalid date")
        self.assertError(self.book(str(a), day(1, 1), day(1, 5)), 400, "validation_error", "must be an integer")
        self.assertError(self.post("/api/bookings", {"apartment_id": a}),
                         400, "validation_error", "check_in, check_out")
        self.assertError(self.post("/api/bookings", {"apartment_id": a, "check_in": day(1, 1),
                                                     "check_out": day(1, 2), "status": "active"}),
                         400, "validation_error", "Unknown field(s): status")
        self.assertError(self.post("/api/bookings", data=b"x", content_type="text/plain"),
                         415, "unsupported_media_type")


class ReadBookingTests(ApiTestCase):
    def test_unknown_booking_is_404(self):
        self.assertError(self.get("/api/bookings/999999999"), 404, "not_found", "Booking 999999999")
        self.assertError(self.patch("/api/bookings/999999999", {"status": "cancelled"}), 404, "not_found")

    def test_list_filters(self):
        apt1, apt2 = self.add_apartment(), self.add_apartment()
        ann, bob = unique("Ann"), unique("Bob")
        b1 = self.booked(apt1["id"], day(2, 10), day(2, 12), guest=ann)
        b2 = self.booked(apt2["id"], day(2, 1), day(2, 3), guest=bob)
        b3 = self.booked(apt1["id"], day(2, 1), day(2, 3), guest=bob)
        self.patch(f"/api/bookings/{b3['id']}", {"status": "cancelled"})
        mine = {b1["id"], b2["id"], b3["id"]}

        def ids(**query):
            r = self.get("/api/bookings", query=query)
            self.assertEqual(r.status, 200, r.body)
            return [b["id"] for b in r.json if b["id"] in mine]

        # Sorted by check-in date, then id; cancelled bookings hidden by default.
        self.assertEqual(ids(), [b2["id"], b1["id"]])
        self.assertEqual(ids(include_cancelled="true"), [b2["id"], b3["id"], b1["id"]])
        self.assertEqual(ids(apartment_id=apt1["id"]), [b1["id"]])
        self.assertEqual(ids(apartment_id=apt1["id"], include_cancelled="true"), [b3["id"], b1["id"]])
        self.assertEqual(ids(guest=bob.upper(), include_cancelled="true"), [b2["id"], b3["id"]])
        r = self.get("/api/bookings", query={"guest": bob, "include_cancelled": "true"})
        self.assertEqual({b["id"] for b in r.json}, {b2["id"], b3["id"]})

    def test_list_filter_validation(self):
        self.assertError(self.get("/api/bookings", query={"include_cancelled": "yes"}),
                         400, "validation_error", "'true' or 'false'")
        self.assertError(self.get("/api/bookings", query={"apartment_id": "x"}),
                         400, "validation_error", "must be an integer")


class ChangeBookingTests(ApiTestCase):
    def setUp(self):
        self.apt = self.add_apartment()
        self.other = self.add_apartment()
        self.b = self.booked(self.apt["id"], day(4, 1), day(4, 5))

    def url(self, booking=None):
        return f"/api/bookings/{(booking or self.b)['id']}"

    def test_change_dates(self):
        r = self.patch(self.url(), {"check_in": day(4, 3), "check_out": day(4, 8)})
        self.assertEqual(r.status, 200, r.body)
        self.assertEqual((r.json["check_in"], r.json["check_out"]), (day(4, 3), day(4, 8)))
        self.assertEqual(self.get(self.url()).json, r.json)

    def test_change_only_one_date(self):
        r = self.patch(self.url(), {"check_out": day(4, 7)})
        self.assertEqual((r.json["check_in"], r.json["check_out"]), (day(4, 1), day(4, 7)))

    def test_move_to_other_apartment_and_rename_guest(self):
        r = self.patch(self.url(), {"apartment_id": self.other["id"], "guest": "Bob"})
        self.assertEqual(r.status, 200, r.body)
        self.assertEqual((r.json["apartment_id"], r.json["guest"]), (self.other["id"], "Bob"))
        # The old apartment is free again for those dates.
        self.assertEqual(self.book(self.apt["id"], day(4, 1), day(4, 5)).status, 201)

    def test_change_into_other_booking_is_409(self):
        nxt = self.booked(self.apt["id"], day(4, 5), day(4, 8))
        r = self.patch(self.url(), {"check_out": day(4, 6)})
        self.assertError(r, 409, "conflict", f"booking {nxt['id']}")
        self.assertEqual(self.get(self.url()).json, self.b)

    def test_move_onto_booked_apartment_is_409(self):
        self.booked(self.other["id"], day(4, 2), day(4, 3))
        self.assertError(self.patch(self.url(), {"apartment_id": self.other["id"]}), 409, "conflict")

    def test_change_does_not_conflict_with_itself(self):
        r = self.patch(self.url(), {"check_in": day(4, 2), "check_out": day(4, 4)})
        self.assertEqual(r.status, 200, r.body)

    def test_change_validation(self):
        self.assertError(self.patch(self.url(), {"check_out": day(4, 1)}),
                         400, "validation_error", "after check-in")
        self.assertError(self.patch(self.url(), {"check_in": "nope"}), 400, "validation_error", "Invalid date")
        self.assertError(self.patch(self.url(), {"apartment_id": NEVER_EXISTED}), 404, "not_found")
        self.assertEqual(self.get(self.url()).json, self.b)


class CancelBookingTests(ApiTestCase):
    def setUp(self):
        self.apt = self.add_apartment()
        self.b = self.booked(self.apt["id"], day(5, 1), day(5, 5))
        self.url = f"/api/bookings/{self.b['id']}"

    def test_cancel_frees_the_dates(self):
        r = self.patch(self.url, {"status": "cancelled"})
        self.assertEqual((r.status, r.json), (200, {**self.b, "status": "cancelled"}))
        self.assertEqual(self.book(self.apt["id"], day(5, 1), day(5, 5)).status, 201)

    def test_cancelled_booking_cannot_change_or_cancel_again(self):
        self.patch(self.url, {"status": "cancelled"})
        self.assertError(self.patch(self.url, {"status": "cancelled"}), 409, "conflict", "already cancelled")
        self.assertError(self.patch(self.url, {"guest": "Bob"}), 409, "conflict", "cannot be changed")
        self.assertEqual(self.get(self.url).json["status"], "cancelled")

    def test_invalid_status_changes(self):
        self.assertError(self.patch(self.url, {"status": "active"}),
                         400, "validation_error", "only be set to 'cancelled'")
        self.assertError(self.patch(self.url, {"status": "cancelled", "guest": "Bob"}),
                         400, "validation_error", "cannot be combined")
        self.assertEqual(self.get(self.url).json, self.b)
