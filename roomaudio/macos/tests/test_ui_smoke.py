"""Browser smoke tests for RoomAudio UI, using mocked responses (no real recordings)."""
from datetime import datetime, timedelta
import json
import re
from pathlib import Path
import unittest
from urllib.parse import urlsplit

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # This is an optional end-to-end dependency.
    sync_playwright = None

INDEX = Path(__file__).resolve().parents[1] / "index.html"


@unittest.skipIf(sync_playwright is None, "Install Python playwright for browser smoke tests")
class RoomAudioUiSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        try:
            cls.browser = cls.pw.chromium.launch(headless=True)
        except Exception:
            cls.pw.stop()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def build_page(self, width=1280, online=True):
        now = datetime.now().replace(second=0, microsecond=0)
        # Align fixture across exactly one two-minute session boundary.
        start = now.replace(minute=(now.minute // 2) * 2) - timedelta(minutes=3)
        records = []
        for index in range(8):
            when = start + timedelta(seconds=15 * index)
            records.append({"name": when.strftime("%Y%m%dT%H%M%S") + ".mp3",
                            "time": when.isoformat(), "bytes": 40000, "token": "test-token"})
        phrases = [{"time": records[0]["time"], "text": "Первое сообщение тестового архива"},
                   {"time": records[3]["time"], "text": "Вторая фраза проверки поиска"}]
        context = self.browser.new_context(viewport={"width": width, "height": 844}, locale="ru-RU")
        page = context.new_page()
        errors = []
        unexpected_routes = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def route_handler(route):
            if route.request.url.startswith("blob:"):
                return route.fulfill(status=404, body="")  # WebKit synthetic media URL.
            path = urlsplit(route.request.url).path
            if path in ("/roomaudio", "/roomaudio/"):
                return route.fulfill(body=INDEX.read_text(encoding="utf-8"), content_type="text/html")
            if path.endswith("/api/status"):
                result = {"capture": {"client_connected": online, "mode": "continuous",
                                      "active_mode": "continuous" if online else "starting"},
                          "source_online": online, "audio_recent": online,
                          "asr_model_ready": True,
                          "asr": {"updated": int(now.timestamp()), "state": "idle", "pending": 0}}
            elif path.endswith("/api/live/status"):
                result = {"online": online}
            elif path.endswith("/api/recording-mode"):
                result = {"client_connected": online, "mode": "continuous",
                          "active_mode": "continuous" if online else "starting",
                          "client_last_seen": int(now.timestamp())}
            elif path.endswith("/api/archive/latest"):
                result = {"time": records[-1]["time"]}
            elif path.endswith("/api/archive/records"):
                result = {"items": records, "total": len(records), "minutes": {},
                          "audio_seconds": 120, "total_bytes": 320000}
            elif path.endswith("/api/archive/text"):
                result = {"items": phrases, "count": len(phrases)}
            elif path.endswith("/api/archive/speech"):
                result = {"items": []}
            elif path.endswith("/api/media-token"):
                result = {"token": "test-token", "expires_in": 3600}
            elif path.endswith("/api/archive/cleanup/trash"):
                result = {"batches": []}
            elif path.endswith(".png"):
                return route.fulfill(status=404, body="")  # Optional spectrogram.
            elif path.endswith(".mp3") or re.fullmatch(r"/[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", path):
                return route.fulfill(status=404, body="")  # No playback in fixture tests.
            else:
                unexpected_routes.append(path)
                return route.fulfill(status=404, body="")
            route.fulfill(body=json.dumps(result), content_type="application/json")

        page.route("**/*", route_handler)
        page.goto("http://roomaudio.test/roomaudio/", wait_until="domcontentloaded")
        page.wait_for_function("document.querySelector('#lastSeen').textContent.includes('Последняя связь:') && document.querySelector('#rangeStatus').textContent.includes('найдено') && !document.querySelector('#liveConnection').textContent.includes('Проверяем')")
        return context, page, errors, unexpected_routes

    def test_listening_first_and_archive_in_desktop_and_mobile(self):
        for width in (1280, 390):
            with self.subTest(width=width):
                context, page, errors, unexpected = self.build_page(width=width)
                try:
                    self.assertTrue(page.locator("#live-view").is_visible())
                    self.assertFalse(page.locator("#archive-view").is_visible())
                    self.assertFalse(page.locator("#archivePlayer").is_visible())
                    self.assertEqual(page.locator("[data-tab]").count(), 2)
                    self.assertEqual(page.locator("#liveConnection").inner_text(), "Эфир доступен")
                    self.assertFalse(page.evaluate("document.documentElement.scrollWidth > innerWidth"))
                    page.locator('[data-tab="archive"]').click()
                    self.assertTrue(page.locator("#archive-view").is_visible())
                    self.assertFalse(page.locator("#archivePlayer").is_visible())
                    self.assertEqual(page.locator(".record").count(), 2)
                    self.assertEqual(page.locator(".phrase").count(), 2)
                    page.locator(".record").first.click()
                    self.assertEqual(page.locator("#textHeading").inner_text(), "Текст выбранной записи")
                    self.assertTrue(page.locator("#archivePlayer").is_visible())
                    page.locator("#search").fill("Вторая")
                    self.assertEqual(page.locator(".phrase").count(), 1)
                    self.assertEqual(page.locator("#textHeading").inner_text(), "Результаты поиска")
                    page.locator("#search").fill("")
                    page.locator("#analysisTools > summary").click()
                    page.locator("#timeline").focus()
                    page.locator("#timeline").press("End")
                    self.assertEqual(page.locator("#timeline").get_attribute("aria-valuenow"), "7")
                    self.assertFalse(page.evaluate("document.documentElement.scrollWidth > innerWidth"))
                    page.locator('[data-tab="live"]').click()
                    self.assertFalse(page.locator("#archivePlayer").is_visible())
                    self.assertEqual(page.locator("#audio").get_attribute("src"), None)
                    page.locator('[data-tab="archive"]').click()
                    self.assertFalse(page.locator("#archivePlayer").is_visible())
                    self.assertEqual(errors, [])
                    self.assertEqual(unexpected, [])
                finally:
                    context.close()

    def test_mobile_webkit_safari_layout_and_state(self):
        try:
            browser = self.pw.webkit.launch(headless=True)
        except Exception as exc:
            self.skipTest("WebKit unavailable: " + str(exc)[:90])
        self.browser = browser
        try:
            for online in (True, False):
                with self.subTest(online=online):
                    context, page, errors, unexpected = self.build_page(390, online=online)
                    try:
                        self.assertEqual(page.locator("#liveConnection").inner_text(),
                                         "Эфир доступен" if online else "Источник недоступен")
                        self.assertEqual(page.locator("#recoverLive").is_visible(), not online)
                        page.locator('[data-tab="archive"]').click()
                        self.assertEqual(page.locator(".record").count(), 2)
                        self.assertFalse(page.locator("#archivePlayer").is_visible())
                        page.locator("#search").fill("Вторая")
                        self.assertEqual(page.locator(".phrase").count(), 1)
                        page.locator(".record").first.click()
                        self.assertTrue(page.locator("#archivePlayer").is_visible())
                        page.locator('[data-tab="live"]').click()
                        self.assertIsNone(page.locator("#audio").get_attribute("src"))
                        self.assertFalse(page.evaluate("document.documentElement.scrollWidth > innerWidth"))
                        self.assertEqual(errors, [])
                        self.assertEqual(unexpected, [])
                    finally:
                        context.close()
        finally:
            browser.close()

    def test_unavailable_source_shows_recovery_not_false_success(self):
        context, page, errors, unexpected = self.build_page(390, online=False)
        try:
            self.assertEqual(page.locator("#liveConnection").inner_text(), "Источник недоступен")
            self.assertTrue(page.locator("#recoverLive").is_visible())
            self.assertIn("Нет связи с Mate", page.locator("#sourceMessage").inner_text())
            self.assertIn("Mate пока не подтвердил", page.locator("#captureSummary").inner_text())
            self.assertEqual(errors, [])
            self.assertEqual(unexpected, [])
        finally:
            context.close()


if __name__ == "__main__":
    unittest.main()
