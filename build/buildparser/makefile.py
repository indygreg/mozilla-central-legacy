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
import re
import StringIO

class Statement(object):
    '''Holds information about an individual PyMake statement.

    This is a wrapper around classes in pymake.parserdata that provides
    useful features for low-level statement inspection and interaction.'''

    __slots__ = (
        # The actual statement
        'statement',

        # Numeric level statement appears in. 0 is the top level. Conditional
        # blocks increase the numeric level. All statements in the same branch
        # of a conditional occur at the same level.
        'level',

        # Numeric condition index for this condition's branch. For a
        # conditional with many branches, the first branch will be 0,
        # the second 1, etc.
        'condition_index',
    )

    SINGLE_EXPANSION_CLASSES = (
        pymake.parserdata.Command,
        pymake.parserdata.EmptyDirective,
        pymake.parserdata.ExportDirective,
        pymake.parserdata.IfdefCondition,
        pymake.parserdata.Include,
        pymake.parserdata.VPathDirective,
    )

    '''Variables that are automatically available in Makefiles.'''
    AUTOMATIC_VARIABLES = set(['@', '%', '<', '?', '^', '+', '|', '*'])

    def __init__(self, statement, level, condition_index=None):
        self.statement       = statement
        self.level           = level
        self.condition_index = condition_index

    def __str__(self):
        '''Convert this statement back to its Makefile representation.'''

        if self.is_command:
            return self.command_string
        elif self.is_condition:
            return self.condition_string
        elif self.is_empty_directive:
            return self.expansion_string
        elif self.is_export:
            return 'export %s' % self.expansion_string
        elif self.is_include:
            return 'include %s' % self.expansion_string
        elif self.is_rule:
            return ('\n%s%s %s' % (
                Statement.expansion_to_string(self.statement.targetexp),
                self.target_separator,
                Statement.expansion_to_string(self.statement.depexp).lstrip()
            )).rstrip()
        elif self.is_setvariable:
            if self.statement.targetexp is not None:
                return '%s: %s %s %s' % (
                    Statement.expansion_to_string(self.statement.targetexp),
                    self.vname_expansion_string,
                    self.token,
                    self.value
                )
            else:
                return '%s %s %s' % (
                    self.vname_expansion_string, self.token, self.value
                )
        elif self.is_static_pattern_rule:
            return ('\n%s%s %s : %s' % (
                Statement.expansion_to_string(self.statement.targetexp),
                self.target_separator,
                Statement.expansion_to_string(self.statement.patternexp),
                Statement.expansion_to_string(self.statement.depexp)
            )).rstrip()
        elif self.is_vpath:
            return 'vpath %s' % self.expansion_string
        elif self.is_condition_block:
            raise Exception('Cannot convert condition block to string. Did you forget to check .has_str?')
        elif self.is_condition_block_end:
            return 'endif\n'
        elif self.is_ifeq_end or self.is_ifdef_end or self.is_else_end:
            raise Exception('Cannot convert end conditions to strings. Did you forget to check .has_str?')
        else:
            raise Exception('Unhandled statement type: %s' % self.statement)

    def __repr__(self):
        loc = self.location
        indent = ' ' * self.level

        if self.is_semaphore:
            return '<%s%s>' % ( indent, self.statement )
        else:
            s = None
            if self.is_condition:
                s = str(self.statement)
            else:
                fd = StringIO.StringIO()
                self.statement.dump(fd, indent)
                s = fd.getvalue()

            return '<%s>' % s

    @property
    def has_str(self):
        if self.is_condition_block:
            return False

        if self.is_ifdef_end or self.is_else_end or self.is_ifeq_end:
            return False

        return True

    @property
    def is_condition_block(self):
        return isinstance(self.statement, pymake.parserdata.ConditionBlock)

    @property
    def is_condition_block_end(self):
        return self.is_semaphore and self.statement == 'EndConditionBlock'

    @property
    def is_condition(self):
        return isinstance(self.statement, pymake.parserdata.Condition)

    @property
    def is_condition_end(self):
        return self.is_ifdef_end or self.is_else_end or self.is_ifeq_end

    @property
    def is_command(self):
        return isinstance(self.statement, pymake.parserdata.Command)

    @property
    def is_else(self):
        return isinstance(self.statement, pymake.parserdata.ElseCondition)

    @property
    def is_else_end(self):
        return isinstance(self.statement, str) and self.statement == 'EndElseCondition'

    @property
    def is_empty_directive(self):
        return isinstance(self.statement, pymake.parserdata.EmptyDirective)

    @property
    def is_export(self):
        return isinstance(self.statement, pymake.parserdata.ExportDirective)

    @property
    def is_ifdef(self):
        return isinstance(self.statement, pymake.parserdata.IfdefCondition)

    @property
    def is_ifdef_end(self):
        return isinstance(self.statement, str) and self.statement == 'EndDefCondition'

    @property
    def is_ifeq(self):
        return isinstance(self.statement, pymake.parserdata.EqCondition)

    @property
    def is_ifeq_end(self):
        return isinstance(self.statement, str) and self.statement == 'EndEqCondition'

    @property
    def is_include(self):
        return isinstance(self.statement, pymake.parserdata.Include)

    @property
    def is_rule(self):
        return isinstance(self.statement, pymake.parserdata.Rule)

    @property
    def is_setvariable(self):
        return isinstance(self.statement, pymake.parserdata.SetVariable)

    @property
    def is_semaphore(self):
        return isinstance(self.statement, str)

    @property
    def is_static_pattern_rule(self):
        return isinstance(self.statement, pymake.parserdata.StaticPatternRule)

    @property
    def is_vpath(self):
        return isinstance(self.statement, pymake.parserdata.VPathDirective)

    @property
    def command_string(self):
        '''Converts a command expansion back into its string form.

        Commands are interesting beasts. For a couple of reasons.

        For one, they can be multi-line.

        There also might be variable references inside the command.
        To the shell, $foo is correct. However, to Makefiles, we need
        $$foo.

        This all means that conversion back to a string is somewhat
        challenging. But, it isn't impossible.
        '''

        s = Statement.expansion_to_string(self.expansion,
                                          escape_variables=True)

        return '\n'.join(['\t%s' % line for line in s.split('\n')])

    @property
    def condition_string(self):
        '''Convert a condition to a string representation.'''

        assert(self.condition_index is not None)
        prefix = ''
        if (self.is_ifdef or self.is_ifeq) and self.condition_index > 0:
            prefix = 'else '

        if self.is_ifdef:
            s = self.expansion_string

            if self.expected_condition:
                return '%sifdef %s' % ( prefix, s )
            else:
                return '%sifndef %s' % ( prefix, s )

        elif self.is_ifeq:
            s = ','.join([
                Statement.expansion_to_string(self.statement.exp1).strip(),
                Statement.expansion_to_string(self.statement.exp2).strip()
            ])

            if self.expected_condition:
                return '%sifeq (%s)' % ( prefix, s )
            else:
                return '%sifneq (%s)' % ( prefix, s )

        elif self.is_else:
            return 'else'
        else:
            raise Exception('Unhandled condition type: %s' % self.statement)

    @property
    def doublecolon(self):
        '''Returns boolean on whether the rule is a doublecolon rule.'''
        assert(self.is_rule or self.is_static_pattern_rule)

        return self.statement.doublecolon

    @property
    def location(self):
        '''Returns the best pymake.parserdata.Location instance for this
        instance.

        May return None if a suitable location is not available.
        '''
        e = self.first_expansion
        if e is not None:
            return e.loc

        return None

    @property
    def expected_condition(self):
        '''For condition statements, returns the expected condition of the test
        for the branch under the statement to be executed.'''
        assert(isinstance(
            self.statement,
            (pymake.parserdata.IfdefCondition, pymake.parserdata.EqCondition))
        )

        return self.statement.expected

    @property
    def expansion(self):
        '''Returns the single expansion in this statement.

        If the statement has no expansions or multiple expansions, this errors.
        '''
        if isinstance(self.statement, Statement.SINGLE_EXPANSION_CLASSES):
            return self.statement.exp
        else:
            raise Exception('Current statement does not have a single expansion: %s' % self.statement)

    @property
    def expansion_string(self):
        '''Returns the single expansion in this statement formatted to a string.'''

        return Statement.expansion_to_string(self.expansion)

    @property
    def first_expansion(self):
        '''Returns the first expansion in this statement or None if no
        expansions are present.'''

        if isinstance(self.statement, Statement.SINGLE_EXPANSION_CLASSES):
            return self.statement.exp
        elif self.is_setvariable:
            return self.statement.vnameexp
        else:
            return None

    @property
    def target_separator(self):
        '''Returns the colon separator after the target for rules.'''
        if self.doublecolon:
            return '::'
        else:
            return ':'

    @property
    def token(self):
        '''Returns the token for this statement.'''
        assert(isinstance(self.statement, pymake.parserdata.SetVariable))

        return self.statement.token

    @property
    def value(self):
        '''Returns the value of this statement.'''
        assert(isinstance(self.statement, pymake.parserdata.SetVariable))

        return self.statement.value

    @property
    def vname_expansion(self):
        '''Returns the vname expansion for this statement.

        If the statement doesn't have a vname expansion, this raises.
        '''
        if isinstance(self.statement, pymake.parserdata.SetVariable):
            return self.statement.vnameexp
        else:
            raise Exception('Statement does not have a vname expansion: %s' % self.statement)

    @property
    def vname_expansion_string(self):
        '''Returns the vname expansion as a string.'''
        return Statement.expansion_to_string(self.vname_expansion)

    @property
    def vname_expansion_is_string_expansion(self):
        '''Returns whether the vname expansion for this statement is a
        String Expansions.'''

        return isinstance(self.vname_expansion, pymake.data.StringExpansion)

    @staticmethod
    def expansion_to_string(e, error_on_function=False, escape_variables=False):
        '''Convert an expansion to a string.

        This effectively converts a string back to the form it was defined as
        in the Makefile. This is different from the resolvestr() method on
        Expansion classes because it doesn't actually expand variables.

        If error_on_function is True, an Exception will be raised if a
        function is encountered. This provides an easy mechanism to
        conditionally convert expansions only if they contain static data.

        If escape_variables is True, individual variable sigil elements will
        be escaped (i.e. '$' -> '$$').

        TODO consider adding this logic on the appropriate PyMake classes.
        '''
        if isinstance(e, pymake.data.StringExpansion):
            if escape_variables and e.s == '$':
                return '$$'

            return e.s
        elif isinstance(e, pymake.data.Expansion):
            parts = []
            for ex, is_func in e:
                if is_func:
                    if error_on_function:
                        raise Exception('Unable to perform expansion due to function presence')

                    parts.append(Statement.function_to_string(ex))
                else:
                    if escape_variables and ex == '$':
                        parts.append('$$')
                    else:
                        parts.append(ex)

            return ''.join(parts)
        else:
            raise Exception('Unhandled expansion type: %s' % e)

    @staticmethod
    def expansion_to_list(e):
        '''Convert an expansion to a list.

        This is similar to expansion_to_string() except it returns a list.'''
        s = Statement.expansion_to_string(e).strip()

        if s == '':
            return []
        else:
            return s.split(' ')

    @staticmethod
    def function_to_string(ex):
        '''Convert a PyMake function instance to a string.'''
        if isinstance(ex, pymake.functions.AddPrefixFunction):
            return '$(addprefix %s,%s)' % (
                Statement.expansion_to_string(ex._arguments[0]),
                Statement.expansion_to_string(ex._arguments[1])
            )

        elif isinstance(ex, pymake.functions.AddSuffixFunction):
            return '$(addsuffix %s,%s)' % (
                Statement.expansion_to_string(ex._arguments[0]),
                Statement.expansion_to_string(ex._arguments[1])
            )

        elif isinstance(ex, pymake.functions.BasenameFunction):
            return '$(basename %s)' % Statement.expansion_to_string(ex._arguments[0])

        elif isinstance(ex, pymake.functions.CallFunction):
            return '$(call %s)' % ','.join(
                [Statement.expansion_to_string(e) for e in ex._arguments])

        elif isinstance(ex, pymake.functions.DirFunction):
            return '$(dir %s)' % Statement.expansion_to_string(ex._arguments[0])

        elif isinstance(ex, pymake.functions.ErrorFunction):
            return '$(error %s)' % Statement.expansion_to_string(ex._arguments[0])

        elif isinstance(ex, pymake.functions.EvalFunction):
            return '$(eval %s)' % Statement.expansion_to_string(ex._arguments[0])

        elif isinstance(ex, pymake.functions.FilterFunction):
            return '$(filter %s,%s)' % (
                Statement.expansion_to_string(ex._arguments[0]),
                Statement.expansion_to_string(ex._arguments[1])
            )

        elif isinstance(ex, pymake.functions.FilteroutFunction):
            return '$(filter-out %s,%s)' % (
                Statement.expansion_to_string(ex._arguments[0]),
                Statement.expansion_to_string(ex._arguments[1])
            )

        elif isinstance(ex, pymake.functions.FindstringFunction):
            return '$(findstring %s,%s)' % (
                Statement.expansion_to_string(ex._arguments[0]),
                Statement.expansion_to_string(ex._arguments[1])
            )

        elif isinstance(ex, pymake.functions.FirstWordFunction):
            return '$(firstword %s)' % Statement.expansion_to_string(ex._arguments[0])

        elif isinstance(ex, pymake.functions.ForEachFunction):
            return '$(foreach %s,%s,%s)' % (
                Statement.expansion_to_string(ex._arguments[0]),
                Statement.expansion_to_string(ex._arguments[1]),
                Statement.expansion_to_string(ex._arguments[2])
            )

        elif isinstance(ex, pymake.functions.IfFunction):
            return '$(if %s)' % ','.join(
                [Statement.expansion_to_string(e) for e in ex._arguments])

        elif isinstance(ex, pymake.functions.OrFunction):
            return '$(or %s)' % ','.join(
                [Statement.expansion_to_string(e) for e in ex._arguments])

        elif isinstance(ex, pymake.functions.PatSubstFunction):
            return '$(patsubst %s,%s,%s)' % (
                Statement.expansion_to_string(ex._arguments[0]),
                Statement.expansion_to_string(ex._arguments[1]),
                Statement.expansion_to_string(ex._arguments[2])
            )

        elif isinstance(ex, pymake.functions.ShellFunction):
            return '$(shell %s)' % Statement.expansion_to_string(ex._arguments[0])

        elif isinstance(ex, pymake.functions.SortFunction):
            return '$(sort %s)' % Statement.expansion_to_string(ex._arguments[0])

        elif isinstance(ex, pymake.functions.StripFunction):
            return '$(strip %s)' % Statement.expansion_to_string(ex._arguments[0])

        elif isinstance(ex, pymake.functions.SubstitutionRef):
            return '$(%s:%s=%s)' % (
                Statement.expansion_to_string(ex.vname),
                Statement.expansion_to_string(ex.substfrom),
                Statement.expansion_to_string(ex.substto)
            )

        elif isinstance(ex, pymake.functions.SubstFunction):
            return '$(subst %s,%s,%s)' % (
                Statement.expansion_to_string(ex._arguments[0]),
                Statement.expansion_to_string(ex._arguments[1]),
                Statement.expansion_to_string(ex._arguments[2])
            )

        elif isinstance(ex, pymake.functions.WarningFunction):
            return '$(warning %s)' % Statement.expansion_to_string(ex._arguments[0])

        elif isinstance(ex, pymake.functions.WildcardFunction):
            return '$(wildcard %s)' % Statement.expansion_to_string(ex._arguments[0])

        elif isinstance(ex, pymake.functions.VariableRef):
            if isinstance(ex.vname, pymake.data.StringExpansion):
                # AFAICT, there is no way to determine if a variable ref is
                # special and doesn't have parens. So, we need to hard code
                # this manually.
                if ex.vname.s in Statement.AUTOMATIC_VARIABLES:
                    return '$%s' % ex.vname.s

                return '$(%s)' % ex.vname.s
            else:
                return Statement.expansion_to_string(ex.vname)

        else:
            raise Exception('Unhandled function type: %s' % ex)

