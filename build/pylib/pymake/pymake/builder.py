# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

import os.path

from pymake.data import Expansion
from pymake.data import StringExpansion
from pymake.parserdata import Command
from pymake.parserdata import ConditionBlock
from pymake.parserdata import ElseCondition
from pymake.parserdata import IfdefCondition
from pymake.parserdata import Include
from pymake.parserdata import Rule
from pymake.parserdata import SetVariable
from pymake.parserdata import Statement
from pymake.parserdata import StaticPatternRule
from pymake.parser import parsestring
from pymake.parser import parsefile

class Makefile(object):
    """API for querying and modifying make files.

    This is a mid-level API that sits between parsing and execution. Some of
    the things you can do with it include:

      - Inspecting parsed make files
      - Modify parsed make files before execution
      - Create new make files from scratch
      - Write make files back to make file "source"
    """

    def __init__(self, filename, directory=None):
        """Create a new empty make file.

        Make files need to have a filename and directory associated with them
        (in case they are ever evaluated). If you will never evaluate this
        instance, you can pass a dummy value to filename.

        The directory defines the directory in which the make file will be
        evaluated. By default, this is computed from the file name.
        """
        self.filename = filename

        if directory is not None:
            self.directory = directory
        else:
            self.directory = os.path.dirname(filename)

        self._statements = []

    @staticmethod
    def from_filename(filename):
        """Construct a new instance with content read from a file."""
        makefile = Makefile(filename)

        for s in parsefile(filename):
            makefile.append(s)

        return makefile

    @staticmethod
    def from_str(s, filename):
        """Construct a new instance from content contained in a buffer."""
        makefile = Makefile(filename)

        for s in parsestring(s, filename):
            makefile.append(s)

        return makefile

    def append(self, statement):
        """Append a Statement to this make file.

        This is a low-level API.
        """
        assert isinstance(statement, Statement)
        self._statements.append(statement)

    def to_source(self):
        """Obtain the source representation of this make file."""
        self.remove_empty_conditions()

        return '\n'.join([s.to_source() for s in self._statements])

    ##########################
    # METHODS FOR INSPECTING #
    ##########################

    def get_statements(self, suppress_condition_blocks=False):
        """Obtain all the statements in this make file.

        This is a generator for 2-tuples of:

          (pymake.parserdata.Statement, list(pymake.parserdata.Condition))

        The first element of the tuple is the Statement instance. The 2nd
        element is a list of pymake.parserdata.Condition that must be satisfied
        for this statement to be evaluated.

        Each member of the conditions stack is a reference to a previously
        emitted statement.

        When a pymake.parserdata.Condition statement is emitted, it does not
        contain itself on the conditions stack.

        Condition blocks are emitted as a pymake.parserdata.ConditionBlock
        first, followed the first condition, followed by the statements in that
        condition, and so on.

        It is possible to detect the end of a condition block by noting when
        the size of the conditions stack decreases.

        You can detect when a new branch in a condition block is entered by
        when the statement is a pymake.parserd
        ata.Condition.

        This is a very low-level API. Many of the other methods in this class
        are built upon it. For example usage, see other methods in this class.
        """
        condition_stack = []
        def emit_statements(statements):
            for statement in statements:
                emit = True
                if isinstance(statement, ConditionBlock) and suppress_condition_blocks:
                    emit = False

                if emit:
                    yield (statement, condition_stack)

                if not isinstance(statement, ConditionBlock):
                    continue

                for condition, condition_statements in statement:
                    yield (condition, condition_stack)
                    condition_stack.append(condition)

                    for t in emit_statements(condition_statements):
                        yield t

                    condition_stack.pop()

        for t in emit_statements(self._statements): yield t

        assert(len(condition_stack) == 0)

    def get_expansions(self):
        """Obtain all expansions in this make file.

        This is a generator for 3-tuples of:

            ( statement, list(condition), expansion )

        The first element is the pymake.parserdata.Statement the expansion is
        associated with.

        The second element is the stack of pymake.parserdata.Condition that
        must be fulfilled for the statement to evaluate.

        The third is the pymake.data.BaseExpansion.
        """
        for statement, conditions in self.get_statements(suppress_condition_block=True):
            # Condition blocks are flattened as part of get_statements(). Their
            # get_expansions() descends into children. Here, we prevent double
            # traversal.
            if isinstance(statement, ConditionBlock):
                continue

            for expansion in statement.get_expansions():
                yield (statement, conditions, expansion)

    def get_ifdefs(self):
        """Obtain ifdef conditions in this make file.

        This is a generator of 4-tuples of:

          ( statement, conditions, variable_name, expected )

        statement -- Underlying pymake.parserdata.IfdefCondition instance
        conditions -- Stack of pymake.parserdata.Condition that must evaluate
            to True for this condition to even be evaluated.
        variable_name -- str name of variable being checked by this ifdef.
        expected -- bool indicating if the variable must be present for the
            condition to be satisfied. True for ifdef, False for ifndef.
        """
        for statement, conditions in self.get_statements(suppress_condition_blocks=True):
            if not isinstance(statement, IfdefCondition):
                continue

            yield (statement,
                   conditions,
                   statement.exp.to_source(),
                   statement.expected)

    def get_all_rules(self):
        """Obtain all rules in this make file.

        This is a generator of 6-tuples of:

          (statement, conditions, target, prerequisites, commands)

        statement -- Underlying pymake.parserdata.Rule or
            pymake.parserdata.StaticPatternRule representing this rule.
        conditions -- Stack of pymake.parserdata.Condition that must evaluate
            to True for this rule to be evaluated.
        target -- pymake.parserdata.BaseExpansion representing the rule target.
        prerequisites -- pymake.parserdata.BaseExpansion representing the
            prerequisites this rule depends on.
        commands -- list of pymake.parserdata.Statement that will be evaluated
            to satisfy this rule.

        For static pattern rules, the pattern can be obtained from the
        pymake.parserdata.StaticPatternRule instance.
        """

        # The statement list doesn't associate commands with rules. So, we need
        # to do that here. We simply buffer the current rule and add commands
        # until we detect a flush is needed.
        rule = None
        for statement, conditions in self.get_statements():
            if isinstance(statement, (Rule, StaticPatternRule)):
                if rule:
                    yield rule

                rule = (statement, conditions, statement.targetexp,
                        statement.depexp, [])

            elif isinstance(statement, Command):
                assert rule is not None
                rule[4].append(statement)

        # Don't forget to flush!
        if rule is not None:
            yield rule

    def get_rules(self):
        """Obtain all regular rules from this make file.

        This is a filter over get_all_rules() which just returns
        pymake.data.Rule instances.

        The return type is the same as get_all_rules().
        """
        for rule in self.get_all_rules():
            if isinstance(rule[0], Rule):
                yield rule

    def get_static_pattern_rules(self):
        """Obtain all static pattern rules from this make file.

        This is a filter over get_all_rules(). The return type is the same.
        """
        for rule in self.get_all_rules():
            if isinstance(rule[0], StaticPatternRule):
                yield rule

    def get_includes(self):
        """Obtain all inclusion directives for this make file.

        This is a generator of 3-tuples of:

          (statement, conditions, path)

        statement -- pymake.parserdata.Include
        conditions -- stack of pymake.parserdata.Condition that must be True
            for this include to be evaluated.
        path -- pymake.parserdata.BaseExpansion representing the path that will
            be included.
        """
        for statement, conditions in self.get_statements():
            if not isinstance(statement, Include):
                continue

            yield (statement, conditions, statement.exp)

    def get_variable_assignments(self):
        """Obtain the variable assignments in this make file.

        This is a generator of 5-tuples of:

          (statement, conditions, variable name, value, type)
        """
        for statement, conditions in self.get_statements():
            if not isinstance(statement, SetVariable):
                continue

            # TODO have constants for variable type
            yield (statement, conditions, statement.vnameexp.to_source(),
                    statement.value, statement.token)

    def get_unconditional_variable_assignments(self):
        """Obtain variable assignments assigned to unconditionally.

        This is filter for get_variable_assignments() for variables not
        depending on any conditions.
        """
        for t in self.get_variable_assignments():
            if len(t) > 0:
                continue

            yield(t[0], t[2], t[3], t[4])

    ############################
    # Methods for Modification #
    ############################

    def remove_variable_assignment(self, name):
        """Remove assignments to a specific named variable."""
        def f(statement):
            if isinstance(statement, ConditionBlock):
                statement.filter(f)
                return True

            if not isinstance(statement, SetVariable):
                return True

            exp = statement.vnameexp

            if not isinstance(exp, StringExpansion):
                return True

            return exp.s != name

        self._statements = filter(f, self._statements)

    def remove_empty_conditions(self):
        """Removes empty conditions from the statement list.

        Some modifications may leave some branches empty. This will discover
        and delete them.

        This is typically called automatically. You normally don't need to call
        this after modifications.
        """
        def f(statement):
            if not isinstance(statement, ConditionBlock):
                return True

            # The easy answer. Remove the whole thing.
            if statement.statement_count == 0:
                return False

            # The harder way is to look for empty branches.
            branch_counts = statement.statement_branch_counts

            # Can't do anything with a single branch with statements.
            if len(branch_counts) == 1:
                return True

            empty_branches = set()
            for i, count in enumerate(branch_counts):
                if count > 0:
                    continue

                empty_branches.add(i)

            new_branches = [statement[0]]

            # We first delete empty branches in the middle of the block, as
            # these are not special and can be removed without much thought.
            for i in xrange(1, len(branch_counts)):
                if i not in empty_branches:
                    new_branches.append(statement[i])

            if len(new_branches) == 1:
                statement._groups = new_branches
                return True

            # An empty first branch is special. If the condition that follows
            # is a simple "else", we can invert the logic of the condition. If
            # the other branch has logic, we can just delete the first branch
            # outright.
            if 0 in empty_branches:
                following = new_branches[1][0]

                if isinstance(following, ElseCondition):
                    new_branches[0][0].expected = not new_branches[0][0].expected
                    new_branches[0][1][:] = new_branches[1][1]
                    del new_branches[1]
                else:
                    del new_branches[0]

            statement._groups = new_branches
            return True

        self._statements = filter(f, self._statements);

