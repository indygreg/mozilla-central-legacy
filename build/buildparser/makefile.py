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

'''This file contains classes for parsing/reading/analyzing Makefiles in the
Mozilla source tree.

One set of related classes are the Critics. A critic is an entity that
analyzes something and issues complaints, or critiques. Each complaint has
a severity and metadata associated with it. In the ideal world, the critics
are always happy and they don't complain, ever. In the real world, changes
are made which upset the critics and they get angry.
'''

import os
import os.path
import pymake.data
import pymake.parser
import pymake.parserdata

class Makefile(object):
    '''A generic wrapper around a PyMake Makefile.

    This provides a convenient API that is missing from PyMake. Perhaps it will
    be merged in some day.
    '''
    def __init__(self, filename):
        '''Construct a Makefile from a file'''
        if not os.path.exists(filename):
            raise Exception('Path does not exist: %s' % filename)

        self.filename = filename
        self.dir      = os.path.dirname(filename)

        # Each Makefile instance can look at two sets of data, the low-level
        # parser output or the high-level "this is what's in a Makefile". Both
        # data sets are lazy-loaded for performance reasons.

        # The Makefile is lazy loaded because under some conditions loading the
        # Makefile can cause PyMake to explode. I [gps] think that PyMake is
        # trying to evaluate variables during loading and the PyMake
        # environment isn't set up properly to allow the exec(), etc calls
        # to succeed. We either need to produce a proper environment for PyMake
        # or fix PyMake so it doens't die a horrible death. Until then, we lazy
        # load the actual Makefile.
        self.makefile = None

        # The following are caches for low-level statement data.
        self.statements = None
        self.own_variables = None

    def has_variable(self, name):
        '''Determines whether a named variable is defined.'''
        if self.makefile is None:
            self._load_makefile()

        v = self.makefile.variables.get(name, True)[2]
        return v is not None

    def get_variable_string(self, name):
        '''Obtain a named variable as a string.'''
        if self.makefile is None:
            self._load_makefile()

        v = self.makefile.variables.get(name, True)[2]
        if v is None:
            return None

        return v.resolvestr(self.makefile, self.makefile.variables)

    def get_variable_split(self, name):
        '''Obtain a named variable as a list.'''
        if self.makefile is None:
            self._load_makefile()

        v = self.makefile.variables.get(name, True)[2]
        if v is None:
            return []

        return v.resolvesplit(self.makefile, self.makefile.variables)

    def get_statements(self):
        '''Obtain all the low-level PyMake-parsed statements from the file.'''
        self._parse_file()

        return self.statements

    def get_own_variable_names(self, ignore_conditional=False):
        '''Returns a list of variables defined by the Makefile itself.

        This looks at the low-level parsed Makefile, before including other
        files, and determines which variables are defined.

        ignore_conditional can be used to filter out variables defined inside
        a conditional (e.g. #ifdef). By default, all variables are returned,
        even the ones inside conditionals that may not be evaluated.
        '''

        # Lazy-load and cache.
        if self.own_variables is None:
            self._load_own_variables()

        if ignore_conditional:
            return [n for n in self.own_variables.keys()]
        else:
            return [k for k, v in self.own_variables.iteritems() if not v[1]]

    def _load_makefile(self):
        self.makefile = pymake.data.Makefile(workdir=self.dir)
        self.makefile.include(self.filename)
        self.makefile.finishparsing()

    def _parse_file(self):
        if self.statements is None:
            self.statements = pymake.parser.parsefile(self.filename)

    def _load_own_variables(self):
        self._parse_file()

        # Name to tuple of ( number of definitions, defined anywhere in condition )
        vars = {}

        # We also need to collect SetVariable statements inside condition
        # blocks. Condition blocks just contain lists of statements, so we
        # recursively examine these all while adding to the same list.
        def examine_statements(statements, in_condition):
            for statement in statements:
                if isinstance(statement, pymake.parserdata.SetVariable):
                    vnameexp = statement.vnameexp
                    if isinstance(vnameexp, pymake.data.StringExpansion):
                        name = vnameexp.s

                        if not name in vars:
                            vars[name] = (1, in_condition)
                        else:
                            has_condition = vars[name][1]
                            if not has_condition:
                                has_condition = in_condition

                            vars[name] = ( vars[name][0] + 1, has_condition )
                    else:
                        raise Exception('Unhandled SetVariable vnameexp: %s' % type(vnameexp))

                elif isinstance(statement, pymake.parserdata.ConditionBlock):
                    for group in statement:
                        examine_statements(group[1], True)

        examine_statements(self.statements, False)

        self.own_variables = vars

