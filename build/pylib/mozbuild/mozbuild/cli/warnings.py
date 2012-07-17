# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

import logging
import operator

from mozbuild.cli.base import ArgumentProvider
from mozbuild.base import Base

class Warnings(Base, ArgumentProvider):
    def __init__(self, config):
        Base.__init__(self, config)

    def summary(self, report=None):
        from mozbuild.compilation.warnings import Warnings

        warnings = Warnings(self.config)

        type_counts = warnings.database.get_type_counts()
        sorted_counts = sorted(type_counts.iteritems(),
                key=operator.itemgetter(1))

        total = 0
        for k, v in sorted_counts:
            print '%d\t%s' % ( v, k )
            total += v

        print '%d\tTotal' % total

    def list(self, report=None):
        from mozbuild.compilation.warnings import Warnings

        warnings = Warnings(self.config)

        # TODO sort should also include line number.
        by_name = sorted(warnings.database.warnings(),
                key=operator.itemgetter('filename'))

        for warning in by_name:
            if warning['column'] is not None:
                print '%s:%d:%d [%s] %s' % (warning['filename'],
                    warning['line'], warning['column'], warning['flag'],
                    warning['message'])
            else:
                print '%s:%d [%s] %s' % (warning['filename'], warning['line'],
                    warning['flag'], warning['message'])

    @staticmethod
    def populate_argparse(parser):
        summary = parser.add_parser('warnings-summary',
                help='Show a summary of compiler warnings.')

        summary.add_argument('report', default=None, nargs='?',
                help='Warnings report to display. If not defined, show '
                     'the most recent report')

        summary.set_defaults(cls=Warnings, method='summary', report=None)

        lst = parser.add_parser('warnings-list',
                help='Show a list of compiler warnings')
        lst.add_argument('report', default=None, nargs='?',
                help='Warnings report to display. If not defined, show '
                     'the most recent report.')
        lst.set_defaults(cls=Warnings, method='list', report=None)
