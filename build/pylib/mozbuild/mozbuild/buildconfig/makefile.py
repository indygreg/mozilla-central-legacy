# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

# This file contains classes for interacting with Makefiles. There are a number
# of classes that wrap PyMake's classes with useful APIs. This functionality
# could likely be merged into PyMake if there is desire for doing that. It was
# developed outside of PyMake so development wouldn't be dependent on changes
# being merged into PyMake.
#
# None of the functionality in this file should be Mozilla-specific. It should
# be reusable for any Makefile.

from . import data

import collections
import os
import os.path
import pymake.data
import pymake.parser
import pymake.parserdata
import re
import StringIO

class Expansion(object):
    """Represents an individual Makefile/PyMake expansion.

    An expansion is a parsed representation of Makefile text. It contains
    pointers to string literals, functions, other variables, etc.
    """

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

    # Classes in this set rely on the filesystem and thus may change during
    # run-time.
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

        '_is_static_string',
    )

    def __init__(self, expansion=None, s=None, location=None):
        """Initialize from an existing PyMake expansion or text"""

        self._is_static_string = None

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

    def difference(self, other):
        """Determine the difference between this and another Expansions.

        Returns None if there is no functional difference. Otherwise, return
        a tuple of:

          ( why, our_expansion, their_expansion )

        Where why is a str describing what is different.
        """
        assert(isinstance(other, Expansion))
        is_our_exp = isinstance(self.expansion, pymake.data.Expansion)
        is_other_exp = isinstance(self.expansion, pymake.data.Expansion)

        if is_our_exp != is_other_exp:
            return ('Expansions not of same type', self, other)

        if not is_our_exp and not is_other_exp:
            assert(isinstance(self.expansion, pymake.data.StringExpansion))
            assert(isinstance(other.expansion, pymake.data.StringExpansion))

            if self.expansion.s != other.expansion.s:
                if self.expansion.s.strip() == other.expansion.s.strip():
                    return ('StringExpansion content not identical (whitespace)', self, other)
                else:
                    return ('StringExpansion content not identical', self, other)
            else:
                return None

        us = collections.deque(self.expansion)
        them = collections.deque(other.expansion)
        # and after all we're only ordinary men

        while len(us) > 0 and len(them) > 0:
            ours, ours_is_func = us.popleft()
            theirs, theirs_is_func = them.popleft()

            if ours_is_func != theirs_is_func:
                return ('Type of expansion not the same', ours, theirs)

            if ours_is_func:
                if type(ours) != type(theirs):
                    return ('Type of function not identical', ours, theirs)

                # Sadly, VariableRef and SubstitutionRef need to be handled as
                # one-offs because they don't follow the typical Function class
                # API.
                if isinstance(ours, pymake.functions.VariableRef):
                    diff = Expansion(ours.vname).difference(Expansion(theirs.vname))
                    if diff is not None:
                        return diff
                    continue

                if isinstance(ours, pymake.functions.SubstitutionRef):
                    diff = Expansion(ours.vname).difference(Expansion(theirs.vname))
                    if diff is not None:
                        return diff

                    diff = Expansion(ours.substfrom).difference(Expansion(theirs.substfrom))
                    if diff is not None:
                        return diff

                    diff = Expansion(ours.substto).difference(Expansion(theirs.substto))
                    if diff is not None:
                        return diff

                    continue

                if len(ours) != len(theirs):
                    return ('Length of function arguments not identical', ours, theirs)

                for offset in range(0, len(ours)):
                    diff = Expansion(ours[offset]).difference(Expansion(theirs[offset]))
                    if diff is not None:
                        return diff

                continue

            else:
                assert(isinstance(ours, str))
                assert(isinstance(theirs, str))

                if ours != theirs:
                    message = 'Expansion member string content not identical'
                    if ours.strip() == theirs.strip():
                        message += ' (whitespace)'

                    return (
                        message,
                        Expansion(s=ours, location=self.location),
                        Expansion(s=theirs, location=other.location)
                    )

                continue

        return None


    def split(self):
        """Split this expansion into words and return the list."""
        s = str(self).strip()
        if len(s) > 1:
            return s.split(' ')
        else:
            return []

    @property
    def location(self):
        """Obtain the pymake.parserdata.Location for this expansion."""
        return self.expansion.loc

    @property
    def is_static_string(self):
        """Indicates whether the expansion is a static string.

        A static string is defined as an expansion that consists of no elements
        beside strongly typed strings."""
        if self._is_static_string is None:
            if isinstance(self.expansion, pymake.data.StringExpansion):
                self._is_static_string = True
                return True

            assert(isinstance(self.expansion, pymake.data.Expansion))

            for e, is_func in self.expansion:
                if is_func:
                    self._is_static_string = False
                    return False

            self._is_static_string = True

        return self._is_static_string

    def is_filesystem_dependent(self):
        """Indicates whether this expansion is dependent on the state of the
        filesystem."""
        for f in self.functions(descend=True):
            if isinstance(f, Expansion.FILESYSTEM_FUNCTION_CLASSES):
                return True

        return False

    def is_shell_dependent(self):
        """Indicates whether this expansion is dependent on the output of a
        shell command."""
        for f in self.functions(descend=True):
            if isinstance(f, pymake.functions.ShellFunction):
                return True

        return False

    def functions(self, descend=False):
        """A generator for functions in this expansion.

        Each returned item is a pymake.functions.Function instance.

        Arguments:

        descend -- If True, descend and find inner functions.
        """
        if isinstance(self.expansion, pymake.data.Expansion):
            for e, is_func in self.expansion:
                if is_func:
                    yield e

                    if descend:
                        if isinstance(e, (pymake.functions.VariableRef, pymake.functions.SubstitutionRef)):
                            continue

                        for i in range(0, len(e)):
                            for f in Expansion(e[i]).functions(descend=True):
                                yield f

    def variable_references(self, descend=False):
        """Generator for all variable references in this expansion.

        Returns Expansion instances which represent the variable name. These
        Expansions will typically be static strings representing the variable
        names, but it is possible for them to reference other variables.

        Arguments:

        descend -- If True, descend into child expansions and find references.
        """
        for f in self.functions(descend=descend):
            if not isinstance(f, pymake.functions.VariableRef):
                continue

            yield Expansion(f.vname, location=f.loc)

    def is_deterministic(self, variables=None, missing_is_deterministic=True):
        """Returns whether the expansion is determinstic.

        A deterministic expansion is one whose value is always guaranteed.
        If variables are not provided, a deterministic expansion is one that
        consists of only string data or transformations on strings. If any
        variables are encounted, the expansion will be non-deterministic by
        the nature of Makefiles, since the variables could come from the
        execution environment or command line arguments. But, we assume
        the current state as defined by the arguments is what will occur
        during real execution. If you wish to override this, set the
        appropriate arguments.
        """

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
        """Convert an expansion to a string.

        This effectively converts a string back to the form it was defined as
        in the Makefile. This is different from the resolvestr() method on
        Expansion classes because it doesn't actually expand variables.

        If error_on_function is True, an Exception will be raised if a
        function is encountered. This provides an easy mechanism to
        conditionally convert expansions only if they contain static data.

        If escape_variables is True, individual variable sigil elements will
        be escaped (i.e. '$' -> '$$').
        """
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
        """Convert an expansion to a list.

        This is similar to expansion_to_string() except it returns a list."""
        s = Expansion.to_str(e).strip()

        if s == '':
            return []
        else:
            return s.split(' ')

    @staticmethod
    def is_static_string(e):
        """Returns whether the expansion consists of only string data."""

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
        """Convert a PyMake function instance to a string."""
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
                return '$(%s)' % Expansion.to_str(ex.vname)

        else:
            raise Exception('Unhandled function type: %s' % ex)


