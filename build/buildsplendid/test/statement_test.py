# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

# This file contains tests for the mid-level Makefile statement API.

from .. import makefile

import pymake.data
import unittest

class TestExpansions(unittest.TestCase):
    DUMMY_LOCATION = pymake.parserdata.Location('DUMMY', 1, 0)

    def test_to_str(self):
        se = pymake.data.StringExpansion('foo', self.DUMMY_LOCATION)
        e = makefile.Expansion(se)
        self.assertEqual(str(e), 'foo')
