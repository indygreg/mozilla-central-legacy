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

# This file contains code for turning the Python build system data structures
# into Makefiles.

from . import data

import os.path

class MakefileGenerator(object):
    '''This class contains logic for taking a build representation and
    converting it into a giant Makefile.'''

    __slots__ = (
        'tree',
    )

    def __init__(self, tree):
        assert(isinstance(tree, data.TreeInfo))

        self.tree = tree

    def generate_makefile(self, fh):
        '''Convert the tree info into a Makefile'''

        print >>fh, '# THIS FILE WAS AUTOMATICALLY GENERATED. DO NOT MODIFY BY HAND'
        print >>fh, 'TOP_SOURCE_DIR := %s' % self.tree.top_source_directory
        print >>fh, 'OBJECT_DIR := %s' % self.tree.object_directory
        print >>fh, 'DIST_DIR := $(OBJECT_DIR)/dist'
        print >>fh, 'DIST_INCLUDE_DIR := $(DIST_DIR)/include'
        print >>fh, 'DIST_IDL_DIR := $(DIST_DIR)/idl'
        print >>fh, 'COPY := cp'
        print >>fh, 'MKDIR := mkdir'
        print >>fh, ''

        print >>fh, '# Our default rule. It is order dependent.'
        print >>fh, 'default: idls\n'

        print >>fh, '$(DIST_DIR) $(DIST_INCLUDE_DIR) $(DIST_IDL_DIR):'
        print >>fh, '\t$(MKDIR) -p "$@"\n'

        self._print_idl_rules(fh)

    def _print_idl_rules(self, fh):
        '''Prints all the IDL rules.'''

        base_command = ' '.join([
            'PYTHONPATH="$(TOP_SOURCE_DIR)/other-licenses/ply:$(TOP_SOURCE_DIR)/xpcom/idl-parser"',
            'python',
            '$(TOP_SOURCE_DIR)/xpcom/idl-parser/header.py',
            '-I $(DIST_IDL_DIR)'
        ])

        print >>fh, 'IDL_GENERATE_HEADER := %s' % base_command
        print >>fh, ''

        copy_targets = []
        convert_targets = []

        # Each IDL is first copied to the output directory before any
        # conversion takes place.

        # Each IDL file produces a .h file of the same name.
        # IDL files also have a complex list of dependencies. So, we create
        # each rule independently.
        output_directory = os.path.join(self.tree.object_directory, 'dist', 'include')
        source_filenames = self.tree.idl_sources.keys()
        source_filenames.sort()
        for filename in source_filenames:
            metadata = self.tree.idl_sources[filename]

            basename = os.path.basename(filename)
            header_basename = os.path.splitext(basename)[0] + '.h'

            dist_idl_filename = os.path.normpath(os.path.join('$(DIST_IDL_DIR)', basename))

            out_header_filename = os.path.normpath(os.path.join(
                '$(DIST_INCLUDE_DIR)', header_basename
            ))

            copy_targets.append(dist_idl_filename)
            convert_targets.append(out_header_filename)

            # The copy target and rule
            print >>fh, '%s: $(DIST_IDL_DIR) %s' % ( dist_idl_filename, filename )
            print >>fh, '\t$(COPY) "%s" "%s"' % ( filename, dist_idl_filename )
            print >>fh, ''

            # The conversion target and rule
            dependencies = metadata['dependencies']
            print >>fh, '%s: $(DIST_INCLUDE_DIR) \\\n  %s' % ( out_header_filename, ' \\\n  '.join(dependencies) )
            print >>fh, '\t$(IDL_GENERATE_HEADER) -o "$@" "%s"' % filename
            print >>fh, ''

        print >>fh, 'idl_copy_targets = %s\n' % ' \\\n  '.join(copy_targets)
        print >>fh, 'idl_convert_targets = %s\n' % ' \\\n  '.join(convert_targets)

        print >>fh, 'idls: $(idl_copy_targets) $(idl_convert_targets)\n'
