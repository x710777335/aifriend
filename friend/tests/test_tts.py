import unittest

from companion.audio.tts import text_for_speech


class TtsTextTests(unittest.TestCase):
    def test_markdown_hash_and_asterisk_are_not_spoken(self) -> None:
        self.assertEqual(text_for_speech("# 标题 *重点*"), " 标题 重点")


if __name__ == "__main__":
    unittest.main()
