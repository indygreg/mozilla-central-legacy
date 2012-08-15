# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

from mach.base import ArgumentProvider
from mozbuild.base import Base
from mozbuild.building.tiers import Tiers


class Build(Base, ArgumentProvider):
    """Provides commands for interacting with the build system."""
    def build(self):
        """Builds the tree."""

        from mozbuild.building.treebuilder import TreeBuilder
        from mach.terminal import BuildTerminal

        builder = self._spawn(TreeBuilder)
        terminal = BuildTerminal(self.log_manager)

        builder.build(on_update=terminal.update_progress)

    def tier(self, tier=None, subtier=None):
        """Perform an action on a specific tier."""

        from mozbuild.building.treebuilder import TreeBuilder

        builder = self._spawn(TreeBuilder)
        builder.build_tier(tier, subtier)

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