class StatementCollection(object):
    '''Provides methods for interacting with PyMake's parser output.'''

    __slots__ = (
        # List of tuples describing ifdefs
        '_ifdefs',

        # List of our normalized statements. Each element is a Statement.
        'statements',

        # Dictionary of variable names defined unconditionally. Keys are
        # variable names and values are lists of their SetVariable statements.
        'top_level_variables',
    )

    def __init__(self, filename=None, buf=None):
        '''Construct a set of statements.

        If buf is defined, filename must all be defined. If buf is defined,
        statements will be read from that string. Else, statements will be
        read from the passed filename.
        '''
        self._ifdefs = None

        if buf is not None:
            assert(filename is not None)
            self._load_raw_statements(pymake.parser.parsestring(buf, filename))
        elif filename:
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
            for s in self.statements:
                if not s.is_ifdef:
                    continue

                self._ifdefs.append((
                    s.expansion_string,
                    s.expected_condition,
                    s.level > 0,
                    s.location
                ))

        return self._ifdefs

    @property
    def includes(self):
        '''Returns information about file includes.

        Each returned item is a tuple of
          ( path, is_conditional, location )
        '''
        for s in self.statements:
            if s.is_include:
                yield (
                    s.expansion_string,
                    s.level > 0,
                    s.location
                )

    @property
    def variable_assignments(self):
        '''Returns information about variable assignments.

        Each returned item is a tuple of:
          ( name, value, token, is_conditional, location )
        '''

        # This is a workaround because filtering doesn't currently munge the
        # statement level.
        condition_count = 0

        for s in self.statements:
            if s.is_condition_block:
                condition_count += 1
            elif s.is_condition_block_end:
                condition_count -= 1

            if not s.is_setvariable:
                continue

            assert(s.vname_expansion_is_string_expansion)

            yield (
                s.vname_expansion_string,
                s.value,
                s.token,
                condition_count > 0,
                s.location
            )

    @property
    def unconditional_variable_assignments(self):
        '''Like variable_assignments but for variables being assigned
        unconditionally (e.g. outside ifdef, ifeq, etc).

        Returned items are tuples of:
          ( name, value, token, location )
        '''

        for name, value, token, conditional, location in self.variable_assignments:
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

    @property
    def lines(self):
        '''Emit lines that constitute a Makefile for this collection.'''
        for statement in self.statements:
            if statement.has_str:
                yield str(statement)

    def include_includes(self):
        '''Follow file includes and insert remote statements into this
        collection.

        For every Include statement in the original list, an IncludeBegin
        semaphore statement will be inserted immediately before. All
        statements from that include file will be inserted after it. After
        all the statements are added, a IncludeEnd semaphore statement will
        be inserted. All statements will appear on the same level.
        '''
        statements = []

        for t in self.statements:
            s = t[0]
            if not isinstance(s, pymake.parserdata.Include):
                statements.append(t)
                continue

            statements.append(('IncludeBegin', t[1]))
            statements.append(t)
            raise Exception('TODO implement')
            statements.append(('IncludeEnd', t[1]))

        self.statements = statements
        self.clear_caches()

    def strip_false_conditionals(self):
        '''Rewrite the raw statement list with raw conditionals filtered out.'''
        statements = []
        currently_defined = set()
        filter_level = None

        # Tuple of (statement_tuple, evaluated, first_branch_taken)
        condition_block_stack = []

        # Conditionals are expanded immediately, during the first pass, so it
        # is safe to linearly traverse and prune as we go.
        for s in self.statements:
            if filter_level is not None:
                if s.level > filter_level:
                    continue
                else:
                    filter_level = None

            if s.is_condition_block:
                condition_block_stack.append([s, False, False])
                continue

            if s.is_ifdef:
                name = s.expansion_string
                defined = name in currently_defined

                # We were able to evaluate the conditional
                condition_block_stack[-1][1] = True

                if (defined and not s.expected_condition) or (not defined and s.expected_condition):
                    filter_level = s.level
                    continue

                # Mark the primary branch as being taken
                condition_block_stack[-1][2] = True

            elif s.is_else:
                top_condition = condition_block_stack[-1]

                # If we were able to evaluate the condition and we took the
                # first branch, filter the else branch.
                if top_condition[1] and top_condition[2]:
                    filter_level = s.level
                    continue

                # If we were able to evaluate, but we didn't take the first
                # branch, that leaves us as the sole branch. Remove the
                # else statement.
                if top_condition[1]:
                    continue

            elif s.is_include:
                # The error on function is an arbitrary restriction. We could
                # possibly work around it, but that would be harder since
                # functions possibly require more context to operate on than
                # the simple parser data.
                filename = Statement.expansion_to_string(s.expansion, error_on_function=True)

                included = StatementCollection(filename)
                included.include_includes()
                included.strip_false_conditionals() # why not?

                raise Exception('TODO')

            elif s.is_setvariable:
                # At the worst, we are in a conditional that we couldn't
                # evaluate, so there is no harm in marking as defined even if
                # it might not be. make will do the right thing at run-time.
                if len(s.value) > 0:
                    currently_defined.add(s.vname_expansion_string)

            elif s.is_condition_end:
                # If we evaluated the condition block, we have an active branch
                # and can remove this semaphore.
                if condition_block_stack[-1][1]:
                    continue

            elif s.is_condition_block_end:
                # If we evaluated the condition, we can remove this
                # semaphore statement.
                popped = condition_block_stack.pop()
                if popped[1]:
                    continue

            statements.append(s)

        self.clear_caches()
        self.statements = statements

    def clear_caches(self):
        '''During normal operation, this object caches some data. This clears
        those caches.'''
        self._ifdefs = None

    def _load_raw_statements(self, statements):
        '''Loads PyMake's parser output into this container.'''

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
                    yield Statement(statement, level=level)

                    index = 0
                    for condition, l in statement:
                        yield Statement(condition, level + 1, condition_index=index)

                        # Recursively add these conditional statements at the
                        # next level.
                        for s in examine(l, level + 2):
                            yield s

                        name = None
                        if isinstance(condition, pymake.parserdata.IfdefCondition):
                            name = 'EndDefCondition'
                        elif isinstance(condition, pymake.parserdata.EqCondition):
                            name = 'EndEqCondition'
                        elif isinstance(condition, pymake.parserdata.ElseCondition):
                            name = 'EndElseCondition'
                        else:
                            raise Exception('Unhandled condition type: %s' % condition)

                        yield Statement(name, level + 1, condition_index=index)
                        index += 1

                    yield Statement('EndConditionBlock', level)
                else:
                    yield Statement(statement, level)

        self.statements = [s for s in examine(statements, 0)]

