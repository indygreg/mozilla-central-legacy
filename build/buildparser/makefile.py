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

class StatementCollection(object):
    '''Provides methods for interacting with PyMake's parser output.'''

    __slots__ = (
        # List of tuples describing ifdefs
        '_ifdefs',

        # List of our normalized statements.
        'statements',

        # Dictionary of variable names defined unconditionally. Keys are
        # variable names and values are lists of their SetVariable statements.
        'top_level_variables',
    )

    def __init__(self, filename=None):
        if filename:
            self._load_raw_statements(pymake.parser.parsefile(filename))
        else:
            raise Exception('Invalid arguments given to constructor')

    @property
    def ifdefs(self):
        '''Returns ifdef occurences in the collection.

        Each returned item in the list is a tuple of
          ( name, expected, is_conditional, location )
        '''
        if self._ifdefs is None:
            self._ifdefs = []
            for (s, level) in self.statements:
                if not isinstance(s, pymake.parserdata.IfdefCondition):
                    continue

                self._ifdefs.append (
                    self.expansion_to_string(s.exp),
                    s.expected,
                    level > 0,
                    (s.exp.loc.path, s.exp.loc.line, s.exp.loc.column)
                )

        return self._ifdefs

    @property
    def includes(self):
        '''Returns information about file includes.

        Each returned item is a tuple of
          ( path, is_conditional, location )
        '''
        for (s, level) in self.statements:
            if isinstance(s, pymake.parserdata.Include):
                yield (
                    self.expansion_to_string(s.exp),
                    level > 0,
                    (s.exp.loc.path, s.exp.loc.line, s.exp.loc.column)
                )

    @property
    def variable_assignments(self):
        '''Returns information about variable assignments.

        Each returned item is a tuple of:
          ( name, value, token, is_conditional, location )
        '''
        for (s, level) in self.statements:
            if not isinstance(s, pymake.parserdata.SetVariable):
                continue

            assert(isinstance(s.vnameexp, pymake.data.StringExpansion))

            name = s.vnameexp.s

            yield (
                name,
                s.value,
                s.token,
                level > 0,
                ( s.valueloc.path, s.valueloc.line, s.valueloc.column )
            )

    @property
    def unconditional_variable_assignments(self):
        '''Like variable_assignments but for variables being assigned
        unconditionally (e.g. outside ifdef, ifeq, etc).

        Returned items are tuples of:
          ( name, value, token, location )
        '''

        for (name, value, token, conditional, location) in self.variable_assignments:
            if conditional:
                continue

            yield (name, value, token, location)

    @property
    def rules(self):
        '''Returns information about rules defined by statements.

        This emits a list of objects which describe each rule.'''

        conditions_stack = []
        last_level       = 0
        current_rule     = None

        # TODO this doesn't properly capture commands within nested ifdefs
        # within rule blocks. Makefiles are crazy...
        for o, level in self.statements:
            if level > last_level:
                assert(isinstance(o, pymake.parserdata.Condition))
                conditions_stack.append(o)
                last_level = level
                continue
            elif level < last_level:
                for i in range(0, last_level - level):
                    conditions_stack.pop()

            last_level = level

            if isinstance(o, pymake.parserdata.Rule):
                if current_rule is not None:
                    yield current_rule

                current_rule = {
                    'commands':       [],
                    'conditions':     conditions_stack,
                    'doublecolon':    o.doublecolon,
                    'prerequisites':  self.expansion_to_list(o.depexp),
                    'targets':        self.expansion_to_list(o.targetexp),
                    'line':           o.targetexp.loc.line,
                }

            elif isinstance(o, pymake.parserdata.StaticPatternRule):
                if current_rule is not None:
                    yield current_rule

                current_rule = {
                    'commands':      [],
                    'conditions':    conditions_stack,
                    'doublecolon':   o.doublecolon,
                    'pattern':       self.expansion_to_list(o.patternexp),
                    'prerequisites': self.expansion_to_list(o.depexp),
                    'targets':       self.expansion_to_list(o.targetexp),
                    'line':          o.targetexp.loc.line,
                }

            elif isinstance(o, pymake.parserdata.Command):
                assert(current_rule is not None)
                current_rule['commands'].append(o)

        if current_rule is not None:
            yield current_rule

    def lines(self):
        '''Emit lines that constitute a Makefile for this collection.'''
        conditional_stack = []
        last_level = 0

        for (statement, level) in self.statements:
            print (level, statement)
            if (isinstance(statement, pymake.parserdata.ConditionBlock)):
                continue

            if level < last_level:
                for i in range(last_level - level):
                    record = conditional_stack.pop()

                    if record == 'ifdef':
                        yield 'endef\n'
                    elif record == 'ifeq':
                        yield 'endif\n'
                    else:
                        raise Exception('Unhandled conditional type in implementation: %s' % record)

            elif level > last_level:
                assert(isinstance(statement, pymake.parserdata.Condition))

                if isinstance(statement, pymake.parserdata.IfdefCondition):
                    conditional_stack.append('ifdef')
                elif isinstance(statement, pymake.parserdata.EqCondition):
                    conditional_stack.append('ifeq')
                else:
                    raise Exception('Unhandled condition: %s' % statement)

            last_level = level

            s = self.statement_to_string((statement, level))
            if s is None:
                continue

            yield s

    def expansion_to_string(self, e):
        '''Convert an expansion to a string.

        This effectively converts a string back to the form it was defined as
        in the Makefile. This is different from the resolvestr() method on
        Expansion classes because it doesn't actually expand variables.

        TODO consider adding this logic on the appropriate PyMake classes.
        '''
        if isinstance(e, pymake.data.StringExpansion):
            return e.s
        elif isinstance(e, pymake.data.Expansion):
            parts = []
            for ex, is_func in e:
                if is_func:
                    parts.append(self.function_to_string(ex))
                else:
                    parts.append(ex)

            return ''.join(parts)
        else:
            raise Exception('Unhandled expansion type: %s' % e)

    def expansion_to_list(self, e):
        '''Convert an expansion to a list.

        This is similar to expansion_to_string() except it returns a list.'''
        s = self.expansion_to_string(e).strip()

        if s == '':
            return []
        else:
            return s.split(' ')

    def function_to_string(self, ex):
        '''Convert a PyMake function instance to a string.'''
        if isinstance(ex, pymake.functions.AddPrefixFunction):
            return '$(addprefix %s, %s)' % (
                self.expansion_to_string(ex._arguments[0]),
                self.expansion_to_string(ex._arguments[1])
            )

        elif isinstance(ex, pymake.functions.AddSuffixFunction):
            return '$(addsuffix %s, %s)' % (
                self.expansion_to_string(ex._arguments[0]),
                self.expansion_to_string(ex._arguments[1])
            )

        elif isinstance(ex, pymake.functions.BasenameFunction):
            return '$(basename %s)' % self.expansion_to_string(ex._arguments[0])

        elif isinstance(ex, pymake.functions.CallFunction):
            return '$(call %s)' % ','.join(
                [self.expansion_to_string(e) for e in ex._arguments])

        elif isinstance(ex, pymake.functions.DirFunction):
            return '$(dir %s)' % self.expansion_to_string(ex._arguments[0])

        elif isinstance(ex, pymake.functions.ErrorFunction):
            return '$(error %s)' % self.expansion_to_string(ex._arguments[0])

        elif isinstance(ex, pymake.functions.EvalFunction):
            return '$(eval %s)' % self.expansion_to_string(ex._arguments[0])

        elif isinstance(ex, pymake.functions.FilterFunction):
            return '$(filter %s, %s)' % (
                self.expansion_to_string(ex._arguments[0]),
                self.expansion_to_string(ex._arguments[1])
            )

        elif isinstance(ex, pymake.functions.FilteroutFunction):
            return '$(filter-out %s, %s)' % (
                self.expansion_to_string(ex._arguments[0]),
                self.expansion_to_string(ex._arguments[1])
            )

        elif isinstance(ex, pymake.functions.FindstringFunction):
            return '$(findstring %s, %s)' % (
                self.expansion_to_string(ex._arguments[0]),
                self.expansion_to_string(ex._arguments[1])
            )

        elif isinstance(ex, pymake.functions.ForEachFunction):
            return '$(foreach %s, %s, %s)' % (
                self.expansion_to_string(ex._arguments[0]),
                self.expansion_to_string(ex._arguments[1]),
                self.expansion_to_string(ex._arguments[2])
            )

        elif isinstance(ex, pymake.functions.IfFunction):
            return '$(if %s)' % ','.join([
                self.expansion_to_string(e) for e in ex._arguments])

        elif isinstance(ex, pymake.functions.PatSubstFunction):
            return '$(patsubst %s, %s, %s)' % (
                self.expansion_to_string(ex._arguments[0]),
                self.expansion_to_string(ex._arguments[1]),
                self.expansion_to_string(ex._arguments[2])
            )

        elif isinstance(ex, pymake.functions.ShellFunction):
            return '$(shell %s)' % self.expansion_to_string(ex._arguments[0])

        elif isinstance(ex, pymake.functions.SortFunction):
            return '$(sort %s)' % self.expansion_to_string(ex._arguments[0])

        elif isinstance(ex, pymake.functions.StripFunction):
            return '$(strip %s)' % self.expansion_to_string(ex._arguments[0])

        elif isinstance(ex, pymake.functions.SubstitutionRef):
            return '$(%s:%s=%s)' % (
                self.expansion_to_string(ex.vname),
                self.expansion_to_string(ex.substfrom),
                self.expansion_to_string(ex.substto)
            )

        elif isinstance(ex, pymake.functions.SubstFunction):
            return '$(subst %s, %s, %s)' % (
                self.expansion_to_string(ex._arguments[0]),
                self.expansion_to_string(ex._arguments[1]),
                self.expansion_to_string(ex._arguments[2])
            )

        elif isinstance(ex, pymake.functions.WarningFunction):
            return '$(warning %s' % self.expansion_to_string(ex._arguments[0])

        elif isinstance(ex, pymake.functions.WildcardFunction):
            return '$(wildcard %s)' % self.expansion_to_string(ex._arguments[0])

        elif isinstance(ex, pymake.functions.VariableRef):
            if isinstance(ex.vname, pymake.data.StringExpansion):
                return '$(%s)' % ex.vname.s
            else:
                return self.expansion_to_string(ex.vname)

        else:
            raise Exception('Unhandled function type: %s' % ex)

    def condition_to_string(self, c):
        '''Convert a condition to a string representation.'''

        if isinstance(c, pymake.parserdata.IfdefCondition):
            s = self.expansion_to_string(c.exp)

            if c.expected:
                return 'ifdef %s' % s
            else:
                return 'ifndef %s' % s

        elif isinstance(c, pymake.parserdata.EqCondition):
            s = ','.join([
                self.expansion_to_string(c.exp1).strip(),
                self.expansion_to_string(c.exp2).strip()
            ])

            if c.expected:
                return 'ifeq (%s)' % s
            else:
                return 'ifneq (%s)' % s

        elif isinstance(c, pymake.parserdata.ElseCondition):
            return 'else'
        else:
            raise Exception('Unhandled condition type: %s' % c)

    def statement_to_string(self, statement):
        '''Convert a statement to its string representation.'''

        (s, level) = statement

        if isinstance(s, pymake.parserdata.Command):
            return '\t%s' % self.expansion_to_string(s.exp)
        elif isinstance(s, pymake.parserdata.Condition):
            return self.condition_to_string(s)
        elif isinstance(s, pymake.parserdata.ConditionBlock):
            return None
        elif isinstance(s, pymake.parserdata.EmptyDirective):
            return self.expansion_to_string(s.exp)
        elif isinstance(s, pymake.parserdata.ExportDirective):
            return 'export %s' % self.expansion_to_string(s.exp)
        elif isinstance(s, pymake.parserdata.Include):
            return 'include %s' % self.expansion_to_string(s.exp)
        elif isinstance(s, pymake.parserdata.Rule):
            sep = ':'
            if s.doublecolon:
                sep = '::'

            return '%s%s %s' % (
                self.expansion_to_string(s.targetexp),
                sep,
                self.expansion_to_string(s.depexp)
            )
        elif isinstance(s, pymake.parserdata.SetVariable):
            # TODO what is targetexp used for?
            return '%s %s %s' % (
                self.expansion_to_string(s.vnameexp),
                s.token,
                s.value
            )
        elif isinstance(s, pymake.parserdata.StaticPatternRule):
            sep = ':'
            if s.doublecolon:
                sep = '::'

            return '%s%s %s : %s' % (
                self.expansion_to_string(s.targetexp),
                sep,
                self.expansion_to_string(s.patternexp),
                self.expansion_to_string(s.depexp)
            )
        elif isinstance(s, pymake.parserdata.VPathDirective):
            return 'vpath %s' % self.expansion_to_string(s.exp)
        else:
            raise Exception('Unhandled statement type: %s' % s)

    def _load_raw_statements(self, statements):
        '''Loads PyMake's parser output into this container.'''

        last_statement = None

        # This converts PyMake statements into our internal representation.
        # We add a nested level marker to each statement. We also expand
        # ConditionBlocks and add semaphore statements to aid with analysis
        # later.
        def examine(stmts, level):
            for statement in stmts:
                # ConditionBlocks are composed of statement blocks.
                # Each group inside a condition block consists of a condition
                # and a set of statements to be executed when that condition
                # is satisfied.
                if isinstance(statement, pymake.parserdata.ConditionBlock):
                    yield (statement, level)
                    for condition, l in statement:
                        yield (condition, level + 1)

                        # Recursively add these conditional statements at the
                        # next level.
                        examine(l, level + 2)

                        yield ('EndConditional', level + 1)

                    yield ('EndConditionBlock', level)
                else:
                    yield (statement, level)

                    last_statement = statement

        self.statements = [s for s in examine(statements, 0)]

