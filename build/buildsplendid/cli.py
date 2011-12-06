#!/usr/bin/python
# ***** BEGIN LICENSE BLOCK *****
# Version: MPL 1.1/GPL 2.0/LGPL 2.1
#
# The contents of this file are subject to the Mozilla Public License Version
# 1.1 (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
# http://www.mozilla.org/MPL/
#
# Software distributed under the License is distributed on an "AS IS" basis,
# WITHOUT WARRANTY OF ANY KIND, either express or implied. See the License
# for the specific language governing rights and limitations under the
# License.
#
# The Original Code is Mozilla build system.
#
# The Initial Developer of the Original Code is Mozilla Foundation.
# Portions created by the Initial Developer are Copyright (C) 2011
# the Initial Developer. All Rights Reserved.
#
# Contributor(s):
#  Gregory Szorc <gps@mozilla.com>
#
# Alternatively, the contents of this file may be used under the terms of
# either the GNU General Public License Version 2 or later (the "GPL"), or
# the GNU Lesser General Public License Version 2.1 or later (the "LGPL"),
# in which case the provisions of the GPL or the LGPL are applicable instead
# of those above. If you wish to allow use of your version of this file only
# under the terms of either the GPL or the LGPL, and not to allow others to
# use your version of this file under the terms of the MPL, indicate your
# decision by deleting the provisiwons above and replace them with the notice
# and other provisions required by the GPL or the LGPL. If you do not delete
# the provisions above, a recipient may use your version of this file under
# the terms of any one of the MPL, the GPL or the LGPL.
#
# ***** END LICENSE BLOCK *****

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

class LogFormatter(logging.Formatter):
    """Custom log formatting class that writes JSON or our special format."""

    __slots__ = ( 'start_time', 'write_json' )

    def __init__(self, start_time, write_json=False):
        self.start_time = start_time
        self.write_json = write_json

    def format(self, record):
        action = record.action
        params = record.params

        if self.write_json:
            json_obj = [record.created, action, params]
            return json.dumps(json_obj)
        else:
            elapsed = record.created - self.start_time
            return '%4.2f %s' % ( elapsed, record.msg.format(**params) )

