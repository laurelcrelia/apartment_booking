from support import ApiTestCase


class MetaTests(ApiTestCase):
    def test_health(self):
        r = self.get("/api/health")
        self.assertEqual((r.status, r.json), (200, {"status": "ok"}))

    def test_openapi_spec_is_served(self):
        r = self.get("/api/openapi.yaml")
        self.assertEqual(r.status, 200)
        self.assertEqual(r.content_type, "application/yaml")
        self.assertIn(b"openapi: 3.0.3", r.body)

    def test_unknown_api_path_is_json_404(self):
        self.assertError(self.get("/api/nothing-here"), 404, "not_found")
        self.assertError(self.get("/api/apartments/abc"), 404, "not_found")

    def test_wrong_method_is_json_405(self):
        self.assertError(self.patch("/api/apartments", {}), 405, "method_not_allowed")
        self.assertError(self.delete("/api/bookings"), 405, "method_not_allowed")
