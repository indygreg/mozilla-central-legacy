# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

import os.path
import unittest

def selftest():
    """Runs mozbuild unit tests."""

    test_dir = os.path.dirname(__file__)

    loader = unittest.TestLoader()
    suite = loader.discover(test_dir, pattern='*_test.py',
            top_level_dir=test_dir)

    unittest.TextTestRunner().run(suite)
