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

class Expansion(object):
    '''Represents an individual Makefile/PyMake expansion.

    An expansion is a parsed representation of Makefile text. It contains
    pointers to string literals, functions, other variables, etc.
    '''

    # Classes in this set are for functions which are deterministic. i.e.
    # for a given set of input arguments, the output will always be the same
    # regardless of the state of the computer, the filesystem, etc. This list
    # is used for static analysis and false condition elimination.
    DETERMINISTIC_FUNCTION_CLASSES = (
        pymake.functions.SubstFunction,
        pymake.functions.PatSubstFunction,
        pymake.functions.StripFunction,
        pymake.functions.FindstringFunction,
        pymake.functions.FilterFunction,
        pymake.functions.FilteroutFunction,
        pymake.functions.SortFunction,
        pymake.functions.WordFunction,
        pymake.functions.WordlistFunction,
        pymake.functions.WordsFunction,
        pymake.functions.FirstWordFunction,
        pymake.functions.LastWordFunction,
        pymake.functions.DirFunction,
        pymake.functions.NotDirFunction,
        pymake.functions.SuffixFunction,
        pymake.functions.BasenameFunction,
        pymake.functions.AddSuffixFunction,
        pymake.functions.AddPrefixFunction,
        pymake.functions.JoinFunction,
        pymake.functions.IfFunction,
        pymake.functions.OrFunction,
        pymake.functions.AndFunction,
        pymake.functions.ForEachFunction,
        pymake.functions.ErrorFunction,
        pymake.functions.WarningFunction,
        pymake.functions.InfoFunction,
    )

    # Classes in this set rely on the filesystem and thus may not be
    # idempotent.
    FILESYSTEM_FUNCTION_CLASSES = (
        pymake.functions.WildcardFunction,
        pymake.functions.RealpathFunction,
        pymake.functions.AbspathFunction
    )

    NONDETERMINISTIC_FUNCTION_CLASSES = (
        # This /might/ be safe depending on the circumstances, but it would be
        # too difficult to implement.
        pymake.functions.CallFunction,

        # This is a weird one because the value inside might be non-idempotent.
        # We could probably support it, but it would require work.
        pymake.functions.ValueFunction,

        # This transforms the Makefile. We aren't willing to support this for
        # static analysis yet.
        pymake.functions.EvalFunction,

        # Run-time deterministic.
        pymake.functions.OriginFunction,

        # Variables could come from environment. Therefore it is a run-time
        # deterministic.
        pymake.functions.FlavorFunction,

        # For obvious reasons.
        pymake.functions.ShellFunction,

        # variable references aren't always deterministic because the variable
        # behind it might not be deterministic.
        pymake.functions.VariableRef,
        pymake.functions.SubstitutionRef,
    )

    __slots__ = (
        # Holds the low-level expansion
        'expansion',
    )

    def __init__(self, expansion=None, s=None, location=None):
        '''Initialize from an existing PyMake expansion or text'''

        if expansion and s:
            raise Exception('Both expansion and string value must not be defined.')

        if expansion is not None:
            assert(isinstance(expansion,
                   (pymake.data.Expansion, pymake.data.StringExpansion)))
            self.expansion = expansion
        elif s is not None:
            assert(location is not None)

            data = pymake.parser.Data.fromstring(s, location)
            self.expansion = pymake.parser.parsemakesyntax(
                data, 0, (), pymake.parser.iterdata)[0]
        else:
            raise Exception('One of expansion or s must be passed')

    def __str__(self):
        return Expansion.to_str(self.expansion)

    def is_deterministic(self, variables=None, missing_is_deterministic=True):
        '''Returns whether the expansion is determinstic.

        A deterministic expansion is one whose value is always guaranteed.
        If variables are not provided, a deterministic expansion is one that
        consists of only string data or transformations on strings. If any
        variables are encounted, the expansion will be non-deterministic by
        the nature of Makefiles, since they variables could come from the
        execution environment or command line arguments. But, we assume
        the current state as defined by the arguments is what will occur
        during real execution. If you wish to override this, set the
        appropriate arguments.
        '''

        # The simple case is a single string
        if isinstance(self.expansion, pymake.data.StringExpansion):
            return True

        assert(isinstance(self.expansion, pymake.data.Expansion))

        for e, is_func in self.expansion:
            # A simple string is always deterministic.
            if not is_func:
                continue

            if isinstance(e, Expansion.DETERMINISTIC_FUNCTION_CLASSES):
                for i in range(0, len(e)):
                    child = Expansion(expansion=e[i])
                    if not child.is_deterministic(variables=variables):
                        return False

                # If we got here, all child expansions were evaluated and we
                # are deterministic.
                continue

            # We don't have a deterministic function. So, we perform deeper
            # inspection on some of these.

            if isinstance(e, pymake.functions.VariableRef) and variables is not None:
                if isinstance(e.vname, pymake.data.StringExpansion):
                    name = e.vname.s

                    flavor, source, value = variables.get(name, expand=True)

                    # The variable wasn't defined.
                    if flavor is None:
                        if missing_is_deterministic:
                            continue
                        else:
                            return False

                    # We found a variable! If it is simple, that means it
                    # depends on nothing else. And, the variable should be
                    # captured by the current context, so we can assume it is
                    # deterministic.
                    if flavor == pymake.data.Variables.FLAVOR_SIMPLE:
                        continue

                    # Else, we evaluate the expansion on its own.
                    v_exp = Expansion(expansion=value)
                    if not v_exp.is_deterministic(variables=variables,
                            missing_is_deterministic=missing_is_deterministic):
                        return False

                    continue

                # We don't bother with more complicated expansions.
                else:
                    return False


            return False

        return True

    @staticmethod
    def to_str(e, error_on_function=False, escape_variables=False):
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
            if escape_variables:
                return e.s.replace('$', '$$')

            return e.s
        elif isinstance(e, pymake.data.Expansion):
            parts = []
            for ex, is_func in e:
                if is_func:
                    if error_on_function:
                        raise Exception('Unable to perform expansion due to function presence: %s' % ex)

                    parts.append(Expansion.function_to_string(ex))
                else:
                    if escape_variables:
                        parts.append(ex.replace('$','$$'))
                    else:
                        parts.append(ex)

            return ''.join(parts)
        else:
            raise Exception('Unhandled expansion type: %s' % e)

    @staticmethod
    def to_list(e):
        '''Convert an expansion to a list.

        This is similar to expansion_to_string() except it returns a list.'''
        s = Expansion.to_str(e).strip()

        if s == '':
            return []
        else:
            return s.split(' ')

    @staticmethod
    def is_static_string(e):
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
    def function_to_string(ex):
        '''Convert a PyMake function instance to a string.'''
        if isinstance(ex, pymake.functions.AddPrefixFunction):
            return '$(addprefix %s,%s)' % (
                Expansion.to_str(ex[0]),
                Expansion.to_str(ex[1])
            )

        elif isinstance(ex, pymake.functions.AddSuffixFunction):
            return '$(addsuffix %s,%s)' % (
                Expansion.to_str(ex[0]),
                Expansion.to_str(ex[1])
            )

        elif isinstance(ex, pymake.functions.BasenameFunction):
            return '$(basename %s)' % Expansion.to_str(ex[0])

        elif isinstance(ex, pymake.functions.CallFunction):
            return '$(call %s)' % ','.join(
                [Expansion.to_str(e) for e in ex])

        elif isinstance(ex, pymake.functions.DirFunction):
            return '$(dir %s)' % Expansion.to_str(ex[0])

        elif isinstance(ex, pymake.functions.ErrorFunction):
            return '$(error %s)' % Expansion.to_str(ex[0])

        elif isinstance(ex, pymake.functions.EvalFunction):
            return '$(eval %s)' % Expansion.to_str(ex[0])

        elif isinstance(ex, pymake.functions.FilterFunction):
            return '$(filter %s,%s)' % (
                Expansion.to_str(ex[0]),
                Expansion.to_str(ex[1])
            )

        elif isinstance(ex, pymake.functions.FilteroutFunction):
            return '$(filter-out %s,%s)' % (
                Expansion.to_str(ex[0]),
                Expansion.to_str(ex[1])
            )

        elif isinstance(ex, pymake.functions.FindstringFunction):
            return '$(findstring %s,%s)' % (
                Expansion.to_str(ex[0]),
                Expansion.to_str(ex[1])
            )

        elif isinstance(ex, pymake.functions.FirstWordFunction):
            return '$(firstword %s)' % Expansion.to_str(ex[0])

        elif isinstance(ex, pymake.functions.ForEachFunction):
            return '$(foreach %s,%s,%s)' % (
                Expansion.to_str(ex[0]),
                Expansion.to_str(ex[1]),
                Expansion.to_str(ex[2])
            )

        elif isinstance(ex, pymake.functions.IfFunction):
            return '$(if %s)' % ','.join(
                [Expansion.to_str(e) for e in ex])

        elif isinstance(ex, pymake.functions.NotDirFunction):
            return '$(notdir %s)' % Expansion.to_str(ex[0])

        elif isinstance(ex, pymake.functions.OrFunction):
            return '$(or %s)' % ','.join(
                [Expansion.to_str(e) for e in ex])

        elif isinstance(ex, pymake.functions.PatSubstFunction):
            return '$(patsubst %s,%s,%s)' % (
                Expansion.to_str(ex[0]),
                Expansion.to_str(ex[1]),
                Expansion.to_str(ex[2])
            )

        elif isinstance(ex, pymake.functions.ShellFunction):
            return '$(shell %s)' % Expansion.to_str(ex[0])

        elif isinstance(ex, pymake.functions.SortFunction):
            return '$(sort %s)' % Expansion.to_str(ex[0])

        elif isinstance(ex, pymake.functions.StripFunction):
            return '$(strip %s)' % Expansion.to_str(ex[0])

        elif isinstance(ex, pymake.functions.SubstitutionRef):
            return '$(%s:%s=%s)' % (
                Expansion.to_str(ex.vname),
                Expansion.to_str(ex.substfrom),
                Expansion.to_str(ex.substto)
            )

        elif isinstance(ex, pymake.functions.SubstFunction):
            return '$(subst %s,%s,%s)' % (
                Expansion.to_str(ex[0]),
                Expansion.to_str(ex[1]),
                Expansion.to_str(ex[2])
            )

        elif isinstance(ex, pymake.functions.WarningFunction):
            return '$(warning %s)' % Expansion.to_str(ex[0])

        elif isinstance(ex, pymake.functions.WildcardFunction):
            return '$(wildcard %s)' % Expansion.to_str(ex[0])

        elif isinstance(ex, pymake.functions.VariableRef):
            if isinstance(ex.vname, pymake.data.StringExpansion):
                # AFAICT, there is no way to determine if a variable ref is
                # special and doesn't have parens. So, we need to hard code
                # this manually.
                if ex.vname.s in Statement.AUTOMATIC_VARIABLES:
                    return '$%s' % ex.vname.s

                return '$(%s)' % ex.vname.s
            else:
                return Expansion.to_str(ex.vname)

        else:
            raise Exception('Unhandled function type: %s' % ex)