class Statement(object):
    """Holds information about an individual PyMake statement.

    This is a wrapper around classes in pymake.parserdata that provides
    useful features for low-level statement inspection and interaction.

    All parser output from pymake.parserdata is an instance of this class or
    is an instance of a class derived from this one.

    We have overloaded a lot of functionality in this base class. The object
    model would be better if each statement type stood in its own class. The
    main reason it wasn't done this way is laziness. Consumers should not rely
    on many classes being rolled into the generic Statement class forever.
    """

    __slots__ = (
        # The actual statement
        'statement',
    )

    # All of the possible output classes from the PyMake parser. Not all derive
    # from pymake.parserdata.Statement, but we treat them all like they do.
    ALL_PARSERDATA_STATEMENT_CLASSES = (
        pymake.parserdata.Rule,
        pymake.parserdata.StaticPatternRule,
        pymake.parserdata.Command,
        pymake.parserdata.SetVariable,
        pymake.parserdata.EqCondition,
        pymake.parserdata.IfdefCondition,
        pymake.parserdata.ElseCondition,
        pymake.parserdata.ConditionBlock,
        pymake.parserdata.Include,
        pymake.parserdata.VPathDirective,
        pymake.parserdata.ExportDirective,
        pymake.parserdata.UnexportDirective,
        pymake.parserdata.EmptyDirective,
    )

    # Classes that contain a single expansion.
    SINGLE_EXPANSION_CLASSES = (
        pymake.parserdata.Command,
        pymake.parserdata.EmptyDirective,
        pymake.parserdata.ExportDirective,
        pymake.parserdata.IfdefCondition,
        pymake.parserdata.Include,
        pymake.parserdata.VPathDirective,
    )

    # Variables that are automatically available in Makefiles.
    AUTOMATIC_VARIABLES = set(['@', '%', '<', '?', '^', '+', '|', '*'])

    def __init__(self, statement):
        assert(isinstance(statement, Statement.ALL_PARSERDATA_STATEMENT_CLASSES))

        self.statement = statement

    def __eq__(self, other):
        return self.difference(other) is None

    def __str__(self):
        """Convert this statement back to its Makefile representation."""
        if self.is_command:
            return self.command_string
        elif self.is_condition:
            return ConditionBlock.condition_str(self)
        elif self.is_empty_directive:
            return str(Expansion(self.statement.exp))
        elif self.is_export:
            return 'export %s' % Expansion(self.statement.exp)
        elif self.is_include:
            return 'include %s' % Expansion(self.statement.exp)
        elif self.is_rule:
            # We jump through hoops to preserve whitespace
            sep = self.target_separator

            dep_str = Expansion.to_str(self.statement.depexp)
            if len(dep_str) > 0 and dep_str[0] not in (' ', '\t'):
                sep += ' '

            return '\n%s%s%s' % (
                Expansion.to_str(self.statement.targetexp),
                sep,
                dep_str
            )
        elif self.is_set_variable:
            return self.setvariable_string
        elif self.is_static_pattern_rule:
            sep = self.target_separator
            pattern = Expansion.to_str(self.statement.patternexp)
            dep = Expansion.to_str(self.statement.depexp)

            if len(pattern) > 0 and pattern[0] not in (' ', '\t'):
                sep += ' '

            return ('\n%s%s%s:%s' % (
                Expansion.to_str(self.statement.targetexp),
                sep,
                pattern,
                dep
            ))
        elif self.is_vpath:
            return 'vpath %s' % Expansion(self.statement.exp)
        else:
            raise Exception('Unhandled statement type: %s' % self.statement)

    def __repr__(self):
        s = None
        if self.is_condition:
            s = str(self.statement)
        else:
            fd = StringIO.StringIO()
            self.statement.dump(fd, '')
            s = fd.getvalue()

        return '<%s>' % s

    # The following are simple tests for the type of statement
    @property
    def is_rule(self):
        return isinstance(self.statement, pymake.parserdata.Rule)

    @property
    def is_static_pattern_rule(self):
        return isinstance(self.statement, pymake.parserdata.StaticPatternRule)

    @property
    def is_command(self):
        return isinstance(self.statement, pymake.parserdata.Command)

    @property
    def is_set_variable(self):
        return isinstance(self.statement, pymake.parserdata.SetVariable)

    @property
    def is_ifeq(self):
        return isinstance(self.statement, pymake.parserdata.EqCondition)

    @property
    def is_ifdef(self):
        return isinstance(self.statement, pymake.parserdata.IfdefCondition)

    @property
    def is_else(self):
        return isinstance(self.statement, pymake.parserdata.ElseCondition)

    @property
    def is_condition_block(self):
        return False

    @property
    def is_include(self):
        return isinstance(self.statement, pymake.parserdata.Include)

    @property
    def is_vpath(self):
        return isinstance(self.statement, pymake.parserdata.VPathDirective)

    @property
    def is_export(self):
        return isinstance(self.statement, pymake.parserdata.ExportDirective)

    @property
    def is_unexport(self):
        return isinstance(self.statement, pymake.parserdata.UnExportDirective)

    @property
    def is_empty_directive(self):
        return isinstance(self.statement, pymake.parserdata.EmptyDirective)

    @property
    def is_condition(self):
        return isinstance(self.statement, pymake.parserdata.Condition)


    # Accessors available to all statements
    def lines(self):
        """Returns an iterator of str representing the statement transformed
        to Makefile syntax."""
        yield str(self)

    @property
    def location(self):
        """Returns the best pymake.parserdata.Location instance for this
        instance.

        May return None if a suitable location is not available.
        """

        # Expansions is a generator, so we can't subscript.
        for e in self.expansions:
            return e.location

        return None

    def difference(self, other):
        """Determines the difference between this and another Statement.

        We define equivalence to mean the composition of the statement is
        equivalent. We do not test things like locations or the expanded value
        of variables, etc.

        Practically speaking, if two statement appears on consecutive lines
        and the first does not have any side-effects, then the two statements
        are equivalent.

        If there is no difference, None is returned. If there is a difference,
        returns a tuple of:

          ( why, our_expansion, their_expansion )

        Where why is a str explaining the difference and the expansion members
        can be Expansion instances that caused the disagreement.
        """
        if not isinstance(other, Statement):
            return ('Other type is not a Statement', None, None)

        if type(self.statement) != type(other.statement):
            return ('pymake statement type not identical', None, None)

        our_expansions = collections.deque(self.expansions)
        other_expansions = collections.deque(other.expansions)

        while len(our_expansions) > 0 and len(other_expansions) > 0:
            ours = our_expansions.popleft()
            theirs = other_expansions.popleft()

            difference = ours.difference(theirs)
            if difference is None:
                continue

            return difference

        if len(our_expansions) == 0 and len(other_expansions) == 0:
            return None

        ret_ours = None
        ret_theirs = None
        if len(our_expansions) > 0:
            ret_ours = our_expansions.popleft()

        if len(their_expansions) > 0:
            ret_theirs = other_expansions.popleft()

        return ('Length of expansions not equivalent', ret_ours, ret_theirs)

    @property
    def expansions(self):
        """Returns an iterator over all expansions in this statement.

        Each returned item is an Expansion instance.
        """
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
        elif self.is_set_variable:
            if self.statement.targetexp is not None:
                yield Expansion(expansion=self.statement.targetexp)

            yield Expansion(expansion=self.statement.vnameexp)
            yield Expansion(s=self.statement.value, location=self.statement.valueloc)
        elif self.is_else:
            return
        else:
            raise Exception('Unhandled statement type: %s' % self)

    def variable_references(self, descend=False):
        """A generator for variables referenced in this statement.

        Each returned item is an Expansion instance.

        Arguments:

        descend -- If True, descend into expansions contained within primary
                   expansions.
        """
        for e in self.expansions:
            for v in e.variable_references(descend=descend): yield v

    def are_expansions_deterministic(self, variables=None):
        """Determines whether the expansions in this statement are
        deterministic."""

        # TODO figure out what to do about target expansions. Resolving
        # these expansions results in access to Makefile.gettarget()
        if self.is_set_variable and self.statement.targetexp is not None:
            return False

        for e in self.expansions:
            if not e.is_deterministic(variables=variables):
                return False

        return True

    # Statement-specific accessors and methods. If invoked on the wrong
    # statement type, expect an assertion failure.

    @property
    def command_string(self):
        """Converts a command expansion back into its string form.

        Commands are interesting beasts for a couple of reasons.

        First, they can be multi-line. A tab character is inserted at the
        beginning of each line.

        There also might be variable references inside the command.
        To the shell, $foo is correct. However, to Makefiles, we need
        $$foo.
        """
        assert(self.is_command)

        s = Expansion.to_str(self.statement.exp, escape_variables=True)

        return '\n'.join(['\t%s' % line for line in s.split('\n')])

    @property
    def command_name(self):
        """Obtain the name of the command being executed.

        Returns a str or None if the command is empty or doesn't appear to be a
        command.
        """
        assert(self.is_command)

        words = Expansion(self.statement.exp).split()
        if len(words) == 0:
            return None

        command = words[0]
        if command.find('=') != -1:
            return None

        return command.lstrip('@#-+(')

    @property
    def has_doublecolon(self):
        """Returns whether the rule has a double-colon."""
        assert(self.is_rule or self.is_static_pattern_rule)

        return self.statement.doublecolon

    @property
    def target(self):
        """The expansion for the rule target."""
        assert(self.is_rule or self.is_static_pattern_rule)

        return Expansion(self.statement.targetexp)

    @property
    def pattern(self):
        """The expansion for this static rule pattern."""
        assert(self.is_static_pattern_rule);

        return Expansion(self.statement.patternexp)

    @property
    def prerequisites(self):
        """The expansion for the rule prerequisites."""
        assert(self.is_rule or self.is_static_pattern_rule);

        return Expansion(self.statement.depexp)

    @property
    def target_separator(self):
        """Returns the colon separator after the target for rules."""
        assert(self.is_rule or self.is_static_pattern_rule)

        if self.has_doublecolon:
            return '::'
        else:
            return ':'

    @property
    def expected_condition(self):
        """For condition statements, returns the expected condition of the test
        for the branch under the statement to be executed."""
        assert(self.is_ifeq or self.is_ifdef)

        return self.statement.expected

    @property
    def required(self):
        """Whether the statement is required."""
        assert(self.is_include)

        return self.statement.required

    @property
    def token(self):
        """Returns the token for this statement."""
        assert(self.is_set_variable)

        return self.statement.token

    @property
    def setvariable_string(self):
        """Converts a SetVariable statement to a string.

        SetVariable statements are a little funky. In the common case, they
        have the form "foo = bar". If they have a target expression, there
        is the form "targ: foo = bar". And, for multi-line variables, you
        use the define directive. It ia all pretty funky.
        """

        assert(self.is_set_variable)

        value = self.value.replace('#', '\\#')

        if self.statement.targetexp is not None:
            return '%s: %s %s %s' % (
                    Expansion.to_str(self.statement.targetexp),
                    self.vname,
                    self.token,
                    value
                )

        # Now we have the common case. But, it could be multiline.
        multiline = value.count('\n') > 0

        if multiline:
            # According to 6.8 of the Make manual, the equals is optional.
            return 'define %s\n%s\nendef\n' % (self.vname, value)
        else:
            sep = self.token
            if len(value) and value[0] not in (' ', '\t'):
                sep += ' '
            return ('%s %s%s' % (self.vname, sep, value))

    @property
    def value(self):
        """Returns the value of this statement."""
        assert(self.is_set_variable)

        return self.statement.value

    @property
    def value_expansion(self):
        """Returns the value of this SetVariable statement as an expansion.

        By default, variable values are stored as strings. They can be
        upgraded to expansions upon request."""
        assert(self.is_set_variable)

        data = pymake.parser.Data.fromstring(self.statement.value, self.statement.valueloc)
        return Expansion(expansion=pymake.parser.parsemakesyntax(data, 0, (),
                         pymake.parser.iterdata)[0])

    @property
    def vname(self):
        """Returns the variable name as an expansion."""
        assert(self.is_set_variable)

        return Expansion(self.statement.vnameexp)

