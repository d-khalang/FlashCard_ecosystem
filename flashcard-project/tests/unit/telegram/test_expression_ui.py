import unittest

from flashcard.telegram.ui.expression_lists import format_expression_list

class TestExpressionListsUI(unittest.TestCase):
    def test_empty_list(self):
        result = format_expression_list([])
        self.assertEqual(len(result), 1)
        self.assertIn("<b>📚 Flashcard Collection</b>", result[0])
        self.assertIn("don't have any flashcards yet", result[0])

    def test_default_mode(self):
        expressions = ["banana", "apple"] # Unsorted input
        result = format_expression_list(expressions)
        self.assertEqual(len(result), 1)
        content = result[0]
        
        # Check sorting
        apple_idx = content.find("apple")
        banana_idx = content.find("banana")
        self.assertLess(apple_idx, banana_idx)
        
        # Check fancy elements: section headers with bold letter
        self.assertIn("apple", content)
        self.assertIn("<b>A</b>", content)

    def test_plain_mode(self):
        expressions = ["banana", "apple"]
        # Plain mode with default alphabetical sort
        result = format_expression_list(expressions, plain=True)
        self.assertEqual(len(result), 1)
        content = result[0]
        
        # Check sorting
        apple_idx = content.find("apple")
        banana_idx = content.find("banana")
        self.assertLess(apple_idx, banana_idx)
        
        # Check NO fancy elements
        self.assertNotIn("▫️", content)
        self.assertNotIn("<b>A</b>", content)
        self.assertNotIn("━━━━━━━━━━━━━━━━", content)
        self.assertIn("apple\n", content)

    def test_no_sort_mode(self):
        expressions = ["banana", "apple"]
        # No alphabetical sort (mimicking -t)
        result = format_expression_list(expressions, sort_alphabetical=False)
        self.assertEqual(len(result), 1)
        content = result[0]
        
        # Check order PRESERVED
        apple_idx = content.find("apple")
        banana_idx = content.find("banana")
        self.assertLess(banana_idx, apple_idx) # Banana first
        
        # Check NO alphabetic grouping headers
        self.assertNotIn("<b>B</b>", content)

    def test_split_logic(self):
        # Create a list that will definitely exceed 4000 chars
        # 400 items of 10 chars = 4000 chars + overhead (emojis, tags) -> should trigger split
        expressions = [f"word_{i:04d}" for i in range(500)] 
        
        result = format_expression_list(expressions)
        
        self.assertTrue(len(result) > 1)
        
        # Verify content logic roughly
        total_content = "".join(result)
        self.assertIn("word_0000", total_content)
        self.assertIn("word_0499", total_content)

if __name__ == '__main__':
    unittest.main()