class Statement(object):
    '''Holds information about an individual PyMake statement.

    This is a wrapper around classes in pymake.parserdata that provides
    useful features for low-level statement inspection and interaction.'''

    __slots__ = (
        # The actual statement
        'statement',
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

    def __init__(self, statement):
        self.statement = statement

    def __eq__(self, other):
        '''Determines if this statement is equivalent to another.

        We define equivalence to mean the composition of the statement is
        equivalent. We do not test things like locations or the expanded value
        of variables, etc.

        Practically speaking, if two statement appears on consecutive lines
        and the first does not have any side-effects, then the two statements
        are equivalent.
        '''
        if not isinstance(other, Statement):
            return False

        if type(self.statement) != type(other.statement):
            return False

        # TODO this implementation is not complete
        our_expansions = self.expansions
        other_expansions = other.expansions

        if len(our_expansions) != len(other_expansions):
            return False

        for i in range(0, len(our_expansions)):
            if our_expansions[i] != other_expansions[i]:
                return False

        return True

    def __str__(self):
        '''Convert this statement back to its Makefile representation.'''

        if self.is_command:
            return self.command_string
        elif self.is_condition:
            return self.condition_str()
        elif self.is_empty_directive:
            return self.expansion_string
        elif self.is_export:
            return 'export %s' % self.expansion_string
        elif self.is_include:
            return 'include %s' % self.expansion_string
        elif self.is_rule:
            return ('\n%s%s %s' % (
                Expansion.to_str(self.statement.targetexp),
                self.target_separator,
                Expansion.to_str(self.statement.depexp).lstrip()
            )).rstrip()
        elif self.is_setvariable:
            return self.setvariable_string
        elif self.is_static_pattern_rule:
            return ('\n%s%s %s: %s' % (
                Expansion.to_str(self.statement.targetexp),
                self.target_separator,
                Expansion.to_str(self.statement.patternexp).strip(),
                Expansion.to_str(self.statement.depexp).strip()
            )).rstrip()
        elif self.is_vpath:
            return 'vpath %s' % self.expansion_string
        else:
            raise Exception('Unhandled statement type: %s' % self.statement)

    def __repr__(self):
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
    def is_condition(self):
        return isinstance(self.statement, pymake.parserdata.Condition)

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
    def is_ifeq(self):
        return isinstance(self.statement, pymake.parserdata.EqCondition)

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

        s = Expansion.to_str(self.expansion,
                             escape_variables=True)

        return '\n'.join(['\t%s' % line for line in s.split('\n')])

    @property
    def condition_is_deterministic(self):
        '''Returns whether the condition can be evaluated deterministically.

        For a condition to be fully deterministic, it must be composed of
        expansions that are deterministic. For an expansion to be
        deterministic, it can't rely on the run-time environment, only
        preconfigured defaults.'''
        pass

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

        return Expansion.to_str(self.expansion)

    @property
    def expansions(self):
        '''Returns an iterator over all expansions in this statement.'''

        if isinstance(self.statement, Statement.SINGLE_EXPANSION_CLASSES):
            yield Expansion(expansion=self.statement.exp)
        elif self.is_ifeq:
            yield Expansion(expansion=self.statement.exp1)
            yield Expansion(expansion=self.statement.exp2)
        elif self.is_rule:
            yield Expansion(expansion=self.statement.targetexp)
            yield Expansion(expansion=self.statement.depexp)
        elif self.is_static_pattern_rule:
            yield Expansion(expansion=self.statement.targetexp)
            yield Expansion(expansion=self.statement.patternexp)
            yield Expansion(expansion=self.statement.depexp)
        elif self.is_setvariable:
            if self.statement.targetexp is not None:
                yield Expansion(expansion=self.statement.targetexp)

            yield Expansion(expansion=self.statement.vnameexp)
            yield Expansion(s=self.statement.value, location=self.statement.valueloc)
        else:
            raise Exception('Unhandled statement type: %s' % self)

    @property
    def first_expansion(self):
        '''Returns the first expansion in this statement or None if no
        expansions are present.'''

        if isinstance(self.statement, Statement.SINGLE_EXPANSION_CLASSES):
            return self.statement.exp
        elif self.is_setvariable:
            return self.statement.vnameexp
        elif self.is_rule:
            return self.statement.targetexp
        elif self.is_static_pattern_rule:
            return self.statement.targetexp
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

        value = self.value.replace('#', '\\#')

        if self.statement.targetexp is not None:
            return '%s: %s %s %s' % (
                    Expansion.to_str(self.statement.targetexp),
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
        return Expansion(expansion=pymake.parser.parsemakesyntax(data, 0, (),
                         pymake.parser.iterdata)[0])

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
        return Expansion.to_str(self.vname_expansion)

    @property
    def vname_expansion_is_string_expansion(self):
        '''Returns whether the vname expansion for this statement is a
        String Expansions.'''

        return isinstance(self.vname_expansion, pymake.data.StringExpansion)

    def are_expansions_deterministic(self, variables=None):
        '''Determines whether the expansions in this statement are
        deterministic.'''

        # TODO figure out what to do about target expansions. Resolving
        # these expansions results in access to Makefile.gettarget()
        if self.is_setvariable and self.statement.targetexp is not None:
            return False

        for e in self.expansions:
            if not e.is_deterministic(variables=variables):
                return False

        return True

class ConditionBlock(object):
    '''Represents a condition block statement.

    The condition block is a collection of conditions and statements inside
    those conditions. The structure mimics that of
    pymake.parserdata.ConditionBlock. However, we provide some higher-level
    APIs.'''

    __slots__ = (
        # Array of tuples of ( condition statement, [ statements ] )
        'conditions',

        # Underlying pymake.parserdata.ConditionBlock statement
        'statement',
    )

    def __init__(self, statement):
        assert(isinstance(statement, pymake.parserdata.ConditionBlock))

        self.statement = statement
        self.conditions = []

        for condition, statements in statement:
            self.conditions.append(
                (Statement(condition), [Statement(s) for s in statements])
            )

    def __str__(self):
        '''Convert the condition block back to its Makefile representation.'''
        return '\n'.join(self.lines())

    def __iter__(self):
        return iter(self.conditions)

    def __len__(self):
        return len(self.conditions)

    def __getitem__(self, i):
        return self.conditions[i]

    def lines(self):
        '''Returns an iterable of str representing the Makefile of lines
        composing this condition block.'''
        i = 0
        for condition, statements in self:
            yield ConditionBlock.condition_str(condition, index)

            for statement in statements:
                yield str(statement)

        yield 'endif'

    @staticmethod
    def condition_str(statement, index=None):
        '''Convert a condition to a string representation.

        The index argument defines the index of this condition inside a
        condition block. If the index is greater than 0, an else will be
        added to the representation.
        '''

        prefix = ''
        if (statement.is_ifdef or statement.is_ifeq) and index > 0:
            prefix = 'else '

        if statement.is_ifdef:
            s = statement.expansion_string

            if statement.expected_condition:
                return '%sifdef %s' % ( prefix, s )
            else:
                return '%sifndef %s' % ( prefix, s )

        elif statement.is_ifeq:
            s = ','.join([
                Expansion.to_str(statement.statement.exp1).strip(),
                Expansion.to_str(statement.statement.exp2).strip()
            ])

            if statement.expected_condition:
                return '%sifeq (%s)' % ( prefix, s )
            else:
                return '%sifneq (%s)' % ( prefix, s )

        elif statement.is_else:
            return 'else'
        else:
            raise Exception('Unhandled condition type: %s' % statement.statement)

    def evaluation_is_deterministic(self, variables=None,
                                    missing_is_deterministic=True):
        '''Returns whether evaluation of this condition block is determinstic.

        Evaluation is considered deterministic if all conditions are
        deterministic. Note that an else condition is always determinstic, so
        for simple ifeq..else..end, if the ifeq is determinstic, the whole
        thing is deterministic.
        '''
        pass

class StatementCollection(object):
    '''Provides methods for interacting with PyMake's parser output.'''

    __slots__ = (
         # String filename we loaded from. A filename must be associated with
         # a Makefile for things to work properly.
        'filename',

        # Directory the Makefile runs in. By default, this is set to the
        # directory of the filename. However, it is completely valid for
        # instantiators to override this with something else. A use case would
        # be if the contents are being read from one location but should
        # appear as if it is loaded from elsewhere.
        'directory',

        # List of tuples describing ifdefs
        '_ifdefs',

        # List of our normalized statements. Each element is a Statement or
        # ConditionBlock.
        'statements',

        # Dictionary of variable names defined unconditionally. Keys are
        # variable names and values are lists of their SetVariable statements.
        'top_level_variables',
    )

    def __init__(self, filename=None, buf=None, directory=None):
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

        self.filename  = filename

        if directory is not None:
            self.directory = directory
        else:
            self.directory = os.path.dirname(filename)

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

    def strip_false_conditionals(self):
        '''Rewrite the raw statement list with false conditional branches
        filtered out.

        This is very dangerous and is prone to breakage if not used properly.
        The underlying problem is conditionals in Makefiles are very
        non-deterministic. Even if you are simply testing ifdef, that
        variable could be provided as an environment variable or command
        line argument. So, not even these could get eliminated.

        This function assumes that no extra variables will be provided at
        run-time and that the state passed in is what will be there when the
        Makefile actually runs.

        The implementation of this function is still horribly naive. A more
        appropriate solution would involve variable tainting, where any
        detected modification in non-deterministic statements would taint
        future references, making them also non-deterministic.
        '''

        variables = pymake.data.Variables()

        def callback(action, name, value=None):
            if action != pymake.data.ExpansionContext.GET_ATTRIBUTE:
                raise Exception('Non-get action not supported')

            if name == 'variables':
                return variables

            # We should never get here because we should detect
            # non-deterministic functions before we ever resolve a variable.
            raise AttributeError('Explicitly disallowed access to attribute: %s' % name)

        context = pymake.data.ExpansionContext(callback)

        # List of ([evaluations], taken_branch_index)
        # Each evaluation is True if it evaluated to true, False if
        # it evaluated to False, or None if it could not be evaluated
        # or was not evaluated because a previous branch was taken.
        condition_block_stack = []

        def parse_statements(input, output):
            # Conditionals are expanded immediately, during the first pass, so
            # it is safe to linearly traverse and prune as we go.
            for s in input:
                if s.is_condition_block:
                    condition_block_stack.append([[], None])
                    output.append(s)
                    continue

                # Perform common actions when we arrive at a new test.
                if s.is_ifdef or s.is_ifeq or s.is_else:
                    top = condition_block_stack[-1]

                    # If any of the branches before it could not be evaluated,
                    # it is futile for us to test because that would preclude
                    # the earlier branches from having an opportunity to run.
                    all_evaluated = True
                    for t in top[0]:
                        if t is None:
                            all_evaluated = False
                            break

                    if not all_evaluated:
                        output.append(s)
                        continue

                    # If we have marked a branch as active, say we didn't
                    # evaluate the current one and move on.
                    if top[1] is not None:
                        top[0].append(None)
                        output.append(s)
                        continue

                if s.is_ifdef:
                    # There are risks with this naive approach. See the method
                    # docs.
                    result = s.statement.evaluate(context)

                    top = condition_block_stack[-1]

                    # We were able to evaluate the conditional
                    top[0].append(result)

                    # We take this branch
                    if result:
                        top[1] = s.condition_index

                elif s.is_ifeq:
                    top = condition_block_stack[-1]

                    # We don't go down this rabbit hole right now. The code is
                    # here, but it doesn't work properly. So, we just ignore
                    # ifeq's.
                    top[0].append(None)
                    output.append(s)
                    continue

                    # ifeq's are a little more complicated than ifdefs. The details
                    # are buried in called methods. The gist is we see if the
                    # conditions are deterministic. If they are, we evaluate.
                    if s.are_expansions_deterministic(variables=variables):
                        result = s.statement.evaluate(context)

                        top[0].append(result)

                        if result:
                            top[1] = s.condition_index

                    else:
                        top[0].append(None)

                elif s.is_else:
                    # We would be filtered out by the catch-all above if we
                    # weren't relevant. So, we assume we are the active
                    # branch.
                    top = condition_block_stack[-1]
                    top[0].append(True)
                    top[1] = s.condition_index

                elif s.is_include:
                    filename = s.expansion.resolvestr(context, variables).strip()

                    # The directory to included files is the (possibly virtual)
                    # directory of the current file plus the path from the
                    # Makefile

                    normalized = os.path.join(self.directory, filename)

                    if os.path.exists(normalized):
                        included = StatementCollection(
                            filename=normalized,
                            directory=self.directory)

                        #temp = []
                        #parse_statements(included.statements, temp)
                    elif s.statement.required:
                        print 'DOES NOT EXISTS: %s' % normalized

                elif s.is_setvariable:
                    if not s.are_expansions_deterministic(variables=variables):
                        # TODO Mark the variable as non-deterministic and poison
                        # future tests
                        output.append(s)
                        continue
                    else:
                        s.statement.execute(context, None)

                elif s.is_condition_block_end:
                    # Grab the state from the stack
                    popped = condition_block_stack.pop()

                    active_branch = popped[1]

                    # If we didn't take a branch, there isn't much we can do
                    if active_branch is None:
                        output.append(s)
                        continue

                    # We took a branch. So, we play back the statements,
                    # filtering out the ones that aren't relevant. First, we
                    # need to find the start of this conditional block.
                    start_index = None
                    for i in range(len(output)-1, 0, -1):
                        s2 = output[i]
                        if s2.is_condition_block and s2.level == s.level:
                            start_index = i
                            break

                    assert(start_index is not None)

                    # Get rid of the beginning condition block before we begin.
                    replay = output[start_index + 1:]
                    del output[start_index:]

                    while len(replay) > 0:
                        replay_current = replay[0]

                        # Nested condition blocks get lifted wholesale
                        if replay_current.is_condition_block:
                            count = 1
                            for s2 in replay[1:]:
                                count += 1

                                if s2.is_condition_block_end:
                                    break

                            output.extend(replay[0:count])
                            del replay[0:count]
                            print 'LIFTED CONDITION BLOCK: %s' % count
                            continue

                        assert(replay_current.is_condition)
                        assert(replay_current.condition_index is not None)

                        # If we are at a branch we didn't take, filter it out.
                        if replay_current.condition_index != active_branch:
                            count = 1
                            for s2 in replay[1:]:
                                count += 1

                                if s2.is_condition_end:
                                    break

                            assert(count > 1)
                            del replay[0:count]
                            continue

                        # We must be in the active branch. The current
                        # statement, the condition, can be filtered. The
                        # last should should be an end condition as well. But,
                        # we verify that, just to be sure.
                        assert(replay[-1].is_condition_end)

                        for s2 in replay[1:-1]:
                            s2.level -= 2
                            output.append(s2)

                        del replay[:]

                    continue

                output.append(s)

        out = []
        parse_statements(self.statements, out)
        self.clear_caches()
        self.statements = out

    def clear_caches(self):
        '''During normal operation, this object caches some data. This clears
        those caches.'''
        self._ifdefs = None

    def _load_raw_statements(self, statements):
        '''Loads PyMake's parser output into this container.'''

        self.statements = []

        for statement in statements:
            if isinstance(statement, pymake.parserdata.ConditionBlock):
                self.statements.append(ConditionBlock(statement))
            else:
                self.statements.append(Statement(statement)

class Makefile(object):
    '''A high-level API for a Makefile.

    This provides a convenient bridge between StatementCollection,
    pymake.data.Makefile, and raw file operations.

    From an API standpoint, interaction between the 3 is a bit fuzzy. Read
    the docs for caveats.
    '''
    __slots__ = (
        'filename',      # Filename of the Makefile
        'directory',     # Directory holding the Makefile
        '_makefile',     # PyMake Makefile instance
        '_statements',   # StatementCollection for this file.
        '_lines',        # List of lines containing (modified) Makefile lines
    )

    RE_SUB = re.compile(r"@([a-z0-9_]+?)@")

    def __init__(self, filename, directory=None):
        '''Construct a Makefile from a file'''
        if not os.path.exists(filename):
            raise Exception('Path does not exist: %s' % filename)

        self.filename  = filename

        if directory is not None:
            self.directory = directory
        else:
            self.directory = os.path.dirname(filename)

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

            self._statements = StatementCollection(filename=self.filename,
                                                   buf=buf,
                                                   directory=self.directory)

        return self._statements

    @property
    def makefile(self):
        if self._makefile is None:
            if self._lines is not None:
                raise Exception('Cannot load Makefile from modified content at this time')

            self._makefile = pymake.data.Makefile(workdir=self.directory)
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