class Makefile(object):
    '''A high-level API for a Makefile.

    This provides a convenient bridge between StatementCollection,
    pymake.data.Makefile, and raw file operations.

    From an API standpoint, interaction between the 3 is a bit fuzzy. Read
    the docs for caveats.
    '''
    __slots__ = (
        'filename',      # Filename of the Makefile
        'dir',           # Directory holding the Makefile
        '_makefile',      # PyMake Makefile instance
        '_statements',   # StatementCollection for this file.
        '_lines',        # List of lines containing (modified) Makefile lines
    )

    RE_SUB = re.compile(r"@([a-z0-9_]+?)@")

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
        self._makefile   = None
        self._statements = None
        self._lines      = None

    @property
    def statements(self):
        '''Obtain the StatementCollection for this Makefile.'''
        if self._statements is None:
            buf = None
            if self._lines is not None:
                buf = ''.join(self._lines)

            self._statements = StatementCollection(filename=self.filename, buf=buf)

        return self._statements

    @property
    def makefile(self):
        if self._makefile is None:
            if self._lines is not None:
                raise Exception('Cannot load Makefile from modified content at this time')

            self._makefile = pymake.data.Makefile(workdir=self.dir)
            self._makefile.include(self.filename)
            self._makefile.finishparsing()

        return self._makefile

    @property
    def lines(self):
        '''Returns a list of lines making up this file.'''

        if self._statements:
            for line in self._statements.lines:
                yield line
        elif self._lines is not None:
            for line in self._lines:
                yield line.rstrip('\n')
        else:
            # TODO this could come from file, no?
            raise('No source of lines available')

    def perform_substitutions(self, mapping, raise_on_missing=False,
                              error_on_missing=False, callback_on_missing=None):
        '''Performs variable substitutions on the Makefile.

        A dictionary of variables is passed. Each "@key@" in the source
        Makefile will be substituted for the literal value in the dictionary.

        This will invalidate any cached objects. However, consumers could
        still have a reference to an old one. So, if this method is called,
        it should be done before any other method is consumed.

        Invalidation of the cached objects also means that changes to the
        StatementCollection will be lost.

        The caller has a few choices when it comes to behavior for source
        variables missing from the translation map. The default behavior is
        to insert the empty string (''). If raise_on_missing is True, an
        exception will be thrown. If error_on_missing is True, an $(error)
        will be inserted.
        '''

        lines = []

        with open(self.filename, 'rb') as fh:
            for line in fh:
                # Handle simple case of no substitution first
                if line.count('@') < 2:
                    lines.append(line)
                    continue

                # Now we perform variable replacement on the line.
                newline = line
                for match in self.RE_SUB.finditer(line):
                    variable = match.group(1)
                    value = mapping.get(variable, None)

                    if value is None:
                        if raise_on_missing:
                            raise Exception('Missing variable from translation map: %s' % variable)

                        if callback_on_missing is not None:
                            callback_on_missing(variable)

                        if error_on_missing:
                            value = '$(error Missing source variable: %s)' % variable
                        else:
                            value = ''
                    newline = newline.replace(match.group(0), value)

                lines.append(newline)

        self._makefile   = None
        self._statements = None
        self._lines      = lines

    def variable_defined(self, name, search_includes=False):
        '''Returns whether a variable is defined in the Makefile.

        By default, it only looks for variables defined in the current
        file, not in included files.'''
        if search_includes:
            v = self.makefile.variables.get(name, True)[2]
            return v is not None
        else:
            return name in self.statements.defined_variables

    def get_variable_string(self, name, resolve=True):
        '''Obtain a named variable as a string.

        If resolve is True, the variable's value will be resolved. If not,
        the Makefile syntax of the expansion is returned. In either case,
        if the variable is not defined, None is returned.
        '''
        if resolve:
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
        v = self.makefile.variables.get(name, True)[2]
        if v is None:
            return []

        return v.resolvesplit(self.makefile, self.makefile.variables)

    def get_own_variable_names(self, include_conditionals=True):
        '''Returns a set of variable names defined by the Makefile itself.

        include_conditionals can be used to filter out variables defined inside
        a conditional (e.g. #ifdef). By default, all variables are returned,
        even the ones inside conditionals that may not be evaluated.
        '''
        names = set()

        for ( name, value, token, is_conditional, location ) in self.statements.variable_assignments:
            if is_conditional and not include_conditionals:
                continue

            names.add(name)

        return names

    def has_own_variable(self, name, include_conditionals=True):
        '''Returns whether the specified variable is defined in the Makefile
        itself (as opposed to being defined in an included file.'''
        return name in self.get_own_variable_names(include_conditionals)

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

        misc.included_files = [t[0] for t in self.statements.includes]

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