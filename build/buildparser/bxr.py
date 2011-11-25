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

# This file contains functionality for the Build Cross Reference (BXR) tool.

from . import config
from . import extractor

import hashlib
import mako
import mako.template
import uuid

# This is our mako HTML template. Scroll down to see which variables are
# available.
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
  <head>
    <title>BXR - Build Cross Reference</title>
  </head>
  <body>
    <h1>Build Cross Reference</h1>
    <p>This document contains information about the build system.</p>

    <section id="index">
    <h1>Index</h1>
    <ul>
      <li><a href="#makefiles">Makefiles</a></li>
      <li><a href="#variables">Variables</a></li>
      <li><a href="#targets">Targets</a></li>
    </ul>
    </section>

    <section id="makefiles">
    <h1>Makefiles</h1>
    <p>This section documents the various Makefiles which were consulted to
    build this page.</p>

    <table border="1">
      <tr>
        <th>Path</th>
        <th>Relevant</th>
        <th>Success</th>
      </tr>
      % for path in sorted(makefiles.keys()):
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
      % for path, v in includes.iteritems():
        <tr>
          <td>${path | h}</td>
          <td>${len(v)}</td>
        </tr>
      % endfor
    </table>

    <h2>Makefile Info</h2>
    <p>This section contains detailed information on every Makefile.</p>

    % for path in sorted(makefiles.keys()):
      <% makefile = makefiles[path] %>
      <div id="${makefile['id']}" class="makefile">
        <h4>${makefile_path(path) | h}</h4>
        <div>
          <strong>Source</strong>:
          <a href="${makefile_repo_link(path, 'hg') | h}">Mercurial</a>,
          <a href="${makefile_repo_link(path, 'github') | h}">GitHub</a>
        </div>
        % if len(makefile['rules']) > 0:
        <table border="1">
          <tr>
            <th>Target Name(s)</th>
            <th>Doublecolon</th>
            <th>Prerequisites</th>
            <th>Conditions</th>
          </tr>
          % for rule in makefile['rules']:
            <tr>
              <td>${rule['target'] | h}
              <a href="${makefile_repo_link(path, 'hg', rule['line']) | h}">HG</a> |
              <a href="${makefile_repo_link(path, 'github', rule['line']) | h}">GitHub</a>
              </td>

              % if rule['doublecolon']:
                  <td><strong>YES</strong</td>
              % else:
                  <td>No</td>
              % endif

              <td>${rule['prerequisites'] | h}</td>

              <td>
              % if len(rule['conditions']) > 0:
                <ul>
                % for c in rule['conditions']:
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
    </section>

    <section id="variables">
    <h1>Variables</h1>

    <h2>Variable List</h2>
    <p>The master list of all variables follows. These variables can appear in
    Makefiles or inside included .mk files.</p>

    <table border="1">
      <tr>
        <th>Name</th>
        <th>Makefile Count</th>
        <th>Used as Conditional</th>
      </tr>
      % for name in sorted(variables.keys()):
        <% variable = variables[name] %>
        <tr>
          <td><a href="#${variable['id']}">${name | h}</a></td>
          <td>${len(variable['set_paths'])}</td>
          <td>
          ?
          ##% if variable in ifdef_variables:
          ##  <strong>Yes</strong>
          ##% else:
          ##  No
          ##% endif
          </td>
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
          <td><a href="#${variables[k]['id']}">${k | h}</a></td>
          <td>${v}</td>
        </tr>
      % endfor
    </table>

    <h2>Variable Info</h2>
    <p>Information about each encountered variable follows.</p>

    % for name in sorted(variables.keys()):
      <% variable = variables[name] %>
      <div id="${variable['id']}" class="variable">
        <h4>${name | h}</h4>

        <table border="1">
          <tr>
            <th>Makefile</th>
            <th>Used as ifdef</th>
            <th>Defined Conditionally</th>
            <th>Utilized</th>
          </tr>
          % for path in sorted(variable['set_paths']):
          <tr>
            <td>${makefile_link(path)}</td>
            <td>
            ?
            ##% if variable in ifdef_variables and path in ifdef_variables[variable]:
            ##  <strong>Yes</strong>
            ##% else:
            ##  No
            ##% endif
            </td>
            <td>
            ?
            ##% if path in variables[variable]['conditional_paths']:
            ##  <strong>Yes</strong>
            ##% else:
            ##  No
            ##% endif
            </td>
            <td>?</td>
          </tr>
          % endfor
        </table>
      </div>
    % endfor

    <h2>Variables Used in Conditionals</h2>
    <p>The following variables are used as part of evaluating a conditional.</p>
    <table border="1">
      <tr>
        <th>Name</th>
        <th># Makefiles</th>
      </tr>
      ##% for var in sorted(ifdef_variables.keys()):
      ##<tr>
      ##  <td><a href="#${variable_ids[var]}">${var | h}</td>
      ##  <td>${len(ifdef_variables[var].keys())}</td>
      ##</tr>
      ##% endfor
    </table>
    </section>

    <section id="targets">
      <h1>Targets</h1>
      <table border="1">
        <tr>
          <th>Target</th>
          <th>Makefiles</th>
        </tr>
        % for target in sorted(targets.keys()):
          <% data = targets[target] %>
          <tr>
            <td>${target | h}</td>
            <td>
              % if len(data['paths']) > 0:
                <ul>
                % for path in sorted(data['paths']):
                  <li>${makefile_link(path)}</li>
                % endfor
                </ul>
              % endif
            </td>
          </tr>
        % endfor
      </table>
    </section>
  </body>
