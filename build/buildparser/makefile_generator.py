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

    def get_converted_path(self, path):
        '''Convert a string filesystem path into its Makefile equivalent, with
        appropriate variable substitution.'''
        if path[0:len(self.tree.object_directory)] == self.tree.object_directory:
            return '$(OBJECT_DIR)%s' % path[len(self.tree.object_directory):]
        elif path[0:len(self.tree.top_source_directory)] == self.tree.top_source_directory:
            return '$(TOP_SOURCE_DIR)%s' % path[len(self.tree.top_source_directory):]
        else:
            return path

    def generate_makefile(self, fh):
        '''Convert the tree info into a Makefile'''

        state = {
            'fh':      fh,
            'phonies': set()
        }

        self._print_header(state)
        self._print_idl_rules(state)
        self._print_file_exports(state)
        self._print_footer(state)

    def _print_header(self, state):
        fh = state['fh']

        print >>fh, '# THIS FILE WAS AUTOMATICALLY GENERATED. DO NOT MODIFY BY HAND'
        print >>fh, 'TOP_SOURCE_DIR := %s' % self.tree.top_source_directory
        print >>fh, 'OBJECT_DIR := %s' % self.tree.object_directory
        print >>fh, 'DIST_DIR := $(OBJECT_DIR)/dist'
        print >>fh, 'DIST_INCLUDE_DIR := $(DIST_DIR)/include'
        print >>fh, 'DIST_IDL_DIR := $(DIST_DIR)/idl'
        print >>fh, 'TEMP_DIR := $(DIST_DIR)/tmp'
        print >>fh, 'NSINSTALL := $(OBJECT_DIR)/config/nsinstall'
        print >>fh, 'COPY := cp'
        print >>fh, ''

        # The first defined target in a Makefile is the default one. The name
        # 'default' reinforces this.
        print >>fh, 'default: export\n'

        print >>fh, 'export: distdirs idl file_exports\n'

        print >>fh, 'distdirs: $(DIST_DIR) $(DIST_INCLUDE_DIR) $(DIST_IDL_DIR)\n'

        state['phonies'] |= set(['default', 'export', 'distdirs'])

        # Directory creation targets
        print >>fh, '$(DIST_DIR) $(DIST_INCLUDE_DIR) $(DIST_IDL_DIR) $(TEMP_DIR):'
        print >>fh, '\t$(NSINSTALL) -D -m 775 "$@"\n'

    def _print_footer(self, state):
        fh = state['fh']

        # Define .PHONY target with collected list
        print >>fh, '.PHONY: %s\n' % ' \\\n  '.join(state['phonies'])

    def _print_idl_rules(self, state):
        '''Prints all the IDL rules.'''

        fh = state['fh']

        base_command = ' '.join([
            'PYTHONPATH="$(TOP_SOURCE_DIR)/other-licenses/ply:$(TOP_SOURCE_DIR)/xpcom/idl-parser"',
            'python',
            '$(TOP_SOURCE_DIR)/xpcom/idl-parser/header.py',
            '-I $(DIST_IDL_DIR)',
            '--cachedir=$(TEMP_DIR)',
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

            converted_filename = self.get_converted_path(filename)

            copy_targets.append(dist_idl_filename)
            convert_targets.append(out_header_filename)

            # Create a symlink from the source IDL file to the dist directory
            print >>fh, '%s: %s' % ( dist_idl_filename, converted_filename )
            print >>fh, '\t$(NSINSTALL) -R -m 644 "%s" $(DIST_IDL_DIR)\n' % converted_filename

            # The conversion target and rule
            dependencies = [self.get_converted_path(f) for f in metadata['dependencies']]
            print >>fh, '%s: %s' % ( out_header_filename, ' \\\n  '.join(dependencies) )
            print >>fh, '\t$(IDL_GENERATE_HEADER) -o "$@" "%s"\n' % converted_filename

        print >>fh, 'idl_install_idls: %s\n' % ' \\\n  '.join(copy_targets)
        print >>fh, 'idl_generate_headers: idl_install_idls \\\n  %s\n' % '  \\\n  '.join(convert_targets)
        print >>fh, 'idl: idl_install_idls idl_generate_headers\n'
        state['phonies'] |= set(['idl_install_idls', 'idl_generate_headers', 'idl'])

    def _print_file_exports(self, state):
        '''Prints targets for exporting files.'''

        fh = state['fh']

        dirs = sorted(self.tree.exports.keys())
        out_dirs = ['$(DIST_INCLUDE_DIR)%s' % d for d in dirs]

        print >>fh, '%s:' % ' '.join(out_dirs)
        print >>fh, '\t$(NSINSTALL) -D -m 775 "$@"\n'

        export_targets = []

        for dir in dirs:
            out_dir = '$(DIST_INCLUDE_DIR)%s' % dir

            if out_dir[-1:] != '/':
                out_dir += '/'

            source_filenames = sorted(self.tree.exports[dir].values())

            # We could have a unified target for all sources and invoke nsinstall
            # once, but that would be a lot of work for nsinstall. We go with
            # explicit per-filename targets. These should be highly
            # parallelized, so it shouldn't be a big issue.
            for source_filename in source_filenames:
                basename = os.path.basename(source_filename)
                out_filename = '%s%s' % ( out_dir, basename )
                source_converted = self.get_converted_path(source_filename)

                print >>fh, '%s: %s' % ( out_filename, source_converted )
                print >>fh, '\t$(NSINSTALL) -R -m 644 "%s" "%s"\n' % ( source_converted, out_dir )

                export_targets.append(out_filename)

        export_targets.sort()
        print >>fh, 'file_exports: %s\n' % ' \\\n  '.join(export_targets)
        state['phonies'].add('file_exports')
