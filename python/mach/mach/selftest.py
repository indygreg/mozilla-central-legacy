# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

from ..base import Base
from .base import ArgumentProvider

class SelfTest(Base, ArgumentProvider):
    def __init__(self, config):
        Base.__init__(self, config)

    def unittest(self):
        """Run unit tests against ourself."""

        from ..test.selftest import selftest
        selftest()

    @staticmethod
    def populate_argparse(parser):
        selftest = parser.add_parser('selftest',
                help='Have mach test itself.')
        selftest.set_defaults(cls=SelfTest, method='unittest')
