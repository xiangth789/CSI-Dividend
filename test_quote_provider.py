
import unittest
from quote_provider import to_tencent_code, parse_tencent_quote_line, parse_tencent_quote_text

SAMPLE = 'v_sh600000="1~浦发银行~600000~9.59~9.37~9.37~1099035~723977~375059~9.58~504~9.57~1290~9.56~7319~9.55~4634~9.54~1336~9.59~21263~9.60~39283~9.61~6148~9.62~11163~9.63~5550~~20260610161426~0.22~2.35~9.59~9.34~9.59/1099035/1046292201~1099035~104629~0.33~6.35~~9.59~9.34~2.67~3194.03~3194.03~0.42~10.31~8.43~1.56";'

class TencentQuoteParserTests(unittest.TestCase):
    def test_market_code_mapping(self):
        self.assertEqual(to_tencent_code("600000"), "sh600000")
        self.assertEqual(to_tencent_code("000651"), "sz000651")
        self.assertEqual(to_tencent_code("159547"), "sz159547")

    def test_parses_realtime_core_fields(self):
        q = parse_tencent_quote_line(SAMPLE)
        self.assertEqual(q["code"], "600000")
        self.assertEqual(q["name"], "浦发银行")
        self.assertAlmostEqual(q["price"], 9.59)
        self.assertAlmostEqual(q["prev_close"], 9.37)
        self.assertAlmostEqual(q["change_pct"], 2.35)
        self.assertEqual(q["quote_time"], "2026-06-10 16:14:26")
        self.assertEqual(q["market_date"], "2026-06-10")
        self.assertAlmostEqual(q["high"], 9.59)
        self.assertAlmostEqual(q["low"], 9.34)

    def test_batch_text_returns_by_plain_code(self):
        d = parse_tencent_quote_text(SAMPLE)
        self.assertIn("600000", d)
        self.assertAlmostEqual(d["600000"]["price"], 9.59)

if __name__ == "__main__":
    unittest.main()
