# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import unittest

from mozbuild.frontend.reader import Sandbox

# The build config class is not a reusable type, sadly. So, we have to mock it.
class MockConfig(object):
    def __init__(self):
        self.topsrcdir = '/path/to/topsrcdir'
        self.topobjdir = '/path/to/topobjdir'

        self.defines = {
            'MOZ_TRUE': 1,
            'MOZ_FALSE': 0,
        }

        self.substs = {
            'MOZ_FOO': 'foo',
            'MOZ_BAR': 'bar',
        }

class TestSandbox(unittest.TestCase):
    def sandbox(self):
        config = MockConfig()
        return Sandbox(config)

    def test_default_state(self):
        sandbox = self.sandbox()
        config = sandbox.config

        self.assertEqual(sandbox['TOPSRCDIR'], config.topsrcdir)
        self.assertEqual(sandbox['TOPOBJDIR'], config.topobjdir)

        self.assertIn('CONFIG', sandbox)
        self.assertEqual(sandbox['CONFIG']['MOZ_TRUE'], True)
        self.assertEqual(sandbox['CONFIG']['MOZ_FOO'], config.substs['MOZ_FOO'])

    def test_exec_source_success(self):
        sandbox = self.sandbox()

        sandbox.exec_source('foo = True', 'foo.py')

        self.assertNotIn('foo', sandbox)

    def test_exec_compile_error(self):
        sandbox = self.sandbox()

        with self.assertRaises(SyntaxError):
            sandbox.exec_source('2f23;k;asfj', 'foo.py')