class ConditionBlock(Statement):
    """Represents a condition block statement.

    The condition block is a collection of conditions and statements inside
    those conditions. The structure mimics that of
    pymake.parserdata.ConditionBlock. However, we provide some higher-level
    APIs."""

    __slots__ = (
        # Array of tuples of ( condition statement, [ statements ] )
        'conditions',
    )

    def __init__(self, statement):
        assert(isinstance(statement, pymake.parserdata.ConditionBlock))

        Statement.__init__(self, statement)

        self.conditions = []

        for condition, statements in statement:
            wrapped = []
            for s in statements:
                if isinstance(s, pymake.parserdata.ConditionBlock):
                    wrapped.append(ConditionBlock(s))
                else:
                    wrapped.append(Statement(s))
            self.conditions.append((Statement(condition), wrapped))

    def __str__(self):
        """Convert the condition block back to its Makefile representation."""
        return '\n'.join(self.lines())

    def __iter__(self):
        return iter(self.conditions)

    def __len__(self):
        return len(self.conditions)

    def __getitem__(self, i):
        return self.conditions[i]

    @property
    def is_condition_block(self):
        return True

    @property
    def is_ifdef_only(self):
        """Is the condition block composed only of ifdef statements?"""
        for condition, statements in self:
            if condition.is_ifeq:
                return False

            assert(condition.is_ifdef or condition.is_else)

        return True

    @property
    def has_ifeq(self):
        """Does the condition block have any ifeq components?"""
        return not self.is_ifdef_only

    @property
    def expansions(self):
        """A generator for expansions in the conditions block."""
        for condition, statements in self:
            for e in condition.expansions: yield e
            for s in statements:
                for e in s.expansions: yield e

    def lines(self):
        """Returns an iterable of str representing the Makefile of lines
        composing this condition block."""
        index = 0
        for condition, statements in self:
            yield ConditionBlock.condition_str(condition, index)
            index += 1

            for statement in statements:
                yield str(statement)

        yield 'endif'

    def determine_condition(self, makefile, allow_nondeterministic=False):
        """Evaluate conditions in this block and determine which one executes.

        Possible return values:
          int -- Index of the condition that evaluated to True.
          None -- Unable to determine condition.
          False -- The condition didn't evaluate to True.

        False should only be returned on condition blocks consisting of one
        condition.

        None will likely be returned if a non-deterministic expansion is seen
        in a condition.

        Arguments:

        makefile -- Makefile context for execution.
        allow_nondeterministic -- If a nondeterministic expansion is seen,
                                  try to evaluate it. This is very dangerous.
        """
        for i in range(0, len(self)):
            condition = self.conditions[i][0]

            if condition.is_ifdef:
                if condition.statement.evaluate(makefile):
                    return i

            elif condition.is_ifeq:
                deterministic = condition.are_expansions_deterministic(makefile.variables)

                if deterministic:
                    if condition.statement.evaluate(makefile):
                        return i
                    else:
                        continue

                if not allow_nondeterministic:
                    return None

            # If we get to the else condition, all other branches must have
            # evaluated to False.
            elif condition.is_else:
                assert(i == len(self) - 1)
                return i

            else:
                raise Exception('Unexpected condition type: %s' % type(condition.statement))

        assert(len(self) == 1)
        return False

    @staticmethod
    def condition_str(statement, index=None):
        """Convert a condition to a string representation.

        The index argument defines the index of this condition inside a
        condition block. If the index is greater than 0, an else will be
        added to the representation.
        """

        prefix = ''
        if (statement.is_ifdef or statement.is_ifeq) and index > 0:
            prefix = 'else '

        if statement.is_ifdef:
            s = Expansion(statement.statement.exp)

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
        """Returns whether evaluation of this condition block is determinstic.

        Evaluation is considered deterministic if all conditions are
        deterministic. Note that an else condition is always determinstic, so
        for simple ifeq..else..end, if the ifeq is determinstic, the whole
        thing is deterministic.
        """
        pass

