import asyncio
import itertools
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import daftar_akun_fresh as daf  # noqa: E402

RESULT = ("✅ Akun berhasil didaftarkan\nUsername: user1\nPassword: pw1\nUserID: 1001\n"
          "Nomor: 6283000000001\ncsrftoken=abc; SPC_EC=xyz; SPC_U=1")


class Btn:
    def __init__(self, text, cb):
        self.text, self._cb = text, cb

    async def click(self):
        self._cb()


class Msg:
    def __init__(self, id, text, out=False, buttons=None):
        self.id, self.text, self.out, self.buttons = id, text, out, buttons


class FakeBot:
    """Meniru perilaku @shp_tools_bot (pesan di-edit di tempat, OTP diurus bot)."""

    def __init__(self, scenario):
        self.msgs, self.ids = [], itertools.count(1)
        self.sent, self.clicked, self.polls = [], [], 0
        self.attempt, self.scenario, self.phase = 0, scenario, None

    def add(self, text, out=False, buttons=None):
        m = Msg(next(self.ids), text, out, buttons)
        self.msgs.append(m)
        return m

    async def get_messages(self, bot, limit=10):
        self.polls += 1
        self._tick()
        return list(reversed(self.msgs))[:limit]

    async def send_message(self, bot, text):
        self.sent.append(text)
        m = self.add(text, out=True)
        if text == "/account":
            self.attempt += 1
            self.phase, self.wait_msg, self.t0 = "menu", None, self.polls
            self.menu = self.add("Menu akun", buttons=[[Btn("Daftar Akun", self._pick_register)]])
        return m

    def _pick_register(self):
        self.clicked.append("Daftar Akun")
        self.menu.text = "Pilih metode nomor"
        self.menu.buttons = [[Btn("Nomor Otomatis", self._pick_number)]]  # EDIT di tempat

    def _pick_number(self):
        self.clicked.append("Nomor Otomatis")
        self.phase, self.t0 = "otp", self.polls
        self.wait_msg = self.add("📱 Nomor: 628111\n⏳ Menunggu OTP masuk... (maks 61 detik)\n\n⚠️ Jangan pindah command sampai selesai.")

    def _pick_fp(self, label):
        self.clicked.append(label)
        if label == "Fingerprint Custom":
            self.add("Kirim fingerprint custom (paste di sini),\natau pakai salah satu dari stok tersimpan:",
                     buttons=[[Btn("Gunakan Fingerprint Tersimpan", self._use_stored)]])
            return
        self._finish_fp()

    def _use_stored(self):
        self.clicked.append("Gunakan Fingerprint Tersimpan")
        self._finish_fp()

    def _finish_fp(self):
        self.phase, self.t0 = "result", self.polls
        self.add("⏳ Memproses...")

    def _tick(self):
        dt = self.polls - self.t0
        if self.phase == "otp":
            if dt == 5:
                self.wait_msg.text = self.wait_msg.text.replace("(maks 61 detik)", "(maks 61 detik) · kirim ulang #1")
            if dt == 12:
                if self.scenario[self.attempt - 1] == "fail":
                    self.add("❌ OTP tak masuk di 2 nomor (masing-masing 2x kirim). Coba lagi /account.")
                    self.phase = "done"
                else:
                    self.add("✅ OTP terverifikasi. Nomor: 628111")
                    self.add("Pilih metode fingerprint:", buttons=[[
                        Btn("Fingerprint Otomatis", lambda: self._pick_fp("Fingerprint Otomatis")),
                        Btn("Fingerprint Custom", lambda: self._pick_fp("Fingerprint Custom"))]])
                    self.phase = "fp"
        elif self.phase == "result" and dt == 4:
            self.add(RESULT)
            self.phase = "done"


def run(scenario, **kw):
    bot = FakeBot(scenario)

    async def fast_sleep(_s, *a, **k):
        await real_sleep(0)

    real_sleep = asyncio.sleep
    with mock.patch("daftar_akun_fresh.asyncio.sleep", fast_sleep):
        res = asyncio.run(daf.register_one_account(bot, poll=0, **kw))
    return bot, res


class RegisterFlowTests(unittest.TestCase):
    def test_success_custom_clicks_button_and_sends_no_fingerprint(self):
        bot, (ok, reason, parsed) = run(["ok"], use_custom_fp=True)
        self.assertTrue(ok, reason)
        self.assertEqual(parsed["username"], "user1")
        self.assertEqual(bot.sent, ["/account"])  # tidak ada string fingerprint / OTP dikirim
        self.assertEqual(bot.clicked, ["Daftar Akun", "Nomor Otomatis", "Fingerprint Custom",
                                         "Gunakan Fingerprint Tersimpan"])

    def test_success_automatic_fingerprint(self):
        bot, (ok, _r, _p) = run(["ok"], use_custom_fp=False)
        self.assertTrue(ok)
        self.assertEqual(bot.clicked[-1], "Fingerprint Otomatis")

    def test_otp_failure_returns_false(self):
        bot, (ok, reason, _p) = run(["fail"])
        self.assertFalse(ok)
        self.assertIn("OTP tak masuk", reason)

    def test_batch_retries_from_account_until_target(self):
        bot = FakeBot(["fail", "fail", "ok"])

        async def fast_sleep(_s, *a, **k):
            await real_sleep(0)

        real_sleep = asyncio.sleep
        events = []
        orig = daf.register_one_account

        async def reg(client, **kw):
            return await orig(client, poll=0, **kw)

        with mock.patch("daftar_akun_fresh.asyncio.sleep", fast_sleep), \
             mock.patch("daftar_akun_fresh.register_one_account", reg), \
             mock.patch("daftar_akun_fresh.save_fresh_account"), \
             mock.patch("daftar_akun_fresh.save_failed_account"):
            out = asyncio.run(daf.run_register_fresh_batch(bot, total_target=1, on_event=events.append))
        self.assertEqual(out["success"], 1)
        self.assertEqual(out["fail"], 2)
        self.assertEqual(bot.sent.count("/account"), 3)
        self.assertEqual([e["type"] for e in events].count("attempt_fail"), 2)

    def test_classify(self):
        c = daf.classify_bot_text
        self.assertEqual(c("⏳ Menunggu OTP masuk... (maks 61 detik) · kirim ulang #1"), "waiting")
        self.assertEqual(c("✅ OTP terverifikasi. Nomor: 6285119299288"), "otp_ok")
        self.assertEqual(c("❌ OTP tak masuk di 2 nomor. Coba lagi /account."), "error")
        self.assertEqual(c(RESULT), "success")


if __name__ == "__main__":
    unittest.main()
