# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

from mozbuild.cli.base import ArgumentProvider
from mozbuild.base import Base

class BuildConfig(Base, ArgumentProvider):
    def __init__(self, config):
        Base.__init__(self, config)

    def bxr(self, filename):
        from mozbuild.buildconfig.bxr import generate_bxr

        with open(filename, 'wb') as fh:
            generate_bxr(self.config, fh)

    def buildinfo(self):
        from mozbuild.buildconfig.frontend import BuildFrontend

        frontend = BuildFrontend(self.config)
        frontend.load_autoconf_input_files()

        tree = frontend.get_tree_info()

        print tree

    def generate(self, backend):
        from mozbuild.buildconfig.frontend import BuildFrontend

        frontend = BuildFrontend(self.config)
        frontend.load_autoconf_input_files()
        be = self.backend_from_name(backend, frontend)
        be.generate()

    def build(self, backend):
        from mozbuild.buildconfig.frontend import BuildFrontend

        frontend = BuildFrontend(self.config)
        frontend.load_autoconf_input_files()

        be = self.backend_from_name(backend, frontend)
        be.build()

    def backend_from_name(self, name, frontend):
        from mozbuild.buildconfig.backend.legacy import LegacyBackend
        from mozbuild.buildconfig.backend.hybridmake import HybridMakeBackend

        if name == 'legacy':
            return LegacyBackend(frontend)
        elif name == 'reformat':
            backend = LegacyBackend(frontend)
            backend.reformat = True
            backend.verify_reformat = True

            return backend
        elif name == 'hybridmake':
            return HybridMakeBackend(frontend)
        else:
            raise Exception('Unknown backend format: %s' % backend)

    @staticmethod
    def populate_argparse(parser):
        bxr = parser.add_parser('bxr',
            help='The Build Cross Reporter Tool.')

        bxr.set_defaults(cls=BuildConfig, method='bxr', filename='bxr.html')

        buildinfo = parser.add_parser('buildinfo',
            help='Generate a machine-readable document describing the build.')
        buildinfo.set_defaults(cls=BuildConfig, method='buildinfo')

        bb = parser.add_parser('buildconfig',
            help='Configure build backend.')
        backends = set(['legacy', 'reformat', 'hybridmake'])

        bb.add_argument('backend', default='legacy', choices=backends,
            nargs='?', help='Backend files to generate.')

        bb.set_defaults(cls=BuildConfig, method='generate')

        build = parser.add_parser('buildbuild',
            help='Build using the specified backend.')
        build.add_argument('backend', default='legacy', choices=backends,
            nargs='?', help='Backend to use.')
        build.set_defaults(cls=BuildConfig, method='build')

