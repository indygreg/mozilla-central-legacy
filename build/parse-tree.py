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

# This script parses a build tree and performs actions with the data.

import sys

sys.path.append('build/pymake')
sys.path.append('other-licenses/ply')
sys.path.append('xpcom/idl-parser')

import buildparser.extractor

from optparse import OptionParser
from sys import argv, exit
import uuid

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
  <head>
    <title>Build System Information</title>
  </head>
  <body>
    <h1>Build System Data</h1>
    <p>This document contains information about the build system.</p>

    <h1>Makefiles</h1>
    <p>This section documents the various Makefiles which were consulted to
    build this page.</p>

    <table border="1">
      <tr>
        <th>Path</th>
        <th>Relevant</th>
        <th>Success</th>
      </tr>
      % for path in sorted(makefile_paths):
        <tr>
          <td>${makefile_link(path)}</td>
          <td>${makefile_relevant(path)}</td>
          <td>${makefile_success(path)}</td>
        </tr>
      % endfor
    </table>

    <h2>Included Makefiles</h2>
    <p>The following Makefiles are included from others.</p>

    <table border="1">
      <tr>
        <th>Path</th>
        <th>Count</th>
      </tr>
      % for path, v in included_files.iteritems():
        <tr>
          <td>${path | h}</td>
          <td>${len(v)}</td>
        </tr>
      % endfor
    </table>

    <h2>Makefile Info</h2>
    <p>This section contains detailed information on every Makefile.</p>

    % for path in sorted(makefile_paths):
      <div id="${makefile_ids[path]}" class="makefile">
        <h4>${makefile_path(path) | h}</h4>
        <div>
          <strong>Source</strong>:
          <a href="${makefile_repo_link(path, 'hg') | h}">Mercurial</a>,
          <a href="${makefile_repo_link(path, 'github') | h}">GitHub</a>
        </div>
        % if len(makefile_rules[path]) > 0:
        <table border="1">
          <tr>
            <th>Target Name(s)</th>
            <th>Doublecolon</th>
            <th>Prerequisites</th>
            <th>Conditions</th>
          </tr>
          % for rule in makefile_rules[path]:
            <tr>
              <td><ul>
              % for target in rule['targets']:
                <li>${target | h}</li>
              % endfor
              </ul></td>

              % if rule['doublecolon']:
                  <td><strong>YES</strong</td>
              % else:
                  <td>No</td>
              % endif

              <td>
              % if len(rule['prerequisites']) > 0:
                <ul>
                % for prereq in rule['prerequisites']:
                  <li>${prereq | h}</li>
                % endfor
                </ul>
              % endif
              </td>

              <td>
              % if len(rule['condition_strings']) > 0:
                <ul>
                % for c in rule['condition_strings']:
                  <li>${c | h}</li>
                % endfor
                </ul>
              % endif
              </td>
            </tr>
          % endfor
        </table>
        % endif
      </div>
    % endfor

    <h1>Variables</h1>

    <h2>Variable List</h2>
    <p>The master list of all variables follows. These variables can appear in
    Makefiles or inside included .mk files.</p>

    <table border="1">
      <tr>
        <th>Name</th>
        <th>Makefile Count</th>
        <th>Support Count</th>
        <th>Used as Conditional</th>
      </tr>
      % for variable in sorted(variables.keys()):
        <tr>
          <td><a href="#${variable_ids[variable]}">${variable | h}</a></td>
          <td>${len(variables[variable]['paths'])}</td>
          <td>?</td>
          <td>?</td>
        </tr>
      % endfor
    </table>

    <h2>Variables by File Frequency</h2>
    <p>The following lists the number of Makefiles an individual variable occurs in.</p>

    <table border="1">
      <tr>
        <th>Variable</th>
        <th>Count</th>
      </tr>
      % for k, v in variables_by_makefile_count:
        <tr>
          <td><a href="#${variable_ids[k]}">${k | h}</a></td>
          <td>${v}</td>
        </tr>
      % endfor
    </table>

    <h2>Variable Info</h2>
    <p>Information about each encountered variable follows.</p>

    % for variable in sorted(variables.keys()):
      <div id="${variable_ids[variable]}" class="variable">
        <h4>${variable | h}</h4>
        <div><strong>Makefiles</strong>:
          ${', '.join(makefile_link(p) for p in variables[variable]['paths'])}
        </div>

        % if len(variables[variable]['unconditional_paths']) > 0:
        <div><strong>Unconditional Makefiles</strong>:
          ${', '.join(makefile_link(p) for p in variables[variable]['unconditional_paths'])}
        </div>
        % endif

        % if len(variables[variable]['conditional_paths']) > 0:
        <div><strong>Conditional Makefiles</strong>:
          ${', '.join(makefile_link(p) for p in variables[variable]['conditional_paths'])}
        </div>
        % endif

      </div>
    % endfor

    <h2>Variables Used in Conditionals</h2>
    <p>The following variables are used as part of evaluating a conditional.</p>
    <p>TODO.</p>
  </body>
