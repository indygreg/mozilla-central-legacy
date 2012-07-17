# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

from mozbuild.cli.base import ArgumentProvider
from mozbuild.base import Base
from mozbuild.building.tiers import Tiers

class Build(Base, ArgumentProvider):
    def __init__(self, config):
        Base.__init__(self, config)

    def build(self):
        """Builds the tree."""

        from mozbuild.building.treebuilder import TreeBuilder
        from mozbuild.cli.terminal import BuildTerminal

        builder = TreeBuilder(self.config)
        terminal = BuildTerminal(self.log_manager)

        builder.build(on_update=terminal.update_progress)

    def tier(self, tier=None, subtier=None):
        """Perform an action on a specific tier."""

        from mozbuild.building.treebuilder import TreeBuilder

        builder = TreeBuilder(self.config)
        builder.build_tier(tier, subtier)

    def bxr(self, filename):
        from mozbuild.buildconfig.bxr import generate_bxr

        with open(filename, 'wb') as fh:
            generate_bxr(self.config, fh)

    @staticmethod
    def populate_argparse(parser):
        group = parser.add_parser('build',
                                  help='Build the tree.')

        group.set_defaults(cls=Build, method='build')

        tiers = Tiers()

        tier = parser.add_parser(
                   'tier',
                    help='Interacting with individual build tiers (ADVANCED).')

        tier.add_argument('tier', choices=tiers.get_tiers(),
                          help='The tier to interact with.')

        tier.add_argument('subtier', choices=tiers.get_actions(),
                default='default', nargs='?',
                help='Action to perform on tier.')

        tier.set_defaults(cls=Build, method='tier')

        bxr = parser.add_parser('bxr',
                                help='The Build Cross Reporter Tool.')

        bxr.set_defaults(cls=Build, method='bxr', filename='bxr.html')