class MozillaMakefile(Makefile):
    '''A Makefile with knowledge of Mozilla's build system.'''

    def __init__(self, filename):
        Makefile.__init__(self, filename)

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

    def get_reldir(self):
        absdir = os.path.abspath(self.dir)

        return absdir[len(self.objtop)+1:]

    def get_objtop(self):
        depth = self.get_variable_string('DEPTH')
        if not depth:
            depth = self.get_variable_string('MOD_DEPTH')

        return os.path.abspath(os.path.join(self.dir, depth))

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
        return self.get_reldir().replace('\\', '_').replace('/', '_')

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
            'reldir':          self.get_reldir(),
            'objtop':          self.get_objtop(),
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

class Critic(object):
    '''The following are critique severity levels ordered from worse to
    most tolerable.'''
    SEVERE = 1
    STERN  = 2
    HARSH  = 3
    CRUEL  = 4
    BRUTAL = 5

class TreeCritic(Critic):
    '''A critic for a build tree.

    The tree critic is the master critic. It scours a build directory looking
    for everything it and its fellow critics know about. You point it at a
    directory and it goes.
    '''

    def __init__(self):
        pass

    def critique(self, dir):
        makefile_filenames = []

        for root, dirs, files in os.walk(dir):
            for name in files:
                if name == 'Makefile':
                    makefile_filenames.append(os.path.join(root, name))

        makefile_critic = MakefileCritic()

        for filename in makefile_filenames:
            for critique in makefile_critic.critique(filename):
                yield critique

class MakefileCritic(Critic):
    '''A critic for Makefiles.

    It performs analysis of Makefiles and gives criticisms on what it doesn't
    like. Its job is to complain so Makefiles can be better.
    '''
    CRITIC_ERROR = ( 'CRITIC_ERROR', Critic.HARSH )
    UNDERSCORE_PREFIXED_UPPERCASE_VARIABLE = ( 'UNDERSCORE_PREFIXED_UPPERCASE_VARIABLE', Critic.STERN )

    def __init__(self):
        pass

    def critique(self, filename):
        makefile = MozillaMakefile(filename)

        statements = makefile.get_statements()

        state = {
            'filename':       filename,
            'statements':     statements,
            'variable_names': makefile.get_own_variable_names(),
        }

        for critique in self.critique_statements(state):
            yield (filename, critique[0][0], critique[0][1], critique[1])

        for critique in self.critique_variable_names(state):
            yield (filename, critique[0][0], critique[0][1], critique[1])

    def critique_statements(self, state):
        variable_names = []

        for statement in state['statements']:
            if isinstance(statement, pymake.parserdata.Command):
                # TODO do something
                pass
            elif isinstance(statement, pymake.parserdata.ConditionBlock):
                # TODO do anything?
                pass
            elif isinstance(statement, pymake.parserdata.EmptyDirective):
                # TODO do anything?
                pass
            elif isinstance(statement, pymake.parserdata.ExportDirective):
                # TODO do anything?
                pass
            elif isinstance(statement, pymake.parserdata.Include):
                # TODO do something
                pass
            elif isinstance(statement, pymake.parserdata.Rule):
                # TODO do something
                pass
            elif isinstance(statement, pymake.parserdata.SetVariable):
                # TODO do something
                pass
            elif isinstance(statement, pymake.parserdata.StaticPatternRule):
                # TODO do anything?
                pass
            elif isinstance(statement, pymake.parserdata.VPathDirective):
                # TODO do something
                pass
            else:
                yield (self.CRITIC_ERROR, 'Unhandled statement type: %s' % type(statement))
                #pass

    def critique_variable_names(self, state):
        '''Critique variable names.'''
        for name in state['variable_names']:
            # UPPERCASE names cannot begin with an underscore
            if name.isupper() and name[0] == '_':
                yield (self.UNDERSCORE_PREFIXED_UPPERCASE_VARIABLE, name)