</html>

<%def name="makefile_relevant(path)">
    % if path in relevant_makefile_paths:
        YES
    % else:
        <strong>NO</strong>
    % endif
</%def>

<%def name="makefile_success(path)">
    % if path in error_makefile_paths:
        <strong>No</strong>
    % else:
        Yes
    % endif
</%def>

<%def name="makefile_path(path)", buffered="True">
    <% objdir = tree.object_directory %>
    % if path[0:len(objdir)] == objdir:
        ${path[len(objdir)+1:]}
    % else:
        ${path}
    % endif
</%def>

<%def name="makefile_link(path)", buffered="True">
    <% id = makefile_ids[path] %>
    <a href="#${id}">${makefile_path(path) | h}</a>
</%def>

<%def name="makefile_repo_link(path, flavor)", buffered="True">
    <%
    objdir = tree.object_directory
    newpath = path
    if path[0:len(objdir)] == objdir:
        newpath = path[len(objdir)+1:]

    if newpath[-8:] == 'Makefile':
        newpath += '.in'

    base = None

    if flavor == 'hg':
        base = 'https://hg.mozilla.org/mozilla-central/file/default/'
    elif flavor == 'github':
        base = 'https://github.com/doublec/mozilla-central/blob/master/'
    else:
        raise 'Unknown flavor: %s' % flavor

    uri = base + newpath
    %>
    ${uri}
</%def>
'''

op = OptionParser(usage='usage: %prog [options] /path/to/objdir/')
op.add_option('--print-variable-counts', dest='print_variable_counts',
              action='store_true', help='Print counts of seen variable names')
op.add_option('--print-unhandled-variables', dest='print_unhandled_variables',
              action='store_true',
              help='Print information on unhandle variables')
op.add_option('--print-included-file-count', dest='print_include_count',
              help='Print counts of which files are included',
              action='store_true')
op.add_option('--generate-html', dest='generate_html',
              action='store', metavar='FILE',
              help='Create an HTML file describing the parsed build system.')


(options, args) = op.parse_args()

if len(args) != 1:
    print 'Path not specified'
    exit(1)

path = args[0]

parser = buildparser.extractor.ObjectDirectoryParser(path)
parser.load_tree(retain_metadata=True)

if options.print_unhandled_variables:
    l = sorted(parser.unhandled_variables.iteritems(), key=lambda(k, v):
            (len(v), k))
    for k, v in l:
        print '%s\t%s' % ( len(v), k)

if options.print_variable_counts:
    for k, v in sorted(parser.variables.iteritems(), key=lambda(k, v):
        (len(v['paths']), k)):
        print '%s\t%s' % ( len(v['paths']), k )

if options.print_include_count:
    l = sorted(parser.included_files.iteritems(), key=lambda(k, v):
            (len(v), k))
    for k, v in l:
        print '%s\t%s' % ( len(v), k )

if options.generate_html:
    # We don't import mako until now so we don't introduce a package
    # dependency.
    import mako
    import mako.template

    variable_ids = {}
    for name in parser.variables.keys():
        variable_ids[name] = str(uuid.uuid4())

    makefile_ids = {}
    for path in parser.all_makefile_paths:
        makefile_ids[path] = str(uuid.uuid4())

    variables_by_makefile_count = [(k, len(v['paths'])) for (k, v) in
                                    sorted(parser.variables.iteritems(),
                                          reverse=True,
                                          key=lambda(k, v): (len(v['paths']), k)
                                    )]

    makefile_target_names = {}
    makefile_rules = {}
    for path in parser.all_makefile_paths:
        makefile_target_names[path] = parser.get_target_names_from_makefile(path)
        makefile_rules[path] = parser.get_rules_for_makefile(path)

    with open(options.generate_html, 'w') as fh:
        try:
            t = mako.template.Template(HTML_TEMPLATE)
            print >>fh, t.render(
                makefile_paths=parser.all_makefile_paths,
                makefile_ids=makefile_ids,
                makefile_target_names=makefile_target_names,
                makefile_rules=makefile_rules,
                relevant_makefile_paths=parser.relevant_makefile_paths,
                error_makefile_paths=parser.error_makefile_paths,
                included_files=parser.included_files,
                tree=parser.tree,
                variables=parser.variables,
                variable_ids=variable_ids,
                variables_by_makefile_count=variables_by_makefile_count
            )
        except:
            print mako.exceptions.text_error_template().render()