# TODO use decorators to make dispatching and documentation live closer to
# methods.
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

    USAGE = """%(prog)s action [arguments]

This program is your main control point for the Mozilla build
system.

To perform an action, specify it as the first argument. Here are some common
actions:

  %(prog)s build         Build the source tree.
  %(prog)s settings      Launch a wizard to guide you through build setup.
  %(prog)s help          Show full help.
"""

    __slots__ = (
        'cwd',
        'bs_logger',
        'logger',
    )

    def __init__(self, cwd):
        assert(os.path.isdir(cwd))

        self.cwd = cwd

        # We instantiate the buildsplendid logger as early as possible and
        # set the level to debug so everything flows to it.
        self.bs_logger = logging.getLogger('buildsplendid')
        self.bs_logger.setLevel(logging.DEBUG)

        self.logger = logging.getLogger(__name__)

    def run(self, argv):
        """Runs the build tool with arguments specified."""
        parser = self.get_argument_parser()

        if len(argv) == 0:
            parser.usage = BuildTool.USAGE
            parser.print_usage()
            return 0
        elif argv[0] == 'help':
            parser.print_help()
            return 0

        args = parser.parse_args(argv)
        start_time = time.time()

        settings_file = self.get_settings_file(args)

        forensic_handle = None
        if args.logfile:
            forensic_handle = args.logfile

        verbose = args.verbose
        print_json = args.print_json

        # The forensic logger logs everything to JSON
        if forensic_handle is not None:
            forensic_formatter = LogFormatter(start_time, write_json=True)
            forensic_handler = logging.StreamHandler(stream=forensic_handle)
            forensic_handler.setFormatter(forensic_formatter)
            forensic_handler.setLevel(logging.DEBUG)
            self.bs_logger.addHandler(forensic_handler)

        # The stderr logger is always enabled. Although, it is configurable
        # from arguments.
        stderr_formatter = LogFormatter(start_time, write_json=print_json)
        stderr_handler = logging.StreamHandler(stream=sys.stderr)
        stderr_handler.setFormatter(stderr_formatter)
        if not verbose:
            stderr_handler.setLevel(logging.WARNING)

        self.bs_logger.addHandler(stderr_handler)

        self.log(logging.INFO, 'build_tool_start', {'action': args.action},
                 'Build tool started')

        conf = config.BuildConfig()

        if os.path.exists(settings_file):
            if not os.path.isfile(settings_file):
                print 'Specified settings file exists but is not a file: %s' % settings_file
                sys.exit(1)

            conf.load_file(settings_file)
            self.log(logging.WARNING, 'config_load', {'file': settings_file},
                     'Loaded existing config file: {file}')
        else:
            print 'Settings file does not exist at %s\n. I will help you generate one!' % settings_file
            conf.run_commandline_wizard(self.cwd, sys.stdout)

            if not args.no_save_settings:
                conf.save(settings_file)
                self.log(logging.WARNING, 'config_save', {'file': settings_file},
                         'Saved config file to {file}')

        # Now that we have the config squared away, we start doing stuff.
        bs = buildsystem.BuildSystem(conf)

        method_name = args.method
        stripped = vars(args)
        # TODO these should come automatically from the parser object
        for strip in ['settings_file', 'no_save_settings', 'verbose', 'print_json', 'logfile', 'method', 'action']:
            del stripped[strip]

        method = getattr(self, method_name)
        method(bs, **stripped)

        self.log(logging.WARNING, 'finished', {}, 'Build action finished')

    def build(self, bs):
        bs.build()

    def bxr(self, bs, output):
        """Generate BXR.

        Arguments:

          output -- File object to write output to.
        """
        # We lazy import because we don't want a dependency on Mako. If that
        # package is every included with the source tree.
        from . import bxr
        bxr.generate_bxr(bs.config, output)

    def configure(self, bs):
        bs.configure()

    def makefiles(self, bs):
        bs.generate_makefiles()

    def wipe(self, bs):
        bs.wipe()

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

    def unittest(self, bs):
        import unittest

        top_dir = os.path.join(self.cwd, 'build')
        start_dir = os.path.join(top_dir, 'buildsplendid', 'test')

        loader = unittest.TestLoader()
        suite = loader.discover(start_dir, pattern='*_test.py', top_level_dir=top_dir)
        unittest.TextTestRunner().run(suite)

    def log(self, level, action, params, format_str):
        self.logger.log(level, format_str, extra={'action': action, 'params': params})

    def get_settings_file(self, args):
        """Get the settings file for the current environment.

        We determine the settings file in order of:
          1) Command line argument
          2) Environment variable MOZ_BUILD_CONFIG
          3) Default path
        """

        p = os.path.join(self.cwd, 'build.ini')

        if args.settings_file:
            p = args.settings_file
        elif 'MOZ_BUILD_CONFIG' in os.environ:
            p = os.environ['MOZ_BUILD_CONFIG']

        return p

    def get_argument_parser(self):
        """Returns an argument parser for the command-line interface."""

        parser = argparse.ArgumentParser()

        # Add global arguments
        global_parser = argparse.ArgumentParser(add_help=False)

        settings_group = parser.add_argument_group('Settings')
        settings_group.add_argument('--settings',
                                    dest='settings_file',
                                    metavar='FILENAME',
                                    help='Path to settings file.')
        settings_group.add_argument('--no-save-settings',
                                    dest='no_save_settings',
                                    action='store_true',
                                    default=False,
                                    help='When automatically generating settings, do not save the file.')

        logging_group = parser.add_argument_group('Logging')
        logging_group.add_argument('-v', '--verbose',
                                   dest='verbose',
                                   action='store_true',
                                   default=False,
                                   help='Print verbose output.')
        logging_group.add_argument('--print-json',
                                   dest='print_json',
                                   action='store_true',
                                   default=False,
                                   help='Log machine-friendly JSON to STDERR instead of regular text.')
        logging_group.add_argument('-l', '--log-file',
                                   dest='logfile',
                                   metavar='FILENAME',
                                   type=argparse.FileType('ab'),
                                   help='Filename to write log data to.')

        subparser = parser.add_subparsers(dest='action')

        action_build = subparser.add_parser('build',
                                            help=BuildTool.ACTIONS['build'])
        action_build.set_defaults(method='build')

        action_bxr = subparser.add_parser('bxr',
                                          help=BuildTool.ACTIONS['bxr'])
        action_bxr.set_defaults(method='bxr')

        action_bxr.add_argument('--output',
                                default='./bxr.html',
                                metavar='FILENAME',
                                type=argparse.FileType('w'),
                                help='Filename to write BXR HTML file to.')

        action_configure = subparser.add_parser('configure',
                                                help=BuildTool.ACTIONS['configure'])
        action_configure.set_defaults(method='configure')

        #action_help = subparser.add_parser('help', help=BuildTool.ACTIONS['help'])

        action_format_makefile = subparser.add_parser('format-makefile',
                                                      help=BuildTool.ACTIONS['format-makefile'])

        action_format_makefile.set_defaults(method='format_makefile')
        format_choices = set(['raw', 'pymake', 'substitute', 'reformat', 'stripped'])
        action_format_makefile.add_argument('format', default='raw',
                                            choices=format_choices,
                                            help='How to format the Makefile')
        action_format_makefile.add_argument('filename',
                                            metavar='FILENAME',
                                            help='Makefile to parse.')
        action_format_makefile.add_argument('--evaluate-ifeq',
                                            default=False,
                                            dest='strip_ifeq',
                                            action='store_true',
                                            help='Evaluate ifeq conditions.')

        action_makefiles = subparser.add_parser('makefiles',
                                                help=BuildTool.ACTIONS['makefiles'])
        action_makefiles.set_defaults(method='makefiles')

        action_settings = subparser.add_parser('settings',
                                               help=BuildTool.ACTIONS['settings'])
        action_settings.set_defaults(method='settings')

        action_unittest = subparser.add_parser('unittest',
                                               help=BuildTool.ACTIONS['unittest'])
        action_unittest.set_defaults(method='unittest')

        action_wipe = subparser.add_parser('wipe', help=BuildTool.ACTIONS['wipe'])
        action_wipe.set_defaults(method='wipe')

        return parser

