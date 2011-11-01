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

# This script parses a build tree and performs actions with the data.

import sys

sys.path.append('build/pymake')

import buildparser.extractor

from optparse import OptionParser
from sys import argv, exit

op = OptionParser(usage='usage: %prog [options] /path/to/objdir/')
op.add_option('--print-variable-counts', dest='print_variable_counts',
              action='store_true', help='Print counts of seen variable names')
op.add_option('--print-unhandled-variables', dest='print_unhandled_variables',
              action='store_true',
              help='Print information on unhandle variables')

(options, args) = op.parse_args()

if len(args) != 1:
    print 'Path not specified'
    exit(1)

path = args[0]

parser = buildparser.extractor.ObjectDirectoryParser(path)
parser.load_tree()

if options.print_unhandled_variables:
    l = sorted(parser.unhandled_variables.iteritems(), key=lambda(k, v):
            (len(v), k))
    for k, v in l:
        print '%s\t%s' % ( len(v), k)

if options.print_variable_counts:
    # TODO this should be an API elsewhere
    # TODO this does redundant work with parser.load_tree()
    variables = {}
    for p in parser.all_makefile_paths:
        try:
            m = buildparser.makefile.MozillaMakefile(p)

            for v in m.get_own_variable_names(include_conditionals=True):
                if v in variables:
                    variables[v] += 1
                else:
                    variables[v] = 1
        except:
            print 'Exception parsing path: %s' % p
            print sys.exc_info()

    for k, v in sorted(variables.iteritems(), key=lambda(k, v): (v, k)):
        print '%s\t%s' % ( v, k )
