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

# This file contains classes and methods used to extract metadata from the
# Mozilla build system.
#
# TODO the Visual Studio foo needs to be purged and loosely coupled

import buildparser.data
import buildparser.makefile
import os
import os.path
import sys

class ObjectDirectoryParser(object):
    '''A parser for an object directory.

    Currently, this contains all the logic for extracting build data from
    Makefiles.
    '''

    # Some directories cause PyMake to lose its mind when parsing. This is
    # likely due to a poorly configured PyMake environment. For now, we just
    # skip over these.
    # TODO support all directories.
    IGNORE_DIRECTORIES = [os.path.normpath(f) for f in [
        'browser/app',
        'browser/installer',
        'js/src',
        'js/xpconnect',     # somehow forks and calls itself recursively
        'modules',
        'modules/libbz2',   # somehow forks and calls itself recursively
        'nsprpub',
        'security/manager', # hangs
        'toolkit/components/feeds',
        'toolkit/content',
        'toolkit/xre',
        'widget',
        'xpcom/reflect/xptcall'
    ]]

    def __init__(self, directory):
        '''Construct an instance from a directory.

        The given path must be absolute and must be a directory.
        '''
        if not os.path.isabs(directory):
            raise Exception('Path is not absolute: %s' % directory)

        if not os.path.isdir(directory):
            raise Exception('Path is not a directory: %s' % directory)

        self.dir = os.path.normpath(directory)
        self.parsed = False

        top_makefile_path = os.path.join(directory, 'Makefile')

        self.top_makefile = buildparser.makefile.MozillaMakefile(top_makefile_path)
        self.top_source_dir = self.top_makefile.get_top_source_dir()

        # The following hold data once we are parsed.
        self.tree = None
        self.all_makefile_paths = None
        self.relevant_makefile_paths = None
        self.ignored_makefile_paths = None
        self.handled_makefile_paths = None
        self.unhandled_variables = {}

    def load_tree(self):
        '''Loads data from the entire build tree into the instance.'''

        # First, collect all the Makefiles that we can find.
        self.all_makefile_paths = []
        for root, dirs, files in os.walk(self.dir):
            for name in files:
                if name == 'Makefile':
                    self.all_makefile_paths.append(os.path.normpath(os.path.join(root, name)))

        self.all_makefile_paths.sort()

        # Prune out the directories that have known problems.
        self.relevant_makefile_paths = []
        self.ignored_makefile_paths = []
        for path in self.all_makefile_paths:
            subpath = path[len(self.dir)+1:]

            relevant = True
            for ignore in self.IGNORE_DIRECTORIES:
                if subpath.find(ignore) == 0:
                    relevant = False
                    break

            if relevant:
                self.relevant_makefile_paths.append(path)
            else:
                self.ignored_makefile_paths.append(path)

        self.handled_makefile_paths = set()

        self.tree = buildparser.data.BuildTreeInfo()

        self.load_directory(self.dir)

        for k,v in sorted(self.unhandled_variables.iteritems(), key=lambda(k, v): (len(v), k)):
            print '%s\t%s' % ( len(v), k)

    def get_tiers(self):
        '''Returns all the tiers in the build system.'''
        return self.top_makefile.get_variable_split('TIERS')

    def get_tier_platform_dirs(self):
        '''Returns all the tier platform directories.'''
        return self.top_makefile.get_variable_split('tier_platform_dirs')

    def get_tier_base_dirs(self):
        '''Obtain all the tier base directories'''
        return self.top_makefile.get_variable_split('tier_base_dirs')

    def get_makefile_from_path(self, path):
        '''Obtain a MozillaMakefile for the given relative path.'''
        full = os.path.join(self.dir, path)
        file = os.path.join(full, 'Makefile')

        if not os.path.exists(file):
            raise Exception('Path does not exist: %s' % file)

        return buildparser.makefile.MozillaMakefile(file)

    def load_directory(self, directory):
        '''Loads an individual directory into the instance.'''
        assert(os.path.normpath(directory) == directory)
        assert(os.path.isabs(directory))

        makefile = None
        makefile_path = os.path.join(directory, 'Makefile')
        try:
            makefile = buildparser.makefile.MozillaMakefile(makefile_path)
        except:
            print 'Makefile could not be constructed: %s' % makefile_path
            return

        own_variables = set(makefile.get_own_variable_names(include_conditionals=True))

        # prune out lowercase variables, which are defined as local
        lowercase_variables = set()
        for v in own_variables:
            if v.islower():
                lowercase_variables.add(v)

        used_variables = set()

        # We now register this Makefile with the main tree
        for obj in makefile.get_data_objects():
            # TODO register with tree

            used_variables |= obj.used_variables

        unused_variables = own_variables - used_variables - lowercase_variables
        for var in unused_variables:
            entry = self.unhandled_variables.get(var, set())
            entry.add(makefile_path)
            self.unhandled_variables[var] = entry

        if len(unused_variables):
            print makefile.filename
            print unused_variables

        # Collect child directories from the relevant list only.
        subdirs = []
        for path in self.relevant_makefile_paths:
            dirname = os.path.dirname(path)

            if len(path) < len(dirname):
                continue

            if dirname == directory:
                continue

            if os.path.commonprefix([directory, dirname]) == directory:
                leftover = dirname[len(directory)+1:]

                if not len(leftover):
                    continue

                if leftover.count('/') > 0 or leftover.count('\\') > 0:
                    continue

                subdirs.append(leftover)

        subdirs.sort()
        for d in subdirs:
            full = os.path.normpath(os.path.join(directory, d))
            self.load_directory(full)

        self.handled_makefile_paths.add(makefile_path)
