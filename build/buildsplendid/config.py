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

# This file contains code for configuring a build environment.

import ConfigParser
import os
import os.path
import multiprocessing
import platform
import shlex
import sys

MAKEFILE_CONVERSION_OPTIONS = {
    'traditional': """Performs simple conversion from .in files by replacing
                      variable tokens (@var@). This is how Makefiles typically
                      operate. It is the safest option, but is the slowest.""",

    'rewrite': """Rewrite the Makefile using the PyMake API. This is mostly for
                  testing of the core conversion API. Unless you are a build
                  developer, you probably don't care about this.""",

    'prune': """This will analyze the Makefile and prune conditional blocks that
                aren't relevant for the current configuration. The reduction
                is conservative with what it eliminates, so the produced Makefile
                should be functionally equivalent to the original. This performs
                little optimization. It is useful if you are interested in more
                readable Makefiles with unused code eliminated.""",

    'optimized': """Produce a fully optimized Makefile build. This will perform deep
                    inspection of Makefiles and will move known constructs to a fully
                    derecursified Makefile. Unknown variables and rules will be
                    retained in the Makefile and will be called during building. This
                    produces the fastest builds and is the default choice.""",
}

APPLICATION_OPTIONS = {
    'browser':   'Desktop Browser (Firefox)',
    'mail':      'Thunderbird',
    'suite':     'Mozilal Suite (SeaMonkey)',
    'calendar':  'Standalone Calendar (Sunbird)',
    'xulrunner': 'XULRunner'
}

TYPE_POSITIVE_INTEGER = 1
TYPE_STRING = 2
TYPE_PATH = 3

# Defines the set of recognized options in the config.
OPTIONS = {
    'paths': {
        'source_directory': {
            'short': 'Source Directory',
            'help': 'Path to top-level source code directory.',
            'type': TYPE_PATH,
        },
        'object_directory': {
            'short': 'Object Directory',
            'help': 'Path to directory where generated files will go.',
            'type': TYPE_PATH,
        },
    },
    'makefile': {
        'conversion': {
            'short':   'Makefile Conversion',
            'help':    'How to generate Makefiles.',
            'options': MAKEFILE_CONVERSION_OPTIONS,
        }
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
    }
}

class BuildConfig(object):
    """Represents a configuration for building."""

    __slots__ = (
        'config',
    )

    DEFAULTS = {
        'makefile': {'conversion': 'optimized'}
    }

    def __init__(self, filename=None):
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
    def configure_args(self):
        """Returns list of configure arguments for this configuration."""
        args = []

        args.append('--enable-application=%s' % (
            self.config.get('build', 'application') ))

        # TODO should be conditional on DirectX SDK presence
        if os.name == 'nt':
            args.append('--disable-angle')

        if self.config.has_option('build', 'configure_args'):
            args.extend(shlex.split(
                self.config.get('build', 'configure_args')))

        return args

    @property
    def makefile_conversion(self):
        """Returns the type of Makefile generation to perform."""
        return self.get_value('makefile', 'conversion')

    @makefile_conversion.setter
    def makefile_conversion(self, value):
        """Set the type of makefile conversion that will be performed."""
        assert(value in MAKEFILE_CONVERSION_OPTIONS.keys())
        self.config.set('makefile', 'conversion', value)

    def get_value(self, section, option):
        if self.config.has_option(section, option):
            return self.config.get(section, option)

        return self.DEFAULTS[section][option]

    def load_file(self, filename):
        self.config.read(filename)

        for section in self.config.sections():
            if section not in OPTIONS:
                raise Exception('Unknown section in config file: %s' % section)

            for k, v in self.config.items(section):
                if k not in OPTIONS[section]:
                    raise Exception('Unknown option: %s.%s' % ( section, k ))

    def save(self, filename):
        """Saves the build configuration to a file."""
        with open(filename, 'wb') as f:
            self.config.write(f)

    def run_commandline_wizard(self, source_directory, fh=None):
        """Runs a command-line wizard to obtain config options."""
        assert(os.path.isabs(source_directory))
        assert(os.path.isdir(source_directory))

        if fh is None:
            fh = sys.stdout

        self.config.set('paths', 'source_directory', source_directory)

        object_directory = os.path.join(source_directory, 'obj-ff-debug')
        if not self.config.has_option('paths', 'object_directory'):
            self.config.set('paths', 'object_directory', object_directory)

        if not self.config.has_option('build', 'threads'):
            self.config.set('build', 'threads', multiprocessing.cpu_count())

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