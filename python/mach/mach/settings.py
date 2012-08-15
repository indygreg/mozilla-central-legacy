# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

from textwrap import TextWrapper

from mozbuild.base import Base
from mach.base import ArgumentProvider

class Settings(Base, ArgumentProvider):
    def list(self):
        for section in sorted(self.settings):
            for option in sorted(self.settings[section]):
                short, full = self.settings.option_help(section, option)
                print '%s.%s -- %s' % (section, option, short)

    def create(self):
        wrapper = TextWrapper(initial_indent='# ', subsequent_indent='# ')

        for section in sorted(self.settings):
            print '[%s]' % section
            print ''

            for option in sorted(self.settings[section]):
                short, full = self.settings.option_help(section, option)

                print wrapper.fill(full)
                print ';%s =' % option
                print ''

    @staticmethod
    def populate_argparse(parser):
        lst = parser.add_parser('settings-list',
            help='Show available config settings.')

        lst.set_defaults(cls=Settings, method='list')

        create = parser.add_parser('settings-create',
            help='Print a new settings file with usage info.')

        create.set_defaults(cls=Settings, method='create')
