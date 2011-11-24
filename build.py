#!/usr/bin/python
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

# This script is used to configure and build the Mozilla source tree.

import sys

# TODO these should magically come from the environment.
sys.path.append('build')
sys.path.append('build/pymake')
sys.path.append('other-licenses/ply')
sys.path.append('xpcom/idl-parser')

import buildparser.config
import buildparser.extractor
import buildparser.makefile
import json
import optparse
import os.path
import pymake.parser
import time

USAGE = '''Usage: %prog [options] [action]

Supported Actions:

      build  Performs all steps necessary to build the tree. This is what you
             will run most of the time and it is the default action.

  configure  Run autoconf and ensure your build environment is proper. This
             will be executed automatically as needed.

  makefiles  Perform generation of Makefiles. If Makefiles already exist, they
             will be overwritten. Makefile generation is influenced by a number
             of config options.

       wipe  Completely wipe your configured object directory.

        bxr  Create the Build Cross Reference HTML file describing the current
             build tree.'''

SUPPORTED_ACTIONS = (
    'build',
    'bxr',
    'configure',
    'makefiles',
    'wipe',
)

def get_option_parser():
    op = optparse.OptionParser()

    op_group_config = optparse.OptionGroup(op, 'Config File Options')
    op_group_config.add_option('--config-file', dest='config_file',
                               metavar='FILE',
                               help='Path to config file to load and/or save.')
    op_group_config.add_option('--no-save-config', dest='no_save_config',
                               action='store_true', default=False,
                               help='Do not save generated config file.')
    op.add_option_group(op_group_config)

    op_group_output = optparse.OptionGroup(op, 'Output Options')
    op_group_output.add_option(
        '-v', '--verbose', dest='verbose', action='store_true', default=False,
        help='Print verbose output. By default, builds are very silent.'
    )
    op_group_output.add_option(
        '--print-as-json', dest='print_json', action='store_true', default=False,
        help='Log machine-friendly JSON to STDOUT instead of human-friendly text'
    )
    op_group_output.add_option(
        '--forensic-log', dest='forensic_log', metavar='FILE',
        help='Path to write forensic, machine-readable log to'
    )
    op.add_option_group(op_group_output)

    op_group_bxr = optparse.OptionGroup(op, 'BXR Options')
    op_group_bxr.add_option(
        '--bxr-file', dest='bxr_file', metavar='FILE',
        default='./bxr.html',
        help='Path to write BXR to.'
    )
    op.add_option_group(op_group_bxr)

    op_group_debug = optparse.OptionGroup(op, 'Debugging and Power User Options')
    op_group_debug.add_option(
        '--print-makefile-statements', dest='print_makefile_statements',
        metavar='FILE', default=None,
        help='Print the PyMake parsed statement list from the specified file.'
    )
    op_group_debug.add_option(
        '--print-statementcollection', dest='print_statement_collection',
        metavar='FILE', default=None,
        help='Print the StatementCollection statement list for a Makefile.'
    )
    op_group_debug.add_option(
        '--print-reformatted-makefile',
        dest='print_reformatted_statements',
        metavar='FILE', default=None,
        help='Print a Makefile reformatted through the StatementCollection class.'
    )
    op_group_debug.add_option(
        '--print-pruned-makefile',
        dest='print_pruned_makefile',
        metavar='FILE', default=None,
        help='Print a Makefile pruned of false conditionals.'
    )
    op.add_option_group(op_group_debug)

    op.set_usage(USAGE)

    return op

op = get_option_parser()
(options, args) = op.parse_args()

action = 'build'

if len(args) > 0:
    if len(args) != 1:
        op.error('Unknown positional arguments')

    action = args[0]

if action not in SUPPORTED_ACTIONS:
    op.error('Unknown action: %s' % action)

# This is where the main functionality begins.
# TODO consider moving to a module.

start_time = time.time()

config_file = os.path.join(os.path.dirname(__file__), 'build_config.ini')

if options.config_file:
    config_file = options.config_file
elif 'MOZ_BUILD_CONFIG' in os.environ:
    config_file = os.environ['MOZ_BUILD_CONFIG']

forensic_handle = None
if options.forensic_log:
    forensic_handle = open(options.forensic_log, 'ab')

def action_callback(action, params, formatter, important=False, error=False):
    '''Our logging/reporting callback. It takes an enumerated string
    action, a dictionary of parameters describing that action, a
    formatting string for producing human readable text of that event,
    and some flags indicating if the message is important or represents
    an error.'''
    now = time.time()

    elapsed = now - start_time

    json_obj = [now, action, params]

    if forensic_handle is not None:
        json.dump(json_obj, forensic_handle)
        print >>forensic_handle, ''

    if options.verbose or important or error:
        if options.print_json:
            json.dump(json_obj, sys.stderr)
        else:
            print >>sys.stderr, '%4.2f %s' % ( elapsed, formatter.format(**params) )

config = buildparser.config.BuildConfig()

if os.path.exists(config_file):
    config.load_file(config_file)
    action_callback('config_load', {'file': config_file},
                    'Loaded existing config file: {file}',
                    important=True)
else:
    print 'Config file does not exist at %s\n. I will help you generate one!' % config_file
    config.run_commandline_wizard(os.path.abspath(os.path.dirname(__file__)),
                                  sys.stdout)

    if not options.no_save_config:
        config.save(config_file)
        action_callback('config_save', {'file': config_file},
                        'Saved config file to {file', important=True)

# Now that we have the config squared away, we start doing stuff.
bs = buildparser.extractor.BuildSystem(config, callback=action_callback)

other_action_taken = False

# The debug and power user options take precedence over explicit actions.
if options.print_makefile_statements is not None:
    statements = pymake.parser.parsefile(options.print_makefile_statements)
    statements.dump(sys.stdout, '')
    other_action_taken = True

if options.print_statement_collection is not None:
    statements = buildparser.makefile.StatementCollection(
        filename=options.print_statement_collection)

    for statement in statements.statements:
        print statement.debug_str

    other_action_taken = True

if options.print_reformatted_statements is not None:
    statements = buildparser.makefile.StatementCollection(
        filename=options.print_reformatted_statements)

    for line in statements.lines:
        print line

    other_action_taken = True

if options.print_pruned_makefile is not None:
    statements = buildparser.makefile.StatementCollection(
        filename=options.print_pruned_makefile
    )

    statements.strip_false_conditionals()

    for line in statements.lines:
        print line

    other_action_taken = True

if other_action_taken:
    exit(0)

if action == 'build':
    bs.build()
elif action == 'bxr':
    # We lazy import because we don't want a dependency on Mako. If that
    # package is every included with the source tree, we can change this.
    import buildparser.bxr
    with open(options.bxr_file, 'wb') as fh:
        buildparser.bxr.generate_bxr(config, fh)

elif action == 'configure':
    bs.configure()
elif action == 'makefiles':
    bs.generate_makefiles()
elif action == 'wipe':
    bs.wipe()

action_callback('finished', {}, 'Build action finished', important=True)