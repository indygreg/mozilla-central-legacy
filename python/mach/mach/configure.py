# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

# This module provides interfaces for interacting with configure.

from mozbuild.base import Base
from mach.base import ArgumentProvider


class Configure(Base, ArgumentProvider):
    """Provides commands for interacting with configure."""
    def __init__(self, settings, log_manager):
        Base.__init__(self, settings, log_manager)

    def configure(self):
        from mozbuild.configuration.configure import Configure

        c = self._spawn(Configure)

        if not c.ensure_configure():
            c.run_configure()

    @staticmethod
    def populate_argparse(parser):
        group = parser.add_parser('configure',
                                  help="Interact with autoconf.")

        group.set_defaults(cls=Configure, method="configure")
