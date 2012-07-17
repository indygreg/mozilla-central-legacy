#!/usr/bin/python
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

# This module provides functionality for the command-line build tool
# (build.py). It is packaged as a module just because.

from . import buildsystem
from . import config
from . import extractor
from . import makefile

import argparse
import json
import logging
import os.path
import pymake.parser
import sys
import time

class BuildTool(object):
    """Contains code for the command-line build.py interface."""

    ACTIONS = {
        'actions': 'Show all actions that can be performed.',
        'build': 'Performs all steps necessary to perform a build.',
        'bxr': 'Generate Build Cross Reference HTML file describing the build system.',
        'configure': 'Run autoconf and ensure your build environment is proper.',
        'format-makefile': 'Print a makefile (re)formatted.',
        'help': 'Show full help documentation.',
        'makefiles': 'Generate Makefiles to build the project.',
        'settings': 'Sets up your build settings.',
        'unittest': 'Run the unit tests for the build system code',
        'wipe': 'Wipe your output directory and force a full rebuild.',
    }

    def bxr(self, bs, output):
        """Generate BXR.

        Arguments:

          output -- File object to write output to.
        """
        # We lazy import because we don't want a dependency on Mako. If that
        # package is every included with the source tree.
        from . import bxr
        bxr.generate_bxr(bs.config, output)

    def format_makefile(self, bs, format, filename=None, input=None,
                        output=None, strip_ifeq=False):
        """Format Makefiles different ways.

        Arguments:

        format -- How to format the Makefile. Can be one of (raw, pymake,
                  substitute, reformat, stripped)
        filename -- Name of file being read from.
        input -- File handle to read Makefile content from.
        output -- File handle to write output to. Defaults to stdout.
        strip_ifeq -- If True and format is stripped, try to evaluate ifeq
                      conditions in addition to ifdef.
        """
        if output is None:
            output = sys.stdout

        if filename is None and not input:
            raise Exception('No input file handle given.')

        if filename is not None and input is None:
            input = open(filename, 'rb')
        elif filename is None:
            filename = 'FILE_HANDLE'

        if format == 'raw':
            print >>output, input.read()

        elif format == 'pymake':
            statements = pymake.parser.parsestring(input.read(), filename)
            statements.dump(output, '')

        elif format == 'reformat':
            statements = makefile.StatementCollection(buf=input.read(),
                                                      filename=filename)
            for line in statements.lines():
                print >>output, line

        elif format == 'stripped':
            statements = makefile.StatementCollection(buf=input.read(),
                                                      filename=filename)
            statements.strip_false_conditionals(evaluate_ifeq=strip_ifeq)

            for line in statements.lines():
                print >>output, line

        else:
            raise Exception('Unsupported format type: %' % format)

