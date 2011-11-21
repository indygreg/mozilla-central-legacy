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

'''This file contains the critic classes.

A critic is an entity that analyzes something and issues complaints, or
critiques. Each complaint has a severity and metadata associated with it.
In the ideal world, the critics are always happy and they don't complain,
ever. In the real world, changes are made which upset the critics and they
get angry.

Critics exist to enforce best practices.
'''

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