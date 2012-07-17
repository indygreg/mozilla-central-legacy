# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

from mozbuild.base import Base
from mozbuild.testing.xpcshell import XPCShellRunner
from mozbuild.testing.mochitest import MochitestRunner

class Suite(Base):
    def __init__(self, config):
        Base.__init__(self, config)

    def run_suite(self, suite):

        xpcshell = XPCShellRunner(self.config)
        mochitest = MochitestRunner(self.config)

        if suite == 'all':
            xpcshell.run_suite()
            mochitest.run_plain_suite()
            mochitest.run_browser_chrome_suite()
            return

        if suite == 'xpcshell':
            xpcshell.run_suite()
            return

        if suite == 'mochitest-plain':
            mochitest.run_plain_suite()
            return

        if suite == 'mochitest-browser-chrome':
            mochitest.run_browser_chrome_suite()
            return

        raise Exception('Unknown test suite: %s' % suite)
