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

# This file contains classes to hold metadata for build tree concepts.
# The classes in this file should be data-driven and dumb containers.

import os.path

class MakefileDerivedObject(object):
    '''Abstract class for something that was derived from a Makefile.'''

    __slots__ = (
        'used_variables'    # Keeps track of variables consulted to build this object
    )

    def __init__(self):
        self.used_variables = set()

    def add_used_variable(self, name):
        '''Register a variable as used to create the object.

        This is strictly an optional feature. It can be used to keep track
        of which variables are relevant to an object. If you add all the
        used variables from all the derived objects from a single Makefile
        together, you can also see which variables were never used. This can
        be used to eliminate dead code or improve the Makefile parsing
        process.
        '''
        self.used_variables.add(name)

    def get_used_variables(self):
        return self.used_variables

class BuildTreeInfo(object):
    '''Represents the build system data for an entire build tree.

    This is effectively a high-level API into what the current build
    configuration says to do. It is designed to be loosely coupled from the
    definition of the build config and how things are actually built. In other
    words, you should be able to construct one of these instances using
    arbitrary means and then feed an instance to something that is able to
    build the tree.
    '''

    def __init__(self):
        self.modules = {}

    def register_module(self, name, path):
        '''Register a module at a specified path.'''
        self.modules[name] = path

class LibraryInfo(MakefileDerivedObject):
    '''Represents a library in the Mozilla build system.

    A library is likely a C or C++ static or shared library.
    '''

    __slots__ = (
        'cpp_sources',         # C++ source files
        'cxx_flags',           # C++ compiler flags
        'defines',             # set of #define strings to use when compiling this library
        'export_library',      # Whether to export the library
        'local_includes',      # Set of extra paths to search for included files in
        'name',                # The name of the library
        'pic',                 # Whether to generate position-independent code
        'is_component',        # Whether the library is a component, whatever that means
        'is_static',           # Whether the library is static
        'shared_library_libs', # Set of static libraries to link in when building
                               # a shared library
        'short_libname',       # This doesn't appear to be used anywhere
                               # significant, but we capture it anyway.
    )

    def __init__(self):
        '''Create a new library instance.'''
        MakefileDerivedObject.__init__(self)

        self.cpp_sources         = set()
        self.cxx_flags           = set()
        self.defines             = set()
        self.export_library      = None
        self.local_includes      = set()
        self.pic                 = None
        self.is_component        = None
        self.is_static           = None
        self.shared_library_libs = set()
        self.short_libname       = None


class ExportsInfo(MakefileDerivedObject):
    '''Represents a set of objects to export, typically headers.'''

    __slots__ = (
        'exports', # dict of str -> set of namespace to filenames
    )

    def __init__(self):
        MakefileDerivedObject.__init__(self)

        self.exports = {}

    def add_export(self, name, namespace=None):
        '''Adds an export for the library.

        Exports can belong to namespaces. If no namespace is passed, exports
        will belong to the global/default namespace.'''

        key = namespace
        if key is None:
            key = ''

        d = self.exports.get(key, set())
        d.add(name)
        self.exports[key] = d

class XPIDLInfo(MakefileDerivedObject):
    '''Holds information related to XPIDL files.'''

    __slots__ = (
        'module',      # Name of XPIDL module
        'sources',     # Set of source IDL filenames
    )

    def __init__(self):
        MakefileDerivedObject.__init__(self)

        self.module  = None
        self.sources = set()

class UsedVariableInfo(MakefileDerivedObject):
    '''Non-abstract version of MakefileDerivedObject.

    This is used simply for variable tracking purposes.
    '''

    def __init__(self):
        MakefileDerivedObject.__init__(self)

class MiscInfo(MakefileDerivedObject):
    '''Used to track misc info that isn't captured well anywhere else.'''

    __slots__ = (
        'is_gre_module'   # Whether the Makefile is a GRE module and has prefs
    )

    def __init__(self):
        MakefileDerivedObject.__init__(self)

        self.is_gre_module = None