class StatementCollection(object):
    """Mid-level API for interacting with Makefile statements.

    This is effectively a wrapper around PyMake's parser output. It can
    be used to extract data from low-level parser output. It can even perform
    basic manipulation of Makefiles.

    If you want to perform static analysis of Makefiles or want to poke around
    at what's inside, this is the class to use or extend.
    """

    VARIABLE_ASSIGNMENT_SIMPLE = 1
    VARIABLE_ASSIGNMENT_RECURSIVE = 2
    VARIABLE_ASSIGNMENT_APPEND = 3
    VARIABLE_ASSIGNMENT_CONDITIONAL = 4

    __slots__ = (
         # String filename we loaded from. A filename must be associated with
         # a Makefile for things to work properly.
        'filename',

        # Directory the Makefile runs in. By default, this is set to the
        # directory of the filename. However, it is completely valid for
        # instantiators to override this with something else. A use case would
        # be if the contents are being read from one location but should
        # appear as if it is loaded from elsewhere. This is useful for
        # tricking filesystem functions into working, for example.
        'directory',

        # List of our normalized statements. Each element is a Statement
        # or derived class.
        '_statements',
    )

    def __init__(self, filename=None, buf=None, directory=None):
        """Construct a set of statements.

        If buf is defined, filename must all be defined. If buf is defined,
        statements will be read from that string. Else, statements will be
        read from the passed filename.
        """
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

    def lines(self):
        """Emit lines that constitute a Makefile for this collection.

        To generate the Makefile representation of this instance, simply:

          '\n'.join(foo.lines())

        Or,

          for line in foo.lines():
            print >>fh, line
        """
        for statement in self._statements:
            for line in statement.lines(): yield line

    def difference(self, other):
        """Obtain the difference between this instance and another one.

        This is a helper method to identify where/how two supposedly
        equivalent Makefiles differ.

        If the two instances are functionally equivalent, None is returned.
        If they are different, a dictionary is returned with the form:
          {
            'index': 6, # Numeric index of statements at which things were
                        # different
            'ours': Statement,   # Our statement that didn't match
            'theirs': Statement, # Their statement that didn't match
            'our_expansion': Expansion, # Our expansion that didn't match
            'their_expansion': Expansion, # Their expansion that didn't match
            'why': 'X was Y', # str explaining why they were different
          }
        """
        assert(isinstance(other, StatementCollection))
        our_statements = collections.deque(self.expanded_statements(suppress_condition_blocks=True))
        other_statements = collections.deque(other.expanded_statements(suppress_condition_blocks=True))

        error = {
            'index': -1,
            'our_line': -1,
            'their_line': -1,
            'why': 'Unknown',
        }

        while len(our_statements) > 0 and len(other_statements) > 0:
            error['index'] += 1
            ours = our_statements.popleft()[0]
            theirs = other_statements.popleft()[0]

            # Pure laziness
            error['ours'] = ours
            error['theirs'] = theirs

            difference = ours.difference(theirs)
            if difference is None:
                continue

            error['why'] = difference[0]
            error['our_expansion'] = difference[1]
            error['their_expansion'] = difference[2]
            return error

        if len(our_statements) == 0 and len(other_statements) == 0:
            return None

        error['why'] = 'statement lengths did not agree'
        return error

    def expanded_statements(self, suppress_condition_blocks=False):
        """Returns an iterator over the statements in this collection.

        Each returned item is a tuple of:

            ( Statement, [conditions] )

        Each Statement is the Statement instance being returned. The 2nd
        member is a list of conditions that must be satisfied for this
        statement to be evaluated. Each element is merely a reference to
        a Statement that was emitted previously. In other words, this is a
        convenient repackaging to make less stateful consumption easier.
        An emitted condition does not contain itself on the preconditions
        stack.

        Condition blocks are emitted as a Statement first followed by all
        of their individual statements, starting with the condition for
        the first branch.

        It is possible to detect the end of a condition block by noting when
        len(conditions) decreases. A new branch in the same condition block
        is entered when entry[0].is_condition is True. The implementation of
        various methods in this class demonstrate this technique and can be
        used as a reference.

        Arguments:

        suppress_condition_blocks -- If True, the Condition Block statement
                                     will not be emitted. However, everything
                                     else is the same.
        """
        condition_stack = []

        def emit_statements(statements):
            for statement in statements:
                emit = True
                if statement.is_condition_block and suppress_condition_blocks:
                    emit = False

                if emit:
                    yield (statement, condition_stack)

                if statement.is_condition_block:
                    for condition, inner in statement:
                        yield (condition, condition_stack)
                        condition_stack.append(condition)

                        for t in emit_statements(inner):
                            yield t

                        condition_stack.pop()

        for t in emit_statements(self._statements): yield t

        assert(len(condition_stack) == 0)

    def expansions(self):
        """A generator for all Expansions in this collection.

        Each returned item is a tuple of:

          ( statement, conditions, expansion )

        Where expansion is an Expansion and statement is the Statement it
        belongs to.
        """
        statements = self.expanded_statements(suppress_condition_blocks=True)
        for statement, conditions in statements:
            # Condition blocks expand to their child elements. The child
            # elements come after, so we ignore to avoid double output.
            if statement.is_condition_block:
                continue

            for expansion in statement.expansions:
                yield (statement, conditions, expansion)

    def ifdefs(self):
        """A generator of ifdef metadata in this collection.

        Each returned item is a tuple of:

          ( statement, conditions, name, expected )

        The first member is the underlying Statement instance. name is a str
        of the variable being checked for definintion. expected is the boolean
        indicating the expected evaluation for the condition to be satisfied.
        Finally, conditions is a list of conditions that must be satisfied for
        this statement to be evaluated.

        Please note that "name" is a str, not an Expansion. This is because
        ifdef statements operate on variable names, not variables themselves.

        name and expected can be accessed from the underlying Statement, of
        course. They are provided explicitly for convenience.
        """
        statements = self.expanded_statements(suppress_condition_blocks=True)
        for statement, conditions in statements:
            if not statement.is_ifdef:
                continue

            yield (statement,
                   conditions,
                   str(list(statement.expansions)[0]),
                   statement.statement.expected)

    def includes(self):
        """A generator of includes metadata.

        Each returned item is a tuple of:

          ( statement, conditions, path )

        The first member is the underlying Statement. The second is a list
        of conditions that must be satisfied for this statement to be executed.
        Finally, we have the path Expansion for this statement. It is up
        to the caller to expand the expansion.
        """
        for statement, conditions in self.expanded_statements():
            if not statement.is_include:
                continue

            yield (statement, conditions, list(statement.expansions)[0])

    def variable_assignments(self):
        """A generator of variable assignments.

        Each returned item is a tuple of:

          ( statement, conditions, name, value, type )

        The first member is the underlying Statement. The second is the list
        of conditions that must be satisfied for this statement to execute.
        The 3rd, or name, or is the variable name, as a str. The 4th is the
        value, as a str. The 5th is the type of variable assignment/reference.
        This will be one of the VARIABLE_ASSIGNMENT_* constants from this
        class.
        """
        for statement, conditions in self.expanded_statements():
            if not statement.is_set_variable:
                continue

            vname = statement.vname

            type = None
            token = statement.token
            if token == '=':
                type = StatementCollection.VARIABLE_ASSIGNMENT_RECURSIVE
            elif token == ':=':
                type = StatementCollection.VARIABLE_ASSIGNMENT_SIMPLE
            elif token == '+=':
                type = StatementCollection.VARIABLE_ASSIGNMENT_APPEND
            elif token == '?=':
                type = StatementCollection.VARIABLE_ASSIGNMENT_CONDITIONAL
            else:
                raise Exception('Unhandled variable assignment token: %' % token)

            yield (statement, conditions, str(vname), statement.value, type)

    def unconditional_variable_assignments(self):
        """This is a convenience method to return variables that are assigned
        to unconditionally. It is simply a filter over variable_assignments()
        which filters out entries where len(entry[1]) == 0.

        Each returned item is a tuple of:

          ( statement, name, value, type )

        The members have the same meaning as variable_assignments().
        """

        for t in self.variable_assignments():
            if len(t) > 0:
                pass

            yield (t[0], t[2], t[3], t[4])

    def variable_references(self):
        """Generator for references to variables.

        Returns Expansion instances that expand to the name of the variable.
        """
        for statement, conditions in self.expanded_statements():
            for v in statement.variable_references(descend=True): yield v

    def all_rules(self):
        """A generator for all rules in this instance.

        Each returned item is a tuple of:

          ( statement, conditions, target, prerequisites, commands, pattern )

        statement is the underlying Statement instance and conditions is the
        list of conditions that must be satisfied for this rule to be
        evaluated.

        target is the Expansion for the target of this rule. Next is
        prerequisite, which is an Expansion of the prerequisites for this
        rule. Finally, we have commands, which is a list of the command
        Statement instances that will be evaluated for this rule.

        If the rule is a regular rule, pattern will be None. If the rule is a
        static pattern rule, it will be an expansions.
        """

        # Commands are associated with rules until another rule comes along.
        # So, we keep track of the current rule and add commands to it as we
        # encounter commands. When we see a new rule, we flush the last rule.
        # When we're done, if we have a rule, we flush it.
        current_rule = None
        for statement, conditions in self.expanded_statements():
            if statement.is_rule or statement.is_static_pattern_rule:
                if current_rule:
                    yield current_rule

            if statement.is_rule:
                current_rule = (statement,
                                conditions,
                                statement.target,
                                statement.prerequisites,
                                [],
                                None)
            elif statement.is_static_pattern_rule:
                current_rule = (statement,
                                conditions,
                                statement.target,
                                statement.prerequisites,
                                [],
                                statement.pattern)
            elif statement.is_command:
                assert(current_rule is not None)
                current_rule[4].append(statement)

        if current_rule is not None:
            yield current_rule

    def rules(self):
        """A generator for rules in this instance.

        Each returned item is a tuple of:

            ( statement, conditions, target, prerequisite, commands )

        Please note this only returns regular rules and not static pattern
        rules.
        """
        for t in self.all_rules():
            if t[5] is not None:
                continue

            yield (t[0], t[1], t[2], t[3], t[4])

    def static_pattern_rules(self):
        """A generator for static pattern rules.

        Each returned item is a tuple of:
          ( statement, conditions, target, pattern, prerequisites, commands )

        The values have the same meaning as those in rule(). However, we have
        added pattern, which is an Expansion of the pattern for the rule.
        """
        for t in self.all_rules():
            if t[5] is None:
                continue

            yield t

    # Here is where we start defining more esoteric methods dealing with static
    # analysis and modification.

    def filesystem_dependent_statements(self):
        """A generator for statements that directly depend on the state of
        the filesystem.

        Each returned item is a tuple of:

          ( statement, conditions )
        """
        statements = self.expanded_statements(suppress_condition_blocks=True)
        for statement, conditions in statements:
            for expansion in statement.expansions:
                if expansion.is_filesystem_dependent():
                    yield (statement, conditions)
                    break

    def shell_dependent_statements(self):
        """A generator for statements that directly depend on the execution of
        a shell command.

        Each returned item is a tuple of:

          ( statement, conditions )

        This excludes rules, which are implicitly dependent on the output of
        an external command.
        """
        statements = self.expanded_statements(suppress_condition_blocks=True)
        for statement, conditions in statements:
            for expansion in statement.expansions:
                if expansion.is_shell_dependent():
                    yield (statement, conditions)
                    break

    def strip_false_conditionals(self, evaluate_ifeq=False):
        """Rewrite the raw statement list with false conditional branches
        filtered out.

        This is very dangerous and is prone to unexpected behavior if not used
        properly.

        The underlying problem is Makefiles are strongly dependent on the
        run-time environment. There are functions that inspect the filesystem
        or call out to shells. The results of these functions could change
        as a Makefile is being evaluated. Even if you are simply looking at
        variable values, a variable could be provided by an environment
        variable or command line argument.

        This function assumes that no extra variables will be provided at
        run-time and that the state passed in is what will be there when the
        Makefile actually runs.

        The implementation of this function is still horribly naive. A more
        appropriate solution would involve variable tainting, where any
        detected modification in non-deterministic statements would taint
        future references, making them also non-deterministic.

        Arguments:
        evaluate_ifeq  -- Test ifeq conditions
        """

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

        i = 0
        while i < len(self._statements):
            statement = self._statements[i]
            if statement.is_condition_block:
                branch = None

                if statement.is_ifdef_only:
                    branch = statement.determine_condition(context)
                elif evaluate_ifeq:
                    branch = statement.determine_condition(
                        context, allow_nondeterministic=False)
                # Else, we can't evaluate. Keep default branch of None.

                if branch is None:
                    i += 1
                    continue

                if branch is False:
                    del self._statements[i]
                    self._clear_caches()
                    continue

                # We replace the condition block with the statements that
                # are inside the active branch.
                active, active_statements = statement[branch]
                self._statements[i:i + 1] = active_statements
                self._clear_caches()

                # We don't increment the index because the new statement at the
                # current index (the first statement in the taken branch) could
                # be condition block itself.
                continue

            elif statement.is_set_variable:
                if statement.are_expansions_deterministic(variables):
                    statement.statement.execute(context, None)
                else:
                    # TODO we need a better implementation for dealing with
                    # non-deterministic variables.
                    pass

                i += 1
                continue

            elif statement.is_include:
                # TODO evaluate data in included file
                    #filename = s.expansion.resolvestr(context, variables).strip()

                    # The directory to included files is the (possibly virtual)
                    # directory of the current file plus the path from the
                    # Makefile

                    #normalized = os.path.join(self.directory, filename)

                    #if os.path.exists(normalized):
                    #    included = StatementCollection(
                    #        filename=normalized,
                    #        directory=self.directory)

                        #temp = []
                        #parse_statements(included.statements, temp)
                    #elif s.statement.required:
                    #    print 'DOES NOT EXISTS: %s' % normalized

                i += 1
                continue

            else:
                i += 1
                continue

    def _load_raw_statements(self, statements):
        """Loads PyMake's parser output into this container."""

        self._statements = []

        for statement in statements:
            if isinstance(statement, pymake.parserdata.ConditionBlock):
                self._statements.append(ConditionBlock(statement))
            else:
                self._statements.append(Statement(statement))

    def _clear_caches(self):
        """Clears the instance of any cached data."""
        pass

