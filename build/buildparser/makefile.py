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

from . import data

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

    def get_own_variable_names(self, include_conditionals=True):
        '''Returns a list of variables defined by the Makefile itself.

        This looks at the low-level parsed Makefile, before including other
        files, and determines which variables are defined.

        include_conditionals can be used to filter out variables defined inside
        a conditional (e.g. #ifdef). By default, all variables are returned,
        even the ones inside conditionals that may not be evaluated.
        '''

        # Lazy-load and cache.
        if self.own_variables is None:
            self._load_own_variables()

        if include_conditionals:
            return [n for n in self.own_variables.keys()]
        else:
            return [k for k, v in self.own_variables.iteritems() if not v[1]]

    def has_own_variable(self, name, include_conditionals=True):
        '''Returns whether the specified variable is defined in the Makefile
        itself (as opposed to being defined in an included file.'''
        if self.own_variables is None:
            self._load_own_variables()

        return name in self.own_variables.keys()

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

    '''Traits that can identify a Makefile'''
    MODULE       = 1
    LIBRARY      = 2
    DIRS         = 3
    XPIDL_MODULE = 4
    EXPORTS      = 5
    TEST         = 6

    '''Variables common in most Makefiles that aren't really that special.

    This list is used to help identify variables we don't do anything with.'''
    COMMON_VARIABLES = [
        'DEPTH',            # Defined at top of file
        'topsrcdir',        # Defined at top of file
        'srcdir',           # Defined at top of file
        'VPATH',            # Defined at top of file
        'relativesrcdir',   # Defined at top of file. # TODO is this used by anything?
        'DIRS',             # Path traversal
        'PARALLEL_DIRS',    # Path traversal
    ]

    def __init__(self, filename):
        Makefile.__init__(self, filename)

        self.traits = None

    def get_traits(self):
        '''Obtain traits of the Makefile.

        Traits are recognized patterns that invoke special functionality in
        Mozilla's Makefiles. Traits are identified by the presence of specific
        named variables.'''
        if self.traits is not None:
            return self.traits

        self.traits = set()
        variable_names = self.get_own_variable_names(include_conditionals=True)
        for name in variable_names:
            if name == 'MODULE':
                self.traits.add(self.MODULE)
            elif name == 'LIBRARY_NAME':
                self.traits.add(self.LIBRARY)
            elif name == 'DIRS' or name == 'PARALLEL_DIRS':
                self.traits.add(self.DIRS)
            elif name == 'XPIDL_MODULE':
                self.traits.add(self.XPIDL_MODULE)
            elif name == 'EXPORTS':
                self.traits.add(self.EXPORTS)
            elif name in ('_TEST_FILES', 'XPCSHELL_TESTS', '_BROWSER_TEST_FILES', '_CHROME_TEST_FILES'):
                self.traits.add(self.TEST)

        return self.traits

    def get_dirs(self):
        dirs = self.get_variable_split('DIRS')
        dirs.extend(self.get_variable_split('PARALLEL_DIRS'))

        return dirs

    def is_module(self):
        return self.MODULE in self.get_traits()

    def is_xpidl_module(self):
        return self.XPIDL_MODULE in self.get_traits()

    def get_module(self):
        return self.get_variable_string('MODULE')

    def get_reldir(self):
        absdir = os.path.abspath(self.dir)

        return absdir[len(self.get_objtop())+1:]

    def get_objtop(self):
        depth = self.get_variable_string('DEPTH')
        if not depth:
            depth = self.get_variable_string('MOD_DEPTH')

        return os.path.abspath(os.path.join(self.dir, depth))

    def get_top_source_dir(self):
        return self.get_variable_string('topsrcdir')

    def get_source_dir(self):
        return self.get_variable_string('srcdir')

    def get_transformed_reldir(self):
        return self.get_reldir().replace('\\', '_').replace('/', '_')

    def get_library_info(self):
        '''Obtain information for the library defined by this Makefile.

        Returns a data.LibraryInfo instance'''
        l = data.LibraryInfo()

        l.add_used_variable('LIBRARY_NAME')
        name = self.get_variable_string('LIBRARY_NAME')
        assert(name is not None)
        l.name = name

        l.add_used_variable('DEFINES')
        for define in self.get_variable_split('DEFINES'):
            if define[0:2] == '-D':
                l.defines.add(define[2:])
            else:
                l.defines.add(define)

        l.add_used_variable('CFLAGS')
        for f in self.get_variable_split('CFLAGS'):
            l.c_flags.add(f)

        l.add_used_variable('CXXFLAGS')
        for f in self.get_variable_split('CXXFLAGS'):
            l.cxx_flags.add(f)

        l.add_used_variable('CPPSRCS')
        for f in self.get_variable_split('CPPSRCS'):
            l.cpp_sources.add(f)

        # LIBXUL_LIBRARY implies static library generation and presence in
        # libxul.
        l.add_used_variable('LIBXUL_LIBRARY')
        if self.has_own_variable('LIBXUL_LIBRARY'):
            l.is_static = True

        # FORCE_STATIC_LIB forces generation of a static library
        l.add_used_variable('FORCE_STATIC_LIB')
        if self.has_own_variable('FORCE_STATIC_LIB'):
            l.is_static = True

        # IS_COMPONENT is used for verification. It also has side effects for
        # linking flags.
        l.add_used_variable('IS_COMPONENT')
        if self.has_own_variable('IS_COMPONENT'):
            l.is_component = self.get_variable_string('IS_COMPONENT') == '1'

        l.add_used_variable('EXPORT_LIBRARY')
        if self.has_own_variable('EXPORT_LIBRARY'):
            l.export_library = self.get_variable_string('EXPORT_LIBRARY') == '1'

        l.add_used_variable('LOCAL_INCLUDES')
        for s in self.get_variable_split('LOCAL_INCLUDES'):
            if s[0:2] == '-I':
                l.local_includes.add(s[2:])
            else:
                l.local_includes.add(s)

        # SHORT_LIBNAME doesn't appears to be used, but we preserve it anyway.
        l.add_used_variable('SHORT_LIBNAME')
        if self.has_own_variable('SHORT_LIBNAME'):
            l.short_libname = self.get_variable_string('SHORT_LIBNAME')

        l.add_used_variable('SHARED_LIBRARY_LIBS')
        for lib in self.get_variable_split('SHARED_LIBRARY_LIBS'):
            l.shared_library_libs.add(lib)

        return l

    def get_data_objects(self):
        '''Retrieve data objects derived from the Makefile.

        This is the main function that extracts metadata from individual
        Makefiles and turns them into Python data structures.

        This method emits a set of MakefileDerivedObjects which describe the
        Makefile. These objects each describe an individual part of the
        build system, e.g. libraries, IDL files, tests, etc. These emitted
        objects can be fed into another system for conversion to another
        build system, fed into a monolithic data structure, etc.
        '''
        misc = data.MiscInfo()
        tracker = data.UsedVariableInfo()
        for v in self.COMMON_VARIABLES:
            tracker.add_used_variable(v)

        traits = self.get_traits()

        if self.MODULE in traits:
            tracker.add_used_variable('MODULE')
            # TODO emit MakefileDerivedObject instance
            #tree.register_module(self.get_module(), self.dir)

        if self.LIBRARY in traits:
            li = self.get_library_info()
            yield li

        # MODULE_NAME is only used for error checking, it appears.
        tracker.add_used_variable('MODULE_NAME')

        # EXPORTS and friends holds information on what files to copy
        # to an output directory.
        if self.EXPORTS in traits:
            exports = data.ExportsInfo()
            exports.add_used_variable('EXPORTS')
            for export in self.get_variable_split('EXPORTS'):
                exports.add_export(export, namespace=None)

            exports.add_used_variable('EXPORTS_NAMESPACES')
            for namespace in self.get_variable_split('EXPORTS_NAMESPACES'):
                varname = 'EXPORTS_%s' % namespace
                exports.add_used_variable(varname)
                for s in self.get_variable_split(varname):
                    exports.add_export(s, namespace=namespace)

            yield exports

        # XP IDL file generation
        if self.XPIDL_MODULE in traits:
            idl = data.XPIDLInfo()
            idl.add_used_variable('XPIDL_MODULE')
            idl.module = self.get_variable_string('XPIDL_MODULE')

            idl.add_used_variable('XPIDLSRCS')
            for f in self.get_variable_split('XPIDLSRCS'):
                idl.sources.add(f)

            yield idl

        # Test definitions
        if self.TEST in traits:
            ti = data.TestInfo()

            # Regular test files
            ti.add_used_variable('_TEST_FILES')
            if self.has_own_variable('_TEST_FILES'):
                for f in self.get_variable_split('_TEST_FILES'):
                    ti.test_files.add(f)

            # Identifies directories holding xpcshell test files
            ti.add_used_variable('XPCSHELL_TESTS')
            if self.has_own_variable('XPCSHELL_TESTS'):
                for dir in self.get_variable_split('XPCSHELL_TESTS'):
                    ti.xpcshell_test_dirs.add(dir)

            # Files for browser tests
            ti.add_used_variable('_BROWSER_TEST_FILES')
            if self.has_own_variable('_BROWSER_TEST_FILES'):
                for f in self.get_variable_split('_BROWSER_TEST_FILES'):
                    ti.browser_test_files.add(f)

            # Files for chrome tests
            ti.add_used_variable('_CHROME_TEST_FILES')
            if self.has_own_variable('_CHROME_TEST_FILES'):
                for f in self.get_variable_split('_CHROME_TEST_FILES'):
                    ti.chrome_test_files.add(f)

            yield ti

        misc.add_used_variable('GRE_MODULE')
        if self.has_own_variable('GRE_MODULE'):
            misc.is_gre_module = True

        #misc.add_used_variable('PLATFORM_DIR')
        #for d in self.get_variable_split('PLATFORM_DIR'):
        #    misc.platform_dirs.add(d)

        #misc.add_used_variable('CHROME_DEPS')
        #for d in self.get_variable_split('CHROME_DEPS'):
        #    misc.chrome_dependencies.add(d)

        yield tracker
        yield misc

        #info = self.get_module_data(dir)
        #names = []
        #for library in info['libraries']:
        #    proj, id, name = builder.build_project_for_library(
        #        library, name, version=version
        #    )
        #
        #    handle_project(proj, id, name)
        #    names.append(name)
        #
        #    for idl in library['xpidlsrcs']:
        #        source = join('$(MOZ_SOURCE_DIR)', library['reldir'], idl)
        #        top_copy[source] = join('$(MOZ_OBJ_DIR)', 'dist', 'idl', idl)
        #
        #if len(names):
        #    print 'Wrote projects for libraries: %s' % ' '.join(names)
        #
        #for path in info['unhandled']:
        #    print 'Writing generic project for %s' % path
        #    m2 = self.get_dir_makefile(path)[0]
        #
        #    proj, id, name = builder.build_project_for_generic(
        #        m2, version=version
        #    )
        #    handle_project(proj, id, name)

        # fall back to generic case
        #print 'Writing generic project for %s' % directory
        #proj, id, name = builder.build_project_for_generic(
        #  m, version=version
        #)
        #handle_project(proj, id, name)

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

    TODO ensure the various flag variables are either '1' or not defined
    (FORCE_SHARED_LIB, GRE_MODULE, etc)
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