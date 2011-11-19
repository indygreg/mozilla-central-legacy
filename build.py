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

# This script is used to configure and build the Mozilla source tree.

import sys

# TODO these should magically come from the environment.
sys.path.append('build')
sys.path.append('build/pymake')
sys.path.append('other-licenses/ply')
sys.path.append('xpcom/idl-parser')

import buildparser.config
import buildparser.extractor
import optparse
import os.path

op = optparse.OptionParser(usage='Usage: %prog [options]')
op.add_option('--config', dest='config_file', metavar='FILE',
              help='Path to config file to load and/or save.')
op.add_option('--generate-makefiles',
              dest='generate_makefiles',
              default=False,
              action='store_true',
              help='Force (re)generation of Makefiles')

(options, args) = op.parse_args()

config_file = os.path.join(os.path.dirname(__file__), 'build_config.ini')

if options.config_file:
    config_file = options.config_file
elif 'MOZ_BUILD_CONFIG' in os.environ:
    config_file = os.environ['MOZ_BUILD_CONFIG']

config = buildparser.config.BuildConfig()

if os.path.exists(config_file):
    print 'Loading existing config file %s' % config_file
    config.load_file(config_file)
else:
    print 'Config file does not exist at %s\n. I will help you generate one!' % config_file
    config.run_commandline_wizard(os.path.abspath(os.path.dirname(__file__)),
                                  sys.stdout)
    config.save(config_file)
    print 'Saved config file to %s' % config_file

bs = buildparser.extractor.BuildSystem(config)

if options.generate_makefiles:
    def makefile_callback(action, args):
        print '%s: %s' % ( action, args )

    print 'Generating Makefiles...'
    bs.generate_makefiles(callback=makefile_callback)