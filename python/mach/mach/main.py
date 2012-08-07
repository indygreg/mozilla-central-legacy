# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

# This module provides functionality for the command-line build tool
# (mach). It is packaged as a module because everything is a library.

import argparse
import logging
import os.path
import sys

from mozbuild import config
from mozbuild.logger import LoggingManager

# Import sub-command modules
# TODO do this via auto-discovery. Update README once this is done.
from mach.build import Build
from mach.buildconfig import BuildConfig
from mach.configure import Configure
from mach.testing import Testing
from mach.warnings import Warnings


class Mach(object):
    """Contains code for the command-line `mach` interface."""

    USAGE = """%(prog)s command [command arguments]

WARNING: This interface is under heavy development. Behavior can and will
change.

This program is your main control point for the Mozilla source tree.

To perform an action, specify it as the first argument. Here are some common
actions:

  %(prog)s help          Show full help.
  %(prog)s build         Build the source tree.
  %(prog)s test          Run a test suite.
  %(prog)s xpcshell-test Run xpcshell test(s).

To see more help for a specific action, run:

  %(prog)s <command> --help

e.g. %(prog)s build --help
"""

    def __init__(self, cwd):
        assert(os.path.isdir(cwd))

        self.cwd = cwd
        self.log_manager = LoggingManager()
        self.logger = logging.getLogger(__name__)

        self.log_manager.register_structured_logger(self.logger)

    def run(self, argv):
        """Runs the build tool with arguments specified."""
        parser = self.get_argument_parser()

        if len(argv) == 0:
            parser.usage = Mach.USAGE
            parser.print_usage()
            return 0
        elif argv[0] == 'help':
            parser.print_help()
            return 0

        args = parser.parse_args(argv)

        settings_file = self.get_settings_file(args)

        # Enable JSON logging to a file if configured.
        if args.logfile:
            self.log_manager.add_json_handler(args.logfile)

        log_level = logging.INFO
        if args.verbose:
            log_level = logging.DEBUG

        self.log_manager.add_terminal_logging(level=log_level,
                write_interval=args.log_interval)

        conf = config.BuildConfig(log_manager=self.log_manager)

        if os.path.exists(settings_file):
            if not os.path.isfile(settings_file):
                print 'Settings path exists but is not a file: %s' % \
                    settings_file
                print 'Please delete the specified path or try again with ' \
                    'a new path'
                sys.exit(1)

            conf.load_file(settings_file)
            self.log(logging.WARNING, 'config_load', {'file': settings_file},
                 'Loaded existing config file: {file}')
        else:
            conf.populate_default_paths(self.cwd)

            if not args.no_save_settings:
                conf.save(settings_file)
                self.log(logging.WARNING, 'config_save',
                    {'file': settings_file}, 'Saved config file to {file}')

        if args.objdir:
            raise Exception('TODO implement custom object directories.')

        # Now that we have the config squared away, we process the specified
        # sub-command/action. We start by filtering out all arguments handled
        # by us.
        exclude = [
            'settings_file',
            'no_save_settings',
            'objdir',
            'verbose',
            'logfile',
            'log_interval',
            'action',
            'cls',
            'method',
            'func',
        ]

        stripped = {}
        for k in vars(args):
            if k not in exclude:
                stripped[k] = getattr(args, k)

        # If the action is associated with a class, instantiate and run it.
        # All classes must be Base-derived and take a BuildConfig instance.
        if hasattr(args, "cls"):
            cls = getattr(args, "cls")(conf)
            method = getattr(cls, getattr(args, "method"))

            method(**stripped)

        # If the action is associated with a function, call it.
        elif hasattr(args, "func"):
            func = getattr(args, "func")
            func(**stripped)
        else:
            raise Exception("argparse parser not properly configured.")

        self.log(logging.WARNING, 'finished', {}, 'Build action finished')

    def log(self, level, action, params, format_str):
        self.logger.log(level, format_str,
            extra={'action': action, 'params': params})

    def get_settings_file(self, args):
        """Get the settings file for the current environment.

        We determine the settings file in order of:
          1) Command line argument
          2) Environment variable MOZ_BUILD_CONFIG
          3) Default path
        """

        p = os.path.join(self.cwd, 'mach.ini')

        if args.settings_file:
            p = args.settings_file
        elif 'MACH_SETTINGS_FILE' in os.environ:
            p = os.environ['MACH_SETTINGS_FILE']

        return p

    def get_argument_parser(self):
        """Returns an argument parser for the command-line interface."""

        parser = argparse.ArgumentParser()

        settings_group = parser.add_argument_group('Settings')
        settings_group.add_argument('--settings', dest='settings_file',
            metavar='FILENAME', help='Path to settings file.')
        settings_group.add_argument('--no-save-settings',
            dest='no_save_settings', action='store_true', default=False,
            help='When automatically generating settings, do not save the '
                'file.')
        settings_group.add_argument('--objdir', dest='objdir',
            metavar='FILENAME', help='Object directory to use. (ADVANCED).')

        logging_group = parser.add_argument_group('Logging')
        logging_group.add_argument('-v', '--verbose', dest='verbose',
            action='store_true', default=False,
            help='Print verbose output.')
        logging_group.add_argument('-l', '--log-file', dest='logfile',
            metavar='FILENAME', type=argparse.FileType('ab'),
            help='Filename to write log data to.')
        logging_group.add_argument('--log-interval', dest='log_interval',
            action='store_true', default=False,
            help='Prefix log line with interval from last message rather '
                'than relative time. Note that this is NOT execution time '
                'if there are parallel operations.')

        subparser = parser.add_subparsers(dest='action')

        # Register argument action providers with us.
        handlers = [
            Build,
            BuildConfig,
            Configure,
            Testing,
            Warnings,
        ]
        for cls in handlers:
            cls.populate_argparse(subparser)

        return parser
