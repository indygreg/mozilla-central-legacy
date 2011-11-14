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

from . import data
from . import makefile

import os
import os.path
import sys
import xpidl

class ObjectDirectoryParser(object):
    '''A parser for an object directory.

    This holds state for a specific build instance. It is constructed from an
    object directory and gathers information from the files it sees.
    '''

    __slots__ = (
        'dir',                      # Directory data was extracted from.
        'parsed',
        'top_makefile',
        'top_source_dir',
        'retain_metadata',          # Boolean whether Makefile metadata is being
                                    # retained.
        'all_makefile_paths',       # List of all filesystem paths discovered
        'relevant_makefile_paths',  # List of all Makefiles relevant to our interest
        'ignored_makefile_paths',   # List of Makefile paths ignored
        'handled_makefile_paths',   # Set of Makefile paths which were processed
        'error_makefile_paths',     # Set of Makefile paths experiencing an error
                                    # during processing.
        'included_files',           # Dictionary defining which makefiles were
                                    # included from where. Keys are the included
                                    # filename and values are sets of paths that
                                    # included them.
        'variables',                # Dictionary holding details about variables.
        'rules',                    # Dictionary of all rules encountered. Keys
                                    # Makefile paths. Values are lists of dicts
                                    # describing each rule.
        'unhandled_variables',

        'tree', # The parsed build tree
    )

    # Some directories cause PyMake to lose its mind when parsing. This is
    # likely due to a poorly configured PyMake environment. For now, we just
    # skip over these.
    # TODO support all directories.
    IGNORE_DIRECTORIES = [os.path.normpath(f) for f in [
        'browser/app',
        'browser/installer',
        'browser/locales',   # $(shell) in global scope
        'js',
        'modules',
        'nsprpub',
        'security/manager',
        'toolkit/content',
        'toolkit/xre',
        'widget',
        'xpcom/reflect/xptcall',
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

        self.top_makefile = makefile.MozillaMakefile(top_makefile_path)
        self.top_source_dir = self.top_makefile.get_top_source_dir()

        # The following hold data once we are parsed.
        self.retain_metadata         = False
        self.all_makefile_paths      = None
        self.relevant_makefile_paths = None
        self.ignored_makefile_paths  = None
        self.handled_makefile_paths  = None
        self.error_makefile_paths    = None
        self.included_files          = {}
        self.unhandled_variables     = {}
        self.rules                   = {}
        self.variables               = {}

    def load_tree(self, retain_metadata=False):
        '''Loads data from the entire build tree into the instance.'''

        self.retain_metadata = retain_metadata

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
        self.error_makefile_paths   = set()

        self.tree = data.TreeInfo()
        self.tree.object_directory = self.dir

        # Traverse over all relevant Makefiles
        for path in self.relevant_makefile_paths:
            try:
                self.load_makefile(path, retain_metadata=retain_metadata)
            except Exception, e:
                print 'Exception loading Makefile: %s' % path
                print e
                self.error_makefile_paths.add(path)

        # Look for JAR Manifests in source directories and extract data from
        # them.
        for d in self.tree.source_directories:
            jarfile = os.path.normpath(os.path.join(d, 'jar.mn'))

            if os.path.exists(jarfile):
                self.tree.jar_manifests[jarfile] = self.parse_jar_manifest(jarfile)

        # Parse the IDL files.
        for m, d in self.tree.xpidl_modules.iteritems():
            for f in d['sources']:
                try:
                    filename = os.path.normpath(os.path.join(d['source_dir'], f))
                    self.tree.idl_sources[filename] = self.parse_idl_file(filename)
                except Exception, e:
                    print 'Error parsing IDL file: %s' % filename
                    print e

    def load_makefile(self, path, retain_metadata=False):
        '''Loads an indivudal Makefile into the instance.'''
        assert(os.path.normpath(path) == path)
        assert(os.path.isabs(path))

        self.handled_makefile_paths.add(path)
        m = makefile.MozillaMakefile(path)

        own_variables = set(m.get_own_variable_names(include_conditionals=True))
        own_variables_unconditional = set(m.get_own_variable_names(include_conditionals=False))

        # prune out lowercase variables, which are defined as local
        lowercase_variables = set()
        for v in own_variables:
            if v.islower():
                lowercase_variables.add(v)

            if v not in self.variables:
                self.variables[v] = {
                    'paths':               set(),
                    'conditional_paths':   set(),
                    'unconditional_paths': set(),
                }

            info = self.variables[v]
            info['paths'].add(path)
            if v in own_variables_unconditional:
                info['unconditional_paths'].add(path)
            else:
                info['conditional_paths'].add(path)

        used_variables = set()

        # We now register this Makefile with the monolithic data structure
        for obj in m.get_data_objects():
            used_variables |= obj.used_variables

            if obj.source_dir is not None:
                self.tree.source_directories.add(obj.source_dir)

            if obj.top_source_dir is not None and self.tree.top_source_directory is None:
                self.tree.top_source_directory = os.path.normpath(obj.top_source_dir)

            if isinstance(obj, data.XPIDLInfo):
                module = obj.module
                assert(module is not None)

                self.tree.xpidl_modules[module] = {
                    'source_dir': obj.source_dir,
                    'module':     module,
                    'sources':    obj.sources,
                }

                self.tree.idl_directories.add(obj.source_dir)
            elif isinstance(obj, data.ExportsInfo):
                for k, v in obj.exports.iteritems():
                    k = '/%s' % k

                    if k not in self.tree.exports:
                        self.tree.exports[k] = {}

                    for f in v:
                        if f in v:
                            print 'WARNING: redundant exports file: %s (from %s)' % ( f, obj.source_dir )

                        search_paths = [obj.source_dir]
                        search_paths.extend(obj.vpath)

                        found = False

                        for path in search_paths:
                            filename = os.path.join(path, f)
                            if not os.path.exists(filename):
                                continue

                            found = True
                            self.tree.exports[k][f] = filename
                            break

                        if not found:
                            print 'Could not find export file: %s from %s' % ( f, obj.source_dir )
            elif isinstance(obj, data.MiscInfo):
                if obj.included_files is not None:
                    for path in obj.included_files:
                        v = self.included_files.get(path, set())
                        v.add(m.filename)
                        self.included_files[path] = v

        unused_variables = own_variables - used_variables - lowercase_variables
        for var in unused_variables:
            entry = self.unhandled_variables.get(var, set())
            entry.add(path)
            self.unhandled_variables[var] = entry

        if retain_metadata:
            self.collect_makefile_metadata(m)

    def collect_makefile_metadata(self, m):
        '''Collects metadata from a Makefile into memory.'''
        assert(isinstance(m, makefile.MozillaMakefile))

        if m.filename not in self.rules:
            self.rules[m.filename] = []

        rules = self.rules[m.filename]

        for rule in m.get_rules():
            rule['condition_strings'] = [m.condition_to_string(c) for c in rule['conditions']]
            rules.append(rule)

    def parse_jar_manifest(self, filename):
        '''Parse the contents of a JAR manifest filename into a data structure.'''

        # TODO hook into JarMaker.py to parse the JAR
        return {}

    def parse_idl_file(self, filename):
        idl_data = open(filename).read()
        p = xpidl.IDLParser()
        idl = p.parse(idl_data, filename=filename)

        # TODO it probably isn't correct to search *all* idl directories
        # because the same file may be defined multiple places.
        idl.resolve(self.tree.idl_directories, p)

        return {
            'filename':     filename,
            'dependencies': [os.path.normpath(dep) for dep in idl.deps],
        }

    def get_rules_for_makefile(self, path):
        '''Obtain all the rules for a Makefile at a path.'''

        if not self.retain_metadata:
            raise Exception('Metadata is not being retained. Refusing to proceed.')

        return self.rules.get(path, [])

    def get_target_names_from_makefile(self, path):
        '''Obtain a set of target names from a Makefile.'''
        if not self.retain_metadata:
            raise Exception('Metadata is not being retained. Refusing to proceed.')

        targets = set()

        for rule in self.rules.get(path, []):
            targets |= set(rule['targets'])

        return targets