</html>

<%def name="makefile_relevant(path)">
    ?
    ##% if path in relevant_makefile_paths:
    ##    YES
    ##% else:
    ##    <strong>NO</strong>
    ##% endif
</%def>

<%def name="makefile_success(path)">
    ?
    ##% if path in error_makefile_paths:
    ##    <strong>No</strong>
    ##% else:
    ##    Yes
    ##% endif
</%def>

<%def name="makefile_path(path)", buffered="True">
    <% objdir = object_directory %>
    % if path[0:len(objdir)] == objdir:
        ${path[len(objdir)+1:]}
    % else:
        ${path}
    % endif
</%def>

<%def name="makefile_link(path)", buffered="True">
    <% id = makefiles[path]['id'] %>
    <a href="#${id}">${makefile_path(path) | h}</a>
</%def>

<%def name="makefile_repo_link(path, flavor, line=None)", buffered="True">
    <%
    objdir = object_directory
    newpath = path
    if path[0:len(objdir)] == objdir:
        newpath = path[len(objdir)+1:]

    if newpath[-8:] == 'Makefile':
        newpath += '.in'

    uri = None

    if flavor == 'hg':
        uri = 'https://hg.mozilla.org/mozilla-central/file/default/%s' % newpath

        if line is not None:
            uri += '#l%s' % line
    elif flavor == 'github':
        uri = 'https://github.com/doublec/mozilla-central/blob/master/%s' % newpath

        if line is not None:
            uri += '#L%s' % line
    else:
        raise 'Unknown flavor: %s' % flavor
    %>
    ${uri}
</%def>
"""

def generate_bxr(conf, fh):
    """Generate the BXR HTML and write to the specified file handle."""
    assert(isinstance(conf, config.BuildConfig))

    bse = extractor.BuildSystemExtractor(conf)
    bse.load_all_object_directory_makefiles()

    makefiles = {} # Path to dictionary of metadata
    variables = {} # Name to dictionary of metadata
    targets = {}   # Expansion str to dictionary of metadata
    includes = {}  # Expansion str to list of tuples

    for m in bse.makefiles.makefiles():
        key = m.filename
        statements = m.statements
        metadata = makefiles.get(key, None)
        if metadata is None:
            metadata = {
                'id': hashlib.sha1(key).hexdigest(),
                'rules': [],
                'pattern_rules': [],
                'includes': [],
            }

        for statement, conditions, name, value, type in statements.variable_assignments():
            vdata = variables.get(name, None)
            if vdata is None:
                vdata = {
                    'id': hashlib.sha1(name).hexdigest(),
                    'set_paths': set(),
                }

            vdata['set_paths'].add(key)
            variables[name] = vdata

        for statement, conditions, target, prerequisites, commands in statements.rules():
            target_str = str(target)
            metadata['rules'].append({
                'target': target_str,
                'conditions': [str(c) for c in conditions],
                'prerequisites': str(prerequisites),
                'commands': commands,
                'line': statement.location.line,
                'doublecolon': statement.has_doublecolon,
            })

            for targ in target.split():
                target_data = targets.get(targ, None)
                if target_data is None:
                    target_data = {
                        'id': hashlib.sha1(target_str).hexdigest(),
                        'paths': set(),
                    }

                target_data['paths'].add(key)
                targets[targ] = target_data

        for statement, conditions, target, pattern, prerequisites, commands in statements.static_pattern_rules():
            metadata['pattern_rules'].append((
                str(target),
                conditions,
                str(pattern),
                prerequisites,
                commands
            ))

        for statement, conditions, path in statements.includes():
            s = str(path)

            metadata['includes'].append((s, conditions, statement.required, statement.location))

            include = includes.get(s, [])
            include.append((s, conditions, statement.required, statement.location))
            includes[s] = include

        makefiles[key] = metadata

    variables_by_file_count = [(k, len(v['set_paths'])) for (k, v) in
                               sorted(variables.iteritems(),
                                      reverse=True,
                                      key=lambda(k, v): (len(v['set_paths']), k)
                               )]

    try:
        t = mako.template.Template(HTML_TEMPLATE)
        print >>fh, t.render(
            source_directory=conf.source_directory,
            object_directory=conf.object_directory,
            makefiles=makefiles,
            variables=variables,
            targets=targets,
            includes=includes,
            variables_by_makefile_count=variables_by_file_count
        )
    except:
        print >>fh, mako.exceptions.html_error_template().render()
        raise Exception('Error when rendering template. See file for full error.')