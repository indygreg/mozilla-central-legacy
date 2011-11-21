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

'''This file contains classes for interacting with Makefiles. A lot of the
functionality could probably be baked into PyMake directly.'''

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
            return self.setvariable_string
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
    def setvariable_string(self):
        '''Converts a SetVariable statement to a string.

        SetVariable statements are a little funky. In the common case, they
        have the form "foo = bar". If they have a target expression, there
        is the form "targ: foo = bar". And, for multi-line variables, you
        use the define directive. It ia all pretty funky.
        '''

        assert(self.is_setvariable)

        value = self.value

        if self.statement.targetexp is not None:
            return '%s: %s %s %s' % (
                    Statement.expansion_to_string(self.statement.targetexp),
                    self.vname_expansion_string,
                    self.token,
                    value
                )

        # Now we have the common case. But, it could be multiline.
        multiline = value.count('\n') > 0

        if multiline:
            # According to 6.8 of the Make manual, the equals is optional.
            return 'define %s\n%s\nendef\n' % (
                self.vname_expansion_string, value
            )
        else:
            return ('%s %s %s' % (
                    self.vname_expansion_string, self.token, value
                )).rstrip()

    @property
    def value(self):
        '''Returns the value of this statement.'''
        assert(isinstance(self.statement, pymake.parserdata.SetVariable))

        return self.statement.value

    @property
    def value_expansion(self):
        '''Returns the value of this SetVariable statement as an expansion.

        By default, variable values are stored as strings. They can be
        upgraded to expansions upon request.'''
        assert(isinstance(self.statement, pymake.parserdata.SetVariable))

        data = pymake.parser.Data.fromstring(self.statement.value, self.statement.valueloc)
        return pymake.parser.parsemakesyntax(data, 0, (), pymake.parser.iterdata)[0]

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
    def expansion_is_string(e):
        '''Returns whether the expansion consists of only string data.'''

        if isinstance(e, pymake.data.StringExpansion):
            return True
        elif isinstance(e, pymake.data.Expansion):
            for ex, is_func in e:
                if is_func:
                    return False

                assert(isinstance(ex, str))

            return True
        else:
            raise Exception('Unhandled expansion type: %s' % e)

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
                        raise Exception('Unable to perform expansion due to function presence: %s' % ex)

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
                Statement.expansion_to_string(ex[0]),
                Statement.expansion_to_string(ex[1])
            )

        elif isinstance(ex, pymake.functions.AddSuffixFunction):
            return '$(addsuffix %s,%s)' % (
                Statement.expansion_to_string(ex[0]),
                Statement.expansion_to_string(ex[1])
            )

        elif isinstance(ex, pymake.functions.BasenameFunction):
            return '$(basename %s)' % Statement.expansion_to_string(ex[0])

        elif isinstance(ex, pymake.functions.CallFunction):
            return '$(call %s)' % ','.join(
                [Statement.expansion_to_string(e) for e in ex])

        elif isinstance(ex, pymake.functions.DirFunction):
            return '$(dir %s)' % Statement.expansion_to_string(ex[0])

        elif isinstance(ex, pymake.functions.ErrorFunction):
            return '$(error %s)' % Statement.expansion_to_string(ex[0])

        elif isinstance(ex, pymake.functions.EvalFunction):
            return '$(eval %s)' % Statement.expansion_to_string(ex[0])

        elif isinstance(ex, pymake.functions.FilterFunction):
            return '$(filter %s,%s)' % (
                Statement.expansion_to_string(ex[0]),
                Statement.expansion_to_string(ex[1])
            )

        elif isinstance(ex, pymake.functions.FilteroutFunction):
            return '$(filter-out %s,%s)' % (
                Statement.expansion_to_string(ex[0]),
                Statement.expansion_to_string(ex[1])
            )

        elif isinstance(ex, pymake.functions.FindstringFunction):
            return '$(findstring %s,%s)' % (
                Statement.expansion_to_string(ex[0]),
                Statement.expansion_to_string(ex[1])
            )

        elif isinstance(ex, pymake.functions.FirstWordFunction):
            return '$(firstword %s)' % Statement.expansion_to_string(ex[0])

        elif isinstance(ex, pymake.functions.ForEachFunction):
            return '$(foreach %s,%s,%s)' % (
                Statement.expansion_to_string(ex[0]),
                Statement.expansion_to_string(ex[1]),
                Statement.expansion_to_string(ex[2])
            )

        elif isinstance(ex, pymake.functions.IfFunction):
            return '$(if %s)' % ','.join(
                [Statement.expansion_to_string(e) for e in ex])

        elif isinstance(ex, pymake.functions.NotDirFunction):
            return '$(notdir %s)' % Statement.expansion_to_string(ex[0])

        elif isinstance(ex, pymake.functions.OrFunction):
            return '$(or %s)' % ','.join(
                [Statement.expansion_to_string(e) for e in ex])

        elif isinstance(ex, pymake.functions.PatSubstFunction):
            return '$(patsubst %s,%s,%s)' % (
                Statement.expansion_to_string(ex[0]),
                Statement.expansion_to_string(ex[1]),
                Statement.expansion_to_string(ex[2])
            )

        elif isinstance(ex, pymake.functions.ShellFunction):
            return '$(shell %s)' % Statement.expansion_to_string(ex[0])

        elif isinstance(ex, pymake.functions.SortFunction):
            return '$(sort %s)' % Statement.expansion_to_string(ex[0])

        elif isinstance(ex, pymake.functions.StripFunction):
            return '$(strip %s)' % Statement.expansion_to_string(ex[0])

        elif isinstance(ex, pymake.functions.SubstitutionRef):
            return '$(%s:%s=%s)' % (
                Statement.expansion_to_string(ex.vname),
                Statement.expansion_to_string(ex.substfrom),
                Statement.expansion_to_string(ex.substto)
            )

        elif isinstance(ex, pymake.functions.SubstFunction):
            return '$(subst %s,%s,%s)' % (
                Statement.expansion_to_string(ex[0]),
                Statement.expansion_to_string(ex[1]),
                Statement.expansion_to_string(ex[2])
            )

        elif isinstance(ex, pymake.functions.WarningFunction):
            return '$(warning %s)' % Statement.expansion_to_string(ex[0])

        elif isinstance(ex, pymake.functions.WildcardFunction):
            return '$(wildcard %s)' % Statement.expansion_to_string(ex[0])

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

        # List of (statement_tuple, evaluated, branch_taken)
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
