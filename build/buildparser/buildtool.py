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

from . import config
from . import extractor
from . import makefile

import argparse
import json
import os.path
import pymake.parser
import sys
import time

class BuildTool(object):
    '''This class contains code for the command-line build.py interface.'''

    ACTIONS = {
        'actions': 'Show all actions that can be performed.',
        'build': 'Performs all steps necessary to perform a build.',
        'bxr': 'Generate Build Cross Reference HTML file describing the build system.',
        'configure': 'Run autoconf and ensure your build environment is proper.',
        'help': 'Show full help documentation.',
        'makefile-pymake': 'Print PyMake-parsed Makefile statement list.',
        'makefile-reformat': 'Print a Makefile reformatted from the parsed statement list.',
        'makefiles': 'Perform generation of Makefiles used to build.',
        'settings': 'Sets up your build settings.',
        'wipe': 'Wipe your output directory and force a full rebuild.',
    }

    USAGE = '''%(prog)s action [arguments]

    This program is your main control point for interfacing with the Mozilla build
    system.

    To perform an action, specify it as the first argument to the command. Some
    common actions are:

      %(prog)s build       Build the source tree.
      %(prog)s settings    Launch a wizard to guide you through build setup.
      %(prog)s help        Show additional command information.
    '''

    __slots__ = (
        'cwd',
        'log_handler',
        'bs',
    )

    def __init__(self, cwd):
        assert(os.path.isdir(cwd))

        self.cwd = cwd
        self.log_handler = None
        self.bs = None

    def run(self, argv):
        parser = self.get_argument_parser()
        args = parser.parse_args(argv)

        start_time = time.time()

        settings_file = self.get_settings_file(args)

        forensic_handle = None
        if args.logfile:
            forensic_handle = args.logfile

        def action_callback(action, params, formatter,
                                               important=False, error=False):
            '''Our logging/reporting callback. It takes an enumerated string
            action, a dictionary of parameters describing that action, a
            formatting string for producing human readable text of that event,
            and some flags indicating if the message is important or represents
            an error.'''
            now = time.time()

            elapsed = now - start_time

            json_obj = [now, action, params]

            if forensic_handle is not None:
                json.dump(json_obj, forensic_handle)
                print >>forensic_handle, ''

            if args.verbose or important or error:
                if args.print_json:
                    json.dump(json_obj, sys.stderr)
                else:
                    print >>sys.stderr, '%4.2f %s' % ( elapsed, formatter.format(**params) )

        self.log_handler = action_callback

        conf = config.BuildConfig()

        if os.path.exists(settings_file):
            if not os.path.isfile(settings_file):
                print 'Specified settings file exists but is not a file: %s' % settings_file
                sys.exit(1)

            conf.load_file(settings_file)
            action_callback('config_load', {'file': settings_file},
                            'Loaded existing config file: {file}',
                            important=True)
        else:
            print 'Settings file does not exist at %s\n. I will help you generate one!' % settings_file
            conf.run_commandline_wizard(source_directory, sys.stdout)

            if not args.no_save_settings:
                conf.save(settings_file)
                action_callback('config_save', {'file': settings_file},
                                'Saved config file to {file}', important=True)

        # Now that we have the config squared away, we start doing stuff.
        self.bs = extractor.BuildSystem(conf, callback=self.log_handler)

        method = getattr(self, args.method)
        method(args)

        action_callback('finished', {}, 'Build action finished', important=True)

    def build(self, args):
        self.bs.build()

    def bxr(self, args):
        # We lazy import because we don't want a dependency on Mako. If that
        # package is every included with the source tree, we can change this.
        from . import bxr
        with open(args.output, 'wb') as fh:
            buildparser.bxr.generate_bxr(config, fh)

    def configure(self, args):
        self.bs.configure()

    def makefiles(self, args):
        self.bs.generate_makefiles()

    def wipe(self, args):
        self.bs.wipe()

    # TODO convert makefile actions to methods
    ## The debug and power user options take precedence over explicit actions.
    #if options.print_makefile_statements is not None:
    #    statements = pymake.parser.parsefile(options.print_makefile_statements)
    #    statements.dump(sys.stdout, '')
    #    other_action_taken = True
    #
    #if options.print_statement_collection is not None:
    #    statements = buildparser.makefile.StatementCollection(
    #        filename=options.print_statement_collection)
    #
    #    for statement in statements.statements:
    #        print statement.debug_str
    #
    #    other_action_taken = True
    #
    #if options.print_reformatted_statements is not None:
    #    statements = buildparser.makefile.StatementCollection(
    #        filename=options.print_reformatted_statements)
    #
    #    for line in statements.lines:
    #        print line
    #
    #    other_action_taken = True
    #
    #if options.print_pruned_makefile is not None:
    #    statements = buildparser.makefile.StatementCollection(
    #        filename=options.print_pruned_makefile
    #    )
    #
    #    statements.strip_false_conditionals()
    #
    #    for line in statements.lines:
    #        print line
    #
    #    other_action_taken = True

    def get_settings_file(self, args):
        '''Get the settings file for the current environment.

        We determine the settings file in order of:
          1) Command line argument
          2) Environment variable MOZ_BUILD_CONFIG
          3) Default path
        '''

        p = os.path.join(self.cwd, 'build.ini')

        if args.settings_file:
            p = args.settings_file
        elif 'MOZ_BUILD_CONFIG' in os.environ:
            p = os.environ['MOZ_BUILD_CONFIG']

        return p

    def get_argument_parser(self):
        '''Returns an argument parser for the command-line interface.'''

        parser = argparse.ArgumentParser(usage=BuildTool.USAGE)

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

        action_makefile_pymake = subparser.add_parser('makefile-pymake',
                                                      help=BuildTool.ACTIONS['makefile-pymake'])
        action_makefile_pymake.set_defaults(method='makefile_pymake')
        action_makefile_pymake.add_argument('filename',
                                            metavar='FILENAME',
                                            type=argparse.FileType('r'),
                                            help='Makefile to parse.')

        action_makefile_reformat = subparser.add_parser('makefile-reformat',
                                                        help=BuildTool.ACTIONS['makefile-reformat'])
        action_makefile_reformat.set_defaults(method='makefile_reformat')
        action_makefile_reformat.add_argument('filename',
                                              metavar='FILENAME',
                                              type=argparse.FileType('r'),
                                              help='Makefile to reformat.')

        action_makefiles = subparser.add_parser('makefiles',
                                                help=BuildTool.ACTIONS['makefiles'])
        action_makefiles.set_defaults(method='makefiles')

        action_settings = subparser.add_parser('settings',
                                               help=BuildTool.ACTIONS['settings'])
        action_settings.set_defaults(method='settings')

        action_wipe = subparser.add_parser('wipe', help=BuildTool.ACTIONS['wipe'])
        action_wipe.set_defaults(method='wipe')

        return parser

