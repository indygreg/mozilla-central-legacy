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

# This file contains classes for parsing/reading/analyzing Makefiles in the
# Mozilla source tree.

from os import walk
from os.path import abspath, dirname, exists, join
from pymake.data import Makefile, StringExpansion
from pymake.parser import parsefile
from pymake.parserdata import SetVariable

class MozillaMakefile(object):
    '''A wrapper around a PyMake Makefile tailored to Mozilla's build system'''

    def __init__(self, makefile):
        '''Construct from an existing PyMake Makefile instance'''
        self.makefile = makefile
        self.filename = makefile.included[0][0]
        self.dir      = dirname(self.filename)

        self.module = self.get_module()

        depth = self.get_variable_string('DEPTH')
        if not depth:
            depth = self.get_variable_string('MOD_DEPTH')

        self.objtop = abspath(join(self.dir, depth))
        absdir = abspath(self.dir)

        self.reldir = absdir[len(self.objtop)+1:]

    def get_variable_string(self, name):
        v = self.makefile.variables.get(name, True)[2]
        if v is None:
            return None

        return v.resolvestr(self.makefile, self.makefile.variables)

    def get_variable_split(self, name):
        v = self.makefile.variables.get(name, True)[2]
        if v is None:
            return []

        return v.resolvesplit(self.makefile, self.makefile.variables)

    def has_variable(self, name):
        v = self.makefile.variables.get(name, True)[2]
        return v is not None

    def get_dirs(self):
        dirs = self.get_variable_split('DIRS')
        dirs.extend(self.get_variable_split('PARALLEL_DIRS'))

        return dirs

    def is_module(self):
        return self.has_variable('MODULE')

    def get_module(self):
        return self.get_variable_string('MODULE')

    def get_library(self):
        return self.get_variable_string('LIBRARY')

    def is_xpidl_module(self):
        return self.has_variable('XPIDL_MODULE')

    def get_cpp_sources(self):
        return self.get_variable_split('CPPSRCS')

    def get_c_sources(self):
        return self.get_variable_split('CSRCS')

    def get_top_source_dir(self):
        return self.get_variable_string('topsrcdir')

    def get_source_dir(self):
        return self.get_variable_string('srcdir')

    def get_exports(self):
        return self.get_variable_split('EXPORTS')

    def get_defines(self):
        return self.get_variable_string('DEFINES')

    def get_transformed_reldir(self):
        return self.reldir.replace('\\', '_').replace('/', '_')

    def get_library_info(self):
        library = self.get_library()
        assert(library is not None)

        exports = {}
        for export in self.get_variable_split('EXPORTS'):
            if '' not in exports:
                exports[''] = []
            exports[''].append(export)

        for namespace in self.get_variable_split('EXPORTS_NAMESPACES'):
            exports[namespace] = []
            for s in self.get_variable_split('EXPORTS_%s' % namespace):
                exports[namespace].append(s)

        d = {
            'name':            library,
            'normalized_name': self.get_transformed_reldir(),
            'dir':             self.dir,
            'reldir':          self.reldir,
            'objtop':          self.objtop,
            'defines':         self.get_defines(),
            'cppsrcs':         self.get_cpp_sources(),
            'xpidlsrcs':       self.get_variable_split('XPIDLSRCS'),
            'exports':         exports,
            'srcdir':          self.get_variable_string('srcdir'),

            # This should arguably be CXXFLAGS and not the COMPILE_ variant
            # which also pulls a lot of other definitions in. If we wanted to
            # do things properly, we could probably pull in the variables
            # separately and define in a property sheet. But that is more
            # complex. This method is pretty safe. Although, it does produce
            # a lot of redundancy in the individual project files.
            'cxxflags':        self.get_variable_split('COMPILE_CXXFLAGS'),

            'static':          self.get_variable_string('FORCE_STATIC_LIB') == '1',
            'shared':          len(self.get_variable_split('SHARED_LIBRARY_LIBS')) > 0,
        }

        return d

class TreeCritic(object):
    '''A critic for a build tree.

    The tree critic is the master critic. It scours a build directory looking
    for everything it and its fellow critics know about. You point it at a
    directory and it goes.
    '''

    def __init__(self):
        pass

    def critique(self, dir):
        makefile_filenames = []

        for root, dirs, files in walk(dir):
            for name in files:
                if name == 'Makefile':
                    makefile_filenames.append(join(root, name))

        makefile_critic = MakefileCritic()

        for filename in makefile_filenames:
            for critique in makefile_critic.critique(filename):
                yield critique

class MakefileCritic(object):
    '''A critic for Makefiles.

    It performs analysis of Makefiles and gives criticisms on what it doesn't
    like. Its job is to complain so Makefiles can be better.
    '''
    CRITIC_ERROR = ( 'CRITIC_ERROR', 3 )
    UNDERSCORE_PREFIXED_UPPERCASE_VARIABLE = ( 'UNDERSCORE_PREFIXED_UPPERCASE_VARIABLE', 2 )

    def __init__(self):
        pass

    def critique(self, filename):
        if not exists(filename):
            raise 'file does not exist: %s' % filename

        statements = parsefile(filename)

        state = {
            'filename':   filename,
            'statements': statements
        }

        for critique in self.critique_statements(state):
            yield (filename, critique[0][0], critique[0][1], critique[1])

    def critique_statements(self, state):
        # Assemble the variables
        variable_names = []

        for statement in state['statements']:
            if isinstance(statement, SetVariable):
                vnameexp = statement.vnameexp
                if isinstance(vnameexp, StringExpansion):
                    variable_names.append(vnameexp.s)
                else:
                    #yield (self.CRITIC_ERROR, 'Unhandled vnamexp type: %s' % type(vnameexp))
                    pass
            else:
                #yield (self.CRITIC_ERROR, 'Unhandled statement type: %s' % type(statement))
                pass

        state['variable_names'] = variable_names
        for critique in self.critique_variable_names(state):
            yield critique

    def critique_variable_names(self, state):
        '''Critique variable names.'''
        for name in state['variable_names']:
            # UPPERCASE names cannot begin with an underscore
            if name.isupper() and name[0] == '_':
                yield (self.UNDERSCORE_PREFIXED_UPPERCASE_VARIABLE, name)