class Makefile(object):
    '''A generic wrapper around a PyMake Makefile.

    This provides a convenient API that is missing from PyMake. Perhaps it will
    be merged in some day.
    '''
    __slots__ = (
        'filename',      # Filename of the Makefile
        'dir',           # Directory holding the Makefile
        'makefile',      # PyMake Makefile instance
        'statements',    # List of PyMake-parsed statements in the main file
    )

    def __init__(self, filename):
        '''Construct a Makefile from a file'''
        if not os.path.exists(filename):
            raise Exception('Path does not exist: %s' % filename)

        self.filename = filename
        self.dir      = os.path.dirname(filename)

        # Each Makefile instance can look at two sets of data, the low-level
        # statements or the high-level Makefile from PyMake. Each data set is
        # lazy-loaded.

        # Care must be taken when loading the PyMake Makefile instance. When
        # this is loaded, PyMake will perform some evaluation during the
        # constructor. If the environment isn't sane (e.g. no proper shell),
        # PyMake will explode.
        self.makefile      = None
        self.statements    = None

    def variable_defined(self, name, search_includes=False):
        '''Returns whether a variable is defined in the Makefile.

        By default, it only looks for variables defined in the current
        file, not in included files.'''
        if search_includes:
            if self.makefile is None:
                self._load_makefile()

            v = self.makefile.variables.get(name, True)[2]
            return v is not None
        else:
            if self.statements is None:
                self._load_statements()

            return name in self.statements.defined_variables

    def get_variable_string(self, name, resolve=True):
        '''Obtain a named variable as a string.

        If resolve is True, the variable's value will be resolved. If not,
        the Makefile syntax of the expansion is returned. In either case,
        if the variable is not defined, None is returned.
        '''
        if resolve:
            if self.makefile is None:
                self._load_makefile()

            v = self.makefile.variables.get(name, True)[2]
            if v is None:
                return None

            return v.resolvestr(self.makefile, self.makefile.variables)
        else:
            if self.variable_assignments is None:
                self._load_variable_assignments()

            if name not in self.variable_assignments:
                return None

            if len(self.variable_assignments[name]) > 1:
                raise Exception('Cannot return string representation of variable set multiple times: %s' % name)

            return self.variable_assignments[name][0].value

    def get_variable_split(self, name):
        '''Obtain a named variable as a list.'''
        if self.makefile is None:
            self._load_makefile()

        v = self.makefile.variables.get(name, True)[2]
        if v is None:
            return []

        return v.resolvesplit(self.makefile, self.makefile.variables)

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

    def _load_statements(self):
        if self.statements is None:
            self.statements = StatementsCollection(filename=self.filename)

