from support import ApiTestCase, day, unique


class CreateApartmentTests(ApiTestCase):
    def test_create_returns_201_with_location_and_body(self):
        name = unique("Loft")
        r = self.post("/api/apartments", {"name": name, "address": "1 Beach Rd", "rooms": 2, "price": 80})
        self.assertEqual(r.status, 201, r.body)
        self.addCleanup(self._remove_apartment, r.json["id"])
        self.assertIsInstance(r.json["id"], int)
        self.assertLocation(r, f"/api/apartments/{r.json['id']}")
        self.assertEqual({k: v for k, v in r.json.items() if k != "id"},
                         {"name": name, "address": "1 Beach Rd", "rooms": 2, "price": 80})

    def test_defaults(self):
        a = self.add_apartment()
        self.assertEqual((a["rooms"], a["price"]), (1, 0.0))

    def test_name_is_trimmed(self):
        name = unique("Loft")
        a = self.add_apartment(name=f"  {name}  ")
        self.assertEqual(a["name"], name)

    def test_ids_are_not_reused_after_delete(self):
        first = self.add_apartment()
        self.assertEqual(self.delete(f"/api/apartments/{first['id']}").status, 204)
        second = self.add_apartment()
        self.assertGreater(second["id"], first["id"])

    def test_validation_errors(self):
        cases = [
            ({"address": "x"}, "Missing required field(s): name"),
            ({"name": "A"}, "Missing required field(s): address"),
            ({"name": " ", "address": "x"}, "name is required"),
            ({"name": "A", "address": "x", "rooms": 0}, "at least 1"),
            ({"name": "A", "address": "x", "rooms": 1.5}, "'rooms' must be an integer"),
            ({"name": "A", "address": "x", "rooms": True}, "'rooms' must be an integer"),
            ({"name": "A", "address": "x", "price": -1}, "cannot be negative"),
            ({"name": "A", "address": "x", "price": "10"}, "'price' must be a number"),
            ({"name": 5, "address": "x"}, "'name' must be a string"),
            ({"name": "A", "address": "x", "colour": "red"}, "Unknown field(s): colour"),
        ]
        for body, message in cases:
            with self.subTest(body=body):
                self.assertError(self.post("/api/apartments", body), 400, "validation_error", message)

    def test_body_must_be_a_json_object(self):
        r = self.post("/api/apartments", data=b"name=Loft",
                      content_type="application/x-www-form-urlencoded")
        self.assertError(r, 415, "unsupported_media_type")
        r = self.post("/api/apartments", data=b"{not json", content_type="application/json")
        self.assertError(r, 400, "validation_error", "JSON object")
        self.assertError(self.post("/api/apartments", ["Loft"]), 400, "validation_error", "JSON object")


class ReadApartmentTests(ApiTestCase):
    def test_get(self):
        a = self.add_apartment(rooms=3, price=120.5)
        r = self.get(f"/api/apartments/{a['id']}")
        self.assertEqual((r.status, r.json), (200, a))

    def test_get_unknown_is_404(self):
        a = self.add_apartment()
        self.delete(f"/api/apartments/{a['id']}")
        self.assertError(self.get(f"/api/apartments/{a['id']}"), 404, "not_found", f"Apartment {a['id']}")

    def test_list_contains_created_in_id_order(self):
        a = self.add_apartment()
        b = self.add_apartment()
        r = self.get("/api/apartments")
        self.assertEqual(r.status, 200)
        listed = {x["id"]: x for x in r.json}
        self.assertEqual((listed[a["id"]], listed[b["id"]]), (a, b))
        ids = [x["id"] for x in r.json]
        self.assertEqual(ids, sorted(ids))

    def test_min_rooms_filter(self):
        small = self.add_apartment(rooms=1)
        big = self.add_apartment(rooms=3)
        ids = self.search(min_rooms=2)
        self.assertIn(big["id"], ids)
        self.assertNotIn(small["id"], ids)
        self.assertTrue(all(a["rooms"] >= 2 for a in self.get("/api/apartments", query={"min_rooms": 2}).json))

    def test_invalid_min_rooms(self):
        self.assertError(self.get("/api/apartments", query={"min_rooms": "two"}),
                         400, "validation_error", "must be an integer")
        self.assertError(self.get("/api/apartments", query={"min_rooms": 0}),
                         400, "validation_error", "at least 1")


class UpdateApartmentTests(ApiTestCase):
    def test_patch_changes_only_sent_fields(self):
        a = self.add_apartment(rooms=2, price=80)
        r = self.patch(f"/api/apartments/{a['id']}", {"price": 95.5})
        self.assertEqual(r.status, 200, r.body)
        self.assertEqual(r.json, {**a, "price": 95.5})
        self.assertEqual(self.get(f"/api/apartments/{a['id']}").json, r.json)

    def test_patch_all_fields(self):
        a = self.add_apartment()
        name = unique("Studio")
        r = self.patch(f"/api/apartments/{a['id']}",
                       {"name": name, "address": "2 Side St", "rooms": 4, "price": 10})
        self.assertEqual(r.json, {"id": a["id"], "name": name, "address": "2 Side St",
                                  "rooms": 4, "price": 10})

    def test_patch_validation(self):
        a = self.add_apartment()
        cases = [
            ({"name": "  "}, "cannot be empty"),
            ({"rooms": 0}, "at least 1"),
            ({"price": -5}, "cannot be negative"),
            ({"rooms": "2"}, "'rooms' must be an integer"),
            ({"id": 9}, "Unknown field(s): id"),
        ]
        for body, message in cases:
            with self.subTest(body=body):
                self.assertError(self.patch(f"/api/apartments/{a['id']}", body),
                                 400, "validation_error", message)
        self.assertEqual(self.get(f"/api/apartments/{a['id']}").json, a)

    def test_patch_unknown_is_404(self):
        a = self.add_apartment()
        self.delete(f"/api/apartments/{a['id']}")
        self.assertError(self.patch(f"/api/apartments/{a['id']}", {"price": 1}), 404, "not_found")


class DeleteApartmentTests(ApiTestCase):
    def test_delete(self):
        a = self.add_apartment()
        r = self.delete(f"/api/apartments/{a['id']}")
        self.assertEqual((r.status, r.body), (204, b""))
        self.assertEqual(self.get(f"/api/apartments/{a['id']}").status, 404)
        self.assertNotIn(a["id"], [x["id"] for x in self.get("/api/apartments").json])

    def test_delete_unknown_is_404(self):
        a = self.add_apartment()
        self.delete(f"/api/apartments/{a['id']}")
        self.assertError(self.delete(f"/api/apartments/{a['id']}"), 404, "not_found")

    def test_delete_with_active_booking_is_409(self):
        a = self.add_apartment()
        b = self.booked(a["id"], day(3, 1), day(3, 5))
        self.assertError(self.delete(f"/api/apartments/{a['id']}"), 409, "conflict", "active bookings")
        self.assertEqual(self.get(f"/api/apartments/{a['id']}").status, 200)
        self.assertIn(str(b["id"]), self.delete(f"/api/apartments/{a['id']}").json["error"]["message"])

    def test_delete_after_cancelling_bookings(self):
        a = self.add_apartment()
        b = self.booked(a["id"], day(3, 1), day(3, 5))
        self.patch(f"/api/bookings/{b['id']}", {"status": "cancelled"})
        self.assertEqual(self.delete(f"/api/apartments/{a['id']}").status, 204)
