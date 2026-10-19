"""Offline parser regression tests; standard library only, no CDP import."""
import ast
from pathlib import Path
import re
import unicodedata
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "engine.py"
SOURCE_BYTES = SOURCE.read_bytes()
tree = ast.parse(SOURCE_BYTES, filename=str(SOURCE))
engine = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "MuseEngine")
parser = next(n for n in engine.body if isinstance(n, ast.FunctionDef) and n.name == "_parse_quota")
# Compile the actual method unchanged. Avoid importing browser dependencies or
# constructing an engine, which could otherwise create profile directories.
subset = ast.Module(body=[ast.ClassDef(name="MuseEngine", bases=[], keywords=[],
                                     body=[parser], decorator_list=[])], type_ignores=[])
namespace = {"re": re, "unicodedata": unicodedata}
exec(compile(ast.fix_missing_locations(subset), str(SOURCE), "exec"), namespace)
parse = namespace["MuseEngine"]._parse_quota


class QuotaLocalizationTests(unittest.TestCase):
    def fields(self, text, **expected):
        result = parse(text)
        for key, value in expected.items():
            self.assertEqual(result.get(key), value, (key, result))
        return result

    def test_traditional_example(self):
        text = ("設定\n一般\nMeta 帳戶\n用量\n免費計劃\n"
                "每星期上限會於 10月30日重設\n已用 7%\n額外的符元\n永不過期\n"
                "已使用 0%（剩餘 20\u00a0億個憑證）\n升級\n語言\n外觀")
        result = self.fields(text, found=True, plan="免費計劃",
                             weekly_reset="10月30日", weekly_used_pct=7,
                             extra_used_pct=0, extra_expires="never",
                             extra_left="剩餘 20 億個憑證")
        self.assertNotIn("Meta 帳戶", result["raw"])
        self.assertNotIn("語言", result["raw"])

    def test_original_english(self):
        self.fields("Settings\nGeneral\nUsage\nFree plan\nWeekly limit resets on Sep 30\n"
                    "1% used\nAdditional tokens\nNever expires\n0% used (2B tokens left)\nLanguage",
                    found=True, plan="Free plan", weekly_reset="Sep 30",
                    weekly_used_pct=1, extra_used_pct=0, extra_expires="never",
                    extra_left="2B tokens left")

    def test_simplified_example(self):
        self.fields("设置\n用量\n免费计划\n每周上限将于 10月22日重置\n已使用 12.5%\n"
                    "额外令牌\n永不过期\n已使用 0%（剩余 20 亿令牌）\n语言",
                    found=True, plan="免费计划", weekly_reset="10月22日",
                    weekly_used_pct=12.5, extra_used_pct=0, extra_expires="never",
                    extra_left="剩余 20 亿令牌")

    def test_zero_is_success_and_integer(self):
        for text in ["0% used", "已用 0%", "已使用 0%", "已用 ０％"]:
            with self.subTest(text=text):
                result = self.fields(text, found=True, weekly_used_pct=0)
                self.assertIs(type(result["weekly_used_pct"]), int)

    def test_decimal_percentages(self):
        for text in ["12.75% used", "已用 12.75%", "已使用 １２．７５％"]:
            with self.subTest(text=text):
                self.fields(text, found=True, weekly_used_pct=12.75)

    def test_plan_only_is_not_success(self):
        for plan in ["Free plan", "免費計劃", "免费计划", "免費方案"]:
            with self.subTest(plan=plan):
                result = self.fields(plan, found=False, plan=plan)
                self.assertNotIn("weekly_used_pct", result)

    def test_extra_only_is_not_weekly_usage(self):
        for text in ["Usage\nFree plan\nAdditional tokens\nNever expires\n0% used (2B tokens left)",
                     "用量\n免費計劃\n額外的符元\n永不過期\n已使用 0%（剩餘 20 億個憑證）",
                     "用量\n免费计划\n额外令牌\n永不过期\n已使用 20%（剩余 10 亿令牌）",
                     "Usage\nExtra tokens\n7.5% used (10 tokens left)"]:
            with self.subTest(text=text):
                result = self.fields(text, found=False)
                self.assertNotIn("weekly_used_pct", result)
                self.assertIn("extra_used_pct", result)

    def test_unrelated_and_empty_text(self):
        for text in ["", None, "Settings\nGeneral", "Upgrade\n100% discount"]:
            with self.subTest(text=text):
                self.fields(text, found=False)

    def test_profile_and_language_are_excluded(self):
        result = self.fields("Profile\n99% used\nUsage\nFree plan\n0% used\nLanguage\n88% used",
                             found=True, weekly_used_pct=0)
        self.assertNotIn("99%", result["raw"])
        self.assertNotIn("88%", result["raw"])

    def test_percentage_upper_bound(self):
        self.fields("101% used", found=False)
        self.fields("100% used", found=True, weekly_used_pct=100)


if __name__ == "__main__":
    unittest.main(verbosity=2)