class MozillaMakefile(Makefile):
    '''A Makefile with knowledge of Mozilla's build system.'''

    '''Traits that can identify a Makefile'''
    MODULE       = 1
    LIBRARY      = 2
    DIRS         = 3
    XPIDL        = 4
    EXPORTS      = 5
    TEST         = 6
    PROGRAM      = 7

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
        'TOOL_DIRS',        # Path traversal
    ]

    '''This list tracks all variables that are still in the wild but aren't used'''
    UNUSED_VARIABLES = []

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
            elif name in ('XPIDL_MODULE', 'XPIDLSRCS', 'SDK_XPIDLSRCS'):
                self.traits.add(self.XPIDL)
            elif name in ('EXPORTS', 'EXPORTS_NAMESPACES'):
                self.traits.add(self.EXPORTS)
            elif name in ('_TEST_FILES', 'XPCSHELL_TESTS', '_BROWSER_TEST_FILES', '_CHROME_TEST_FILES'):
                self.traits.add(self.TEST)
            elif name in ('PROGRAM'):
                self.traits.add(self.PROGRAM)

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
        l = data.LibraryInfo(self)

        # It is possible for the name to be not defined if the trait was
        # in a conditional that wasn't true.
        l.add_used_variable('LIBRARY_NAME')
        name = self.get_variable_string('LIBRARY_NAME')
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

        l.add_used_variable('FORCE_SHARED_LIB')
        if self.has_own_variable('FORCE_SHARED_LIB'):
            l.is_shared = True

        l.add_used_variable('USE_STATIC_LIBS')
        if self.has_own_variable('USE_STATIC_LIBS'):
            l.use_static_libs = True

        # IS_COMPONENT is used for verification. It also has side effects for
        # linking flags.
        l.add_used_variable('IS_COMPONENT')
        if self.has_own_variable('IS_COMPONENT'):
            l.is_component = self.get_variable_string('IS_COMPONENT') == '1'

        l.add_used_variable('EXPORT_LIBRARY')
        if self.has_own_variable('EXPORT_LIBRARY'):
            l.export_library = self.get_variable_string('EXPORT_LIBRARY') == '1'

        l.add_used_variable('INCLUDES')
        for s in self.get_variable_split('INCLUDES'):
            if s[0:2] == '-I':
                l.includes.add(s[2:])
            else:
                l.includes.add(s)

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
        misc = data.MiscInfo(self)
        tracker = data.UsedVariableInfo(self)
        for v in self.COMMON_VARIABLES:
            tracker.add_used_variable(v)

        for v in self.UNUSED_VARIABLES:
            tracker.add_used_variable(v)

        traits = self.get_traits()

        if self.MODULE in traits:
            tracker.add_used_variable('MODULE')
            # TODO emit MakefileDerivedObject instance
            #tree.register_module(self.get_module(), self.dir)

        if self.LIBRARY in traits:
            li = self.get_library_info()
            yield li

        if self.PROGRAM in traits:
            # TODO capture programs. Executables and libraries are two sides of
            # the same coin. How should this be captured?
            pass

        # MODULE_NAME is only used for error checking, it appears.
        tracker.add_used_variable('MODULE_NAME')

        # EXPORTS and friends holds information on what files to copy
        # to an output directory.
        if self.EXPORTS in traits:
            exports = data.ExportsInfo(self)
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
        if self.XPIDL in traits:
            idl = data.XPIDLInfo(self)
            idl.add_used_variable('XPIDL_MODULE')
            idl.add_used_variable('MODULE')
            if self.has_own_variable('XPIDL_MODULE'):
                idl.module = self.get_variable_string('XPIDL_MODULE')
            elif self.has_own_variable('MODULE'):
                idl.module = self.get_variable_string('MODULE')
            else:
                raise Exception('XPIDL trait without XPIDL_MODULE or MODULE defined')

            idl.add_used_variable('XPIDLSRCS')
            if self.has_own_variable('XPIDLSRCS'):
                for f in self.get_variable_split('XPIDLSRCS'):
                    idl.sources.add(f)

            # rules.mk merges SDK_XPIDLSRCS together, so we treat as the same
            if self.has_own_variable('SDK_XPIDLSRCS'):
                for f in self.get_variable_split('SDK_XPIDLSRCS'):
                    idl.sources.add(f)

            yield idl

        # Test definitions
        if self.TEST in traits:
            ti = data.TestInfo(self)

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

        # DEFINES is used by JarMaker too. Unfortunately, we can't detect
        # when to do JarMaker from Makefiles (bug 487182 might fix it), so
        # we just pass it along.
        misc.add_used_variable('DEFINES')
        if self.has_own_variable('DEFINES'):
            for define in self.get_variable_split('DEFINES'):
                if define[0:2] == '-D':
                    misc.defines.add(define[2:])
                else:
                    misc.defines.add(define)

        # TODO add an info object for JavaScript-related
        misc.add_used_variable('EXTRA_JS_MODULES')
        if self.has_own_variable('EXTRA_JS_MODULES'):
            for js in self.get_variable_split('EXTRA_JS_MODULES'):
                misc.extra_js_module.add(js)

        misc.add_used_variable('EXTRA_COMPONENTS')
        if self.has_own_variable('EXTRA_COMPONENTS'):
            for c in self.get_variable_split('EXTRA_COMPONENTS'):
                misc.extra_components.add(c)

        misc.add_used_variable('GARBAGE')
        if self.has_own_variable('GARBAGE'):
            for g in self.get_variable_split('GARBAGE'):
                misc.garbage.add(g)

        misc.included_files = self.get_included_files()

        yield tracker
        yield misc

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