# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

# This module provides functionality for the command-line build tool
# (mach). It is packaged as a module because everything is a library.

import argparse
import logging
import os.path
import sys

from mozbuild.base import BuildConfig
from mozbuild.config import ConfigSettings
from mozbuild.logger import LoggingManager

# Import sub-command modules
# TODO do this via auto-discovery. Update README once this is done.
from mach.build import Build
from mach.configure import Configure
from mach.settings import Settings
from mach.testing import Testing
from mach.warnings import Warnings

# Classes inheriting from ArgumentProvider that provide commands.
HANDLERS = [
    Build,
    Configure,
    Settings,
    Testing,
    Warnings,
]

# Classes inheriting from ConfigProvider that provide settings.
# TODO this should come from auto-discovery somehow.
SETTINGS_PROVIDERS = [
    BuildConfig
]


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
        self.settings = ConfigSettings()

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

        # Enable JSON logging to a file if configured.
        if args.logfile:
            self.log_manager.add_json_handler(args.logfile)

        log_level = logging.INFO
        if args.verbose:
            log_level = logging.DEBUG

        self.log_manager.add_terminal_logging(level=log_level,
                write_interval=args.log_interval)

        settings_loaded = self.load_settings(args)
        conf = BuildConfig(self.settings)

        if not settings_loaded:
            conf.populate_default_paths(self.cwd)

            if not args.no_save_settings:
                path = os.path.join(self.cwd, 'mach.ini')

                with open(path, 'wb') as fh:
                    self.settings.write(fh)

                self.log(logging.WARNING, 'config_save',
                    {'file': path}, 'Saved config file to {file}')

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
        if hasattr(args, 'cls'):
            cls = getattr(args, 'cls')

            instance = cls(self.settings, self.log_manager)
            method = getattr(instance, getattr(args, 'method'))

            method(**stripped)

        # If the action is associated with a function, call it.
        elif hasattr(args, 'func'):
            func = getattr(args, 'func')
            func(**stripped)
        else:
            raise Exception("argparse parser not properly configured.")

    def log(self, level, action, params, format_str):
        self.logger.log(level, format_str,
            extra={'action': action, 'params': params})

    def load_settings(self, args):
        """Determine what settings files apply and load them.

        Currently, we only support loading settings from a single file.
        Ideally, we support loading from multiple files. This is supported by
        the ConfigSettings API. However, that API currently doesn't track where
        individual values come from, so if we load from multiple sources then
        save, we effectively do a full copy. We don't want this. Until
        ConfigSettings does the right thing, we shouldn't expose multi-file
        loading.

        We look for a settings file in the following locations. The first one
        found wins:

          1) Command line argument
          2) Environment variable
          3) Default path
        """
        for provider in SETTINGS_PROVIDERS:
            provider.register_settings()
            self.settings.register_provider(provider)

        p = os.path.join(self.cwd, 'mach.ini')

        if args.settings_file:
            p = args.settings_file
        elif 'MACH_SETTINGS_FILE' in os.environ:
            p = os.environ['MACH_SETTINGS_FILE']

        self.settings.load_file(p)

        return os.path.exists(p)

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
        for cls in HANDLERS:
            cls.populate_argparse(subparser)

        return parser
