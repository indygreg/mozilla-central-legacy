# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

import unittest

from mozbuild.base import BuildConfig
from mozbuild.config import ConfigSettings

class TestBuildConfig(unittest.TestCase):
    def test_basic(self):
        c = ConfigSettings()
        c.register_provider(BuildConfig)

        c.build.optimized = True
