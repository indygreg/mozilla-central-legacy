# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

# This module provides interfaces for interacting with configure.

from mozbuild.base import Base
from mozbuild.cli.base import ArgumentProvider

class Configure(Base, ArgumentProvider):
    def __init__(self, config):
        Base.__init__(self, config)

    def configure(self):
        from mozbuild.configuration.configure import Configure

        c = Configure(self.config)

        if not c.ensure_configure():
            c.run_configure()

    @staticmethod
    def populate_argparse(parser):
        group = parser.add_parser('configure',
                                  help="Interact with autoconf.")

        group.set_defaults(cls=Configure, method="configure")
