from mnxconverter.musicxml import get_score as get_score_from_musicxml
from mnxconverter.mnx import put_score as put_mnx_score
import os
import unittest

DATA_DIR = os.path.normpath(os.path.join('.', 'tests'))

class TestMetaclass(type):
    """
    Metaclass that adds a test method for every file in the 'tests' directory.
    """
    def __new__(cls, name, bases, attrs):
        def make_test_func(input_markup: bytes, expected_output: bytes):
            return lambda self: self.autotest(input_markup, expected_output)
        i = 0
        for root, dirs, files in os.walk(DATA_DIR):
            for f in files:
                if f.endswith('.musicxml'):
                    filename = f.split('.')[0] # Trim extension.
                    input_filename = os.path.join(root, filename + '.musicxml')
                    output_filename = os.path.join(root, filename + '.mnx')
                    func = make_test_func(
                        open(input_filename, 'rb').read(),
                        open(output_filename, 'rb').read()
                    )
                    func.__doc__ = filename
                    attrs['test_{0:03}'.format(i)] = func # Use '0:03' to make tests run in alphabetical order.
                    i += 1
        return type.__new__(cls, name, bases, attrs)

class FileformatTests(unittest.TestCase, metaclass=TestMetaclass):
    def autotest(self, input_markup: bytes, expected_output: bytes):
        score = get_score_from_musicxml(input_markup)
        self.assertEqual(put_mnx_score(score).strip(), expected_output.strip())

if __name__ == "__main__":
    unittest.main()
