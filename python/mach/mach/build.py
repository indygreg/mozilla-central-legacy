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

    def backendconfig(self, backend):
        from mozbuild.backend.manager import BackendManager

        manager = self._spawn(BackendManager)
        manager.set_backend(backend)
        manager.generate()

    def tier(self, tier=None, subtier=None):
        """Perform an action on a specific tier."""

        from mozbuild.building.treebuilder import TreeBuilder

        builder = self._spawn(TreeBuilder)
        builder.build_tier(tier, subtier)

    def bxr(self, filename, load_all=False, load_from_make=False):
        from mozbuild.buildconfig.bxr import generate_bxr

        with open(filename, 'wb') as fh:
            generate_bxr(self.config, fh, load_all=load_all,
                load_from_make=load_from_make)

    @staticmethod
    def populate_argparse(parser):
        build = parser.add_parser('build',
            help='Build the tree.')

        build.set_defaults(cls=Build, method='build')

        backendconfig = parser.add_parser('backendconfig',
            help='Perform build backend configuration')

        backends = set(['legacy', 'reformat', 'hybridmake'])
        backendconfig.add_argument('backend', default='hybridmake',
            choices=backends, nargs='?',
            help='Build backend to use.')

        backendconfig.set_defaults(cls=Build, method='backendconfig')

        bxr = parser.add_parser('bxr',
            help='The Build Cross Reporter Tool.')
        bxr.add_argument('--all', default=False, action='store_true',
            dest='load_all',
            help='Load all files, not just autoconf configured ones.')
        bxr.add_argument('--make', default=False, action='store_true',
            dest='load_from_make',
            help='Load files by discovering through the root Makefile.in')

        bxr.set_defaults(cls=Build, method='bxr', filename='bxr.html')

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