class Makefile(object):
    """A high-level API for a Makefile.

    This provides a convenient bridge between StatementCollection,
    pymake.data.Makefile, and raw file operations.

    From an API standpoint, interaction between the 3 is a bit fuzzy. Read
    the docs for caveats.
    """
    __slots__ = (
        'filename',      # Filename of the Makefile
        'directory',     # Directory holding the Makefile
        '_makefile',     # PyMake Makefile instance
        '_statements',   # StatementCollection for this file.
        '_lines',        # List of lines containing (modified) Makefile lines
    )

    RE_SUB = re.compile(r"@([a-z0-9_]+?)@")

    def __init__(self, filename, directory=None):
        """Construct a Makefile from a file"""
        if not os.path.exists(filename):
            raise Exception('Path does not exist: %s' % filename)

        self.filename = filename

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
        """Obtain the StatementCollection for this Makefile."""
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
            self._makefile = pymake.data.Makefile(workdir=self.directory)

            if self._lines is None:
                self._makefile.include(os.path.basename(self.filename))
                self._makefile.finishparsing()
            else:
                # This hackiness is because pymake doesn't offer an easier API.
                # We basically copy pymake.data.Makefile.include
                statements = pymake.parser.parsestring(''.join(self._lines),
                    self.filename)
                self._makefile.variables.append('MAKEFILE_LIST',
                    pymake.data.Variables.SOURCE_AUTOMATIC, self.filename,
                    None, self._makefile)
                statements.execute(self._makefile, weak=False)
                self._makefile.gettarget(self.filename).explicit = True

        return self._makefile

    def lines(self):
        """Returns a list of lines making up this file."""

        if self._statements:
            for line in self._statements.lines():
                yield line
        elif self._lines is not None:
            for line in self._lines:
                yield line.rstrip('\n')
        else:
            # TODO this could come from file, no?
            raise('No source of lines available')

    def perform_substitutions(self, mapping, raise_on_missing=False,
                              error_on_missing=False, callback_on_missing=None):
        """Performs variable substitutions on the Makefile.

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
        """

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
        """Returns whether a variable is defined in the Makefile.

        By default, it only looks for variables defined in the current
        file, not in included files."""
        if search_includes:
            v = self.makefile.variables.get(name, True)[2]
            return v is not None
        else:
            return name in self.statements.defined_variables

    def get_variable_string(self, name, resolve=True):
        """Obtain a named variable as a string.

        If resolve is True, the variable's value will be resolved. If not,
        the Makefile syntax of the expansion is returned. In either case,
        if the variable is not defined, None is returned.
        """
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
        """Obtain a named variable as a list."""
        v = self.makefile.variables.get(name, True)[2]
        if v is None:
            return []

        return v.resolvesplit(self.makefile, self.makefile.variables)

    def get_own_variable_names(self, include_conditionals=True):
        names = set()

        for stmt, conds, name, value, how in self.statements.variable_assignments():
            if not include_conditionals and len(conds) > 0:
                continue

            names.add(name)

        return names

    def has_own_variable(self, name):
        return name in self.get_own_variable_names(include_conditionals=True)
