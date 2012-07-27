# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

import unittest

from mozbuild.compilation.warnings import WarningsCollector

CLANG_TESTS = [
    ('foobar.cpp:123:10: warning: you messed up [-Wfoo]',
     'foobar.cpp', 123, 10, 'you messed up', '-Wfoo')
]

MSVC_TESTS = [
    ("C:/mozilla-central/test/foo.cpp(793) : warning C4244: 'return' : "
     "conversion from 'double' to 'PRUint32', possible loss of data",
     'C:/mozilla-central/test/foo.cpp', 793, 'C4244',
     "'return' : conversion from 'double' to 'PRUint32', possible loss of data")
]

class TestWarningsParsing(unittest.TestCase):
    def test_clang_parsing(self):
        for source, filename, line, column, message, flag in CLANG_TESTS:
            collector = WarningsCollector(resolve_files=False)
            warning = collector.process_line(source)

            self.assertIsNotNone(warning)

            self.assertEqual(warning['filename'], filename)
            self.assertEqual(warning['line'], line)
            self.assertEqual(warning['column'], column)
            self.assertEqual(warning['message'], message)
            self.assertEqual(warning['flag'], flag)

        for source, filename, line, flag, message in MSVC_TESTS:
            collector = WarningsCollector(resolve_files=False)
            warning = collector.process_line(source)

            self.assertIsNotNone(warning)

            self.assertEqual(warning['filename'], filename)
            self.assertEqual(warning['line'], line)
            self.assertEqual(warning['flag'], flag)
            self.assertEqual(warning['message'], message)
