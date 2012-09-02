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
    def default_state(self):
        config = MockConfig()
        sandbox = Sandbox(config)

        self.assertEqual(sandbox['TOPSRCDIR'], config.topsrdir)
        self.assertEqual(sandbox['TOPOBJDIR'], config.topobjdir)

        self.assertEqual(sandbox['MOZ_TRUE'], config.defines['MOZ_TRUE'])
        self.assertEqual(sandbox['MOZ_FOO'], config.substs['MOZ_FOO'])
