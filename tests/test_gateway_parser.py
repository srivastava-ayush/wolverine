import unittest

from agents.gateway import parse_command


class GatewayParserTest(unittest.TestCase):
    def test_issue_command(self):
        self.assertEqual(parse_command("fix issue #2 in srivastava-ayush/drawz"),
                         ("fix", "srivastava-ayush/drawz", 2))
        self.assertEqual(parse_command(" `Fix   issue 2 in srivastava-ayush/drawz.` "),
                         ("fix", "srivastava-ayush/drawz", 2))

    def test_pasted_url_and_code_fence(self):
        self.assertEqual(parse_command("https://github.com/srivastava-ayush/drawz/issues/2"),
                         ("fix", "srivastava-ayush/drawz", 2))
        self.assertEqual(parse_command("```text\nfix issue #2 in srivastava-ayush/drawz\n```"),
                         ("fix", "srivastava-ayush/drawz", 2))
        self.assertEqual(parse_command("Please relay this: fix issue #2 in srivastava-ayush/drawz — thanks"),
                         ("fix", "srivastava-ayush/drawz", 2))

    def test_approval_requires_full_hash(self):
        self.assertIsNone(parse_command("approve " + "a" * 32 + " short"))
        self.assertIsNone(parse_command("I already said approve " + "a" * 32 + " " + "b" * 64))
        address = "agent1q" + "c" * 58
        self.assertEqual(parse_command("@" + address + " approve " + "a" * 32 + " " + "b" * 64,
                                       address), ("approve", "a" * 32, "b" * 64))
        self.assertIsNone(parse_command("@agent1qother approve " + "a" * 32 + " " + "b" * 64,
                                        address))
        self.assertEqual(parse_command("show " + "a" * 32), ("show", "a" * 32))
        self.assertEqual(parse_command("Please show " + "a" * 32 + " and explain it."),
                         ("show", "a" * 32))


if __name__ == "__main__":
    unittest.main()
