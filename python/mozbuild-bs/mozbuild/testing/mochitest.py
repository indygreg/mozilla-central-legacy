# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

import os.path

from mozbuild.base import Base

class MochitestRunner(Base):
    def __init__(self, config):
        Base.__init__(self, config)

    def run_plain_suite(self):
        """Runs all plain mochitests."""
        # TODO hook up harness runner.
        self._run_make(directory='.', target='mochitest-plain')

    def run_browser_chrome_suite(self):
        """Runs browser chrome mochitests."""
        # TODO hook up harness.
        self._run_make(directory='.', target='mochitest-browser-chrome')

    def run_mochitest_test(self, test_file=None, plain=False, chrome=False,
            browser=False):
        if test_file is None:
            raise Exception('test_file must be defined.')

        if test_file == 'all':
            self.run_plain_suite()
            return

        parsed = self._parse_test_path(test_file)

        # TODO hook up harness via native Python
        target = None
        if plain:
            target = 'mochitest-plain'
        elif chrome:
            target = 'mochitest-chrome'
        elif browser:
            target = 'mochitest-browser-chrome'
        else:
            raise Exception('No mochitest flavor defined.')

        env = {'TEST_PATH': parsed['normalized']}

        self._run_make(directory='.', target=target, env=env)

    def _parse_test_path(self, test_path):
        if os.path.isdir(test_path) and not test_path.endswith(os.path.sep):
            test_path += os.path.sep

        normalized = test_path

        if test_path.startswith(self.srcdir):
            normalized = test_path[len(self.srcdir):]

        return {
            'normalized': normalized,
            'is_dir': os.path.isdir(test_path)
        }
