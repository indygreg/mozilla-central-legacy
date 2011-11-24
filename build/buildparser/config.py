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
import os.path
import platform
import sys

PROMPT_DEFAULT = """
The default build options have been selected automatically:

  Application:      Firefox
  Type:             debug
  Source Directory: %s
  Object Directory: %s
"""

PROMPT_LACK_OF_WIZARD = """
Eventually the wizard will be interactive. For now, it is static and you must
edit the produced config file manually to modify behavior. Stay tuned!
"""

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

class BuildConfig(object):
    """Represents a configuration for building."""

    __slots__ = (
        'config',
    )

    DEFAULTS = {
        'makefile': {'conversion': 'optimized'}
    }

    def __init__(self, filename=None):
        self.config = ConfigParser.ConfigParser()

        if filename:
            self.load_file(filename)
        else:
            self.config.add_section('paths')

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

        # TODO this should be configurable
        args.append('--enable-application=browser')

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

    def save(self, filename):
        """Saves the build configuration to a file."""
        with open(filename, 'wb') as f:
            self.config.write(f)

    def run_commandline_wizard(self, source_directory, fh=None):
        """Runs a command-line wizard to obtain config options."""
        assert(os.path.isabs(source_directory))
        assert(os.path.isdir(source_directory))

        self.config.set('paths', 'source_directory', source_directory)

        machine = platform.machine()
        object_directory = os.path.join(source_directory, 'obj-ff-debug')

        if fh is None:
            fh = sys.stdout

        print >>fh, PROMPT_DEFAULT % (
            source_directory,
            object_directory
        )

        print >>fh, PROMPT_LACK_OF_WIZARD

        self.config.set('paths', 'object_directory', object_directory)