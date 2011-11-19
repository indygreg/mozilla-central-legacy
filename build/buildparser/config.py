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

PROMPT_DEFAULT = '''
The default build options have been selected automatically:

  Application:      Firefox
  Type:             debug
  Source Directory: %s
  Object Directory: %s
'''

PROMPT_LACK_OF_WIZARD = '''
Eventually the wizard will be interactive. For now, it is static and you must
edit the produced config file manually to modify behavior. Stay tuned!
'''

class BuildConfig(object):
    '''Represents a configuration for building.'''

    __slots__ = (
        'config',
    )

    def __init__(self, filename=None):
        self.config = ConfigParser.RawConfigParser()

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

    def load_file(self, filename):
        self.config.read(filename)

    def save(self, filename):
        '''Saves the build configuration to a file.'''
        with open(filename, 'wb') as f:
            self.config.write(f)

    def run_commandline_wizard(self, source_directory, fh=None):
        '''Runs a command-line wizard to obtain config options.'''
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