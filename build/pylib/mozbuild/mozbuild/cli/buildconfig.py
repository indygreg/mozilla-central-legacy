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
        from mozbuild.buildconfig.extractor import BuildSystemExtractor

        bse = BuildSystemExtractor(self.config)
        bse.load_input_build_config_files()
        tree = bse.get_tree_info()

        print tree

    @staticmethod
    def populate_argparse(parser):
        bxr = parser.add_parser('bxr',
                                help='The Build Cross Reporter Tool.')

        bxr.set_defaults(cls=BuildConfig, method='bxr', filename='bxr.html')

        buildinfo = parser.add_parser('buildinfo',
            help='Generate a machine-readable document describing the build.')
        buildinfo.set_defaults(cls=BuildConfig, method='buildinfo')
