# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

import ConfigParser
import logging
import os
import os.path
import multiprocessing
import shlex
import sys

APPLICATION_OPTIONS = {
    'browser':   'Desktop Browser (Firefox)',
    'mail':      'Thunderbird',
    'suite':     'Mozilal Suite (SeaMonkey)',
    'calendar':  'Standalone Calendar (Sunbird)',
    'xulrunner': 'XULRunner'
}

TYPE_POSITIVE_INTEGER = 1
TYPE_STRING = 2
TYPE_ABSOLUTE_PATH = 3
TYPE_BOOLEAN = 4

# Defines the set of recognized options in the config.
OPTIONS = {
    'paths': {
        'source_directory': {
            'short': 'Source Directory',
            'help': 'Path to top-level source code directory.',
            'type': TYPE_ABSOLUTE_PATH,
            'required': True,
        },
        'object_directory': {
            'short': 'Object Directory',
            'help': 'Path to directory where generated files will go.',
            'type': TYPE_ABSOLUTE_PATH,
            'required': True,
        },
    },
    'build': {
        'application': {
            'short':   'Application',
            'help':    'The application to build.',
            'options': APPLICATION_OPTIONS,
        },
        'threads': {
            'short':  'Threads',
            'help':   'How many parallel threads to launch when building.',
            'type':   TYPE_POSITIVE_INTEGER,
        },
        'configure_args': {
            'short': 'Configure Arguments',
            'help': 'Extra arguments to pass to configure. This is effectively '
                    'a back door. Ideally it should not exist.',
            'type': TYPE_STRING,
        },
        'debug': {
            'short': 'Debug Builds',
            'help': 'Include debug information in builds',
            'type': TYPE_BOOLEAN,
        },
        'optimize': {
            'short': 'Optimized Builds',
            'help': 'Whether to produce builds with optimized code',
            'type': TYPE_BOOLEAN,
        },
        'macos_sdk': {
            'short': 'OS X SDK',
            'help': 'Full path to Mac OS X SDK',
            'type': TYPE_ABSOLUTE_PATH,
        },
    },
    'compiler': {
        'cc': {
            'short': 'C Compiler',
            'help': 'Path to C compiler',
            'type': TYPE_ABSOLUTE_PATH,
        },
        'cxx': {
            'short': 'C++ Compiler',
            'help': 'Path to C++ compiler',
            'type': TYPE_ABSOLUTE_PATH,
        },
        'cflags': {
            'short': 'C Compiler Flags',
            'help': 'Extra flags to add to C compiler',
            'type': TYPE_STRING,
        },
        'cxxflags': {
            'short': 'C++ Compiler Flags',
            'help': 'Extra flags to add to C++ compiler',
            'type': TYPE_STRING,
        },
    },
}

class BuildConfig(object):
    """Represents a configuration for the build system."""

    __slots__ = (
        'config',
        'loaded_filename',
        'logger',
        'log_manager',
    )

    DEFAULTS = {
        'build': {
            'debug': True,
            'optimize': False,
            'threads': multiprocessing.cpu_count(),
            'macos_sdk': None,
        },
    }

    def __init__(self, filename=None, log_manager=None):
        self.loaded_filename = None
        self.log_manager = log_manager
        self.logger = logging.getLogger(__name__)

        self.config = ConfigParser.RawConfigParser()

        if filename:
            self.load_file(filename)
        else:
            for k in sorted(OPTIONS.keys()):
                self.config.add_section(k)

    @property
    def source_directory(self):
        return self.config.get('paths', 'source_directory')

    @property
    def object_directory(self):
        return self.config.get('paths', 'object_directory')

    @property
    def debug_build(self):
        return self.get_value('build', 'debug')

    @property
    def optimized_build(self):
        return self.get_value('build', 'optimize')

    @property
    def thread_count(self):
        return self.get_value('build', 'threads')

    @property
    def macos_sdk(self):
        return self.get_value('build', 'macos_sdk')

    @property
    def configure_args(self):
        """Returns list of configure arguments for this configuration."""
        args = []

        args.append('--enable-application=%s' % (
            self.config.get('build', 'application') ))

        # TODO should be conditional on DirectX SDK presence
        if os.name == 'nt':
            args.append('--disable-angle')

        if self.debug_build:
            args.append('--enable-debug')

        if self.optimized_build:
            args.append('--enable-optimize')

        if self.macos_sdk:
            args.append('--with-macos-sdk=%s' % self.macos_sdk)

        if self.config.has_option('build', 'configure_args'):
            args.extend(shlex.split(
                self.config.get('build', 'configure_args')))

        return args

    def get_value(self, section, option):
        if self.config.has_option(section, option):
            return self.config.get(section, option)

        default_section = self.DEFAULTS.get(section, {})

        return default_section[option]

    def has_value(self, section, option):
        return self.config.has_option(section, option)

    def load_file(self, filename):
        self.config.read(filename)

        for section in self.config.sections():
            if section not in OPTIONS:
                extra = {
                    'params': {'section': section},
                    'action': 'config_unknown_section',
                }
                self.logger.log(logging.WARN,
                    'Unknown section in config file: {section}',
                    extra=extra)
                continue

            for k, v in self.config.items(section):
                if k not in OPTIONS[section]:
                    extra = {
                        'params': {
                            'section': section,
                            'name': k,
                        },
                        'action': 'config_unknown_option',
                    }
                    self.logger.log(logging.WARN,
                            'Unknown option: {section}.{name}',
                            extra=extra)

        self.loaded_filename = filename

    def save(self, filename):
        """Saves the build configuration to a file."""
        with open(filename, 'wb') as f:
            self.config.write(f)

    def get_environment_variables(self):
        env = {}

        mapping = {
            ('compiler', 'cc'): 'CC',
            ('compiler', 'cxx'): 'CXX',
            ('compiler', 'cflags'): 'CFLAGS',
            ('compiler', 'cxxflags'): 'CXXFLAGS',
        }

        for (section, option), k in mapping.iteritems():
            if self.has_value(section, option):
                env[k] = self.get_value(section, option)

        return env

    def run_commandline_wizard(self, source_directory, fh=None):
        """Runs a command-line wizard to obtain config options."""
        assert(os.path.isabs(source_directory))
        assert(os.path.isdir(source_directory))

        if fh is None:
            fh = sys.stdout

        self.config.set('paths', 'source_directory', source_directory)

        object_directory = os.path.join(source_directory, 'objdir')
        if not self.config.has_option('paths', 'object_directory'):
            self.config.set('paths', 'object_directory', object_directory)

        if not self.config.has_option('build', 'application'):
            self.config.set('build', 'application', 'browser')

        print >>fh, 'Current Configuration\n'
        self.print_current_config(fh)
        print >>fh, ''

        print >>fh, 'Interactive settings wizard not yet implemented.'
        print >>fh, 'For now, edit the settings file manually.'

    def print_current_config(self, fh):
        """Prints an English summary of the current config to a file handle."""

        for section in OPTIONS.keys():
            for option, d in OPTIONS[section].iteritems():
                value = None
                if self.config.has_option(section, option):
                    value = self.config.get(section, option)
                else:
                    value = '(default)'

                print >>fh, '{0:30} = {1}'.format(d['short'], value)

