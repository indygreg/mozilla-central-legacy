#!/usr/bin/python
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

# This file contains functionality for the Build Cross Reference (BXR) tool.

import hashlib
import mako
import mako.template
import uuid

from mozbuild.frontend.frontend import BuildFrontend

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
      <li><a href="#commands">Commands</a></li>
      <li><a href="#shell">Shell Invocations</a></li>
      <li><a href="#filesystem">Filesystem Statements</a></li>
    </ul>
    </section>

    <section id="makefiles">
    <h1>Makefiles</h1>
    <p>This section documents the various Makefiles which were consulted to
    build this page.</p>

    <table border="1">
      <tr>
        <th>Path</th>
        <th>Rules</th>
        <th>Pattern Rules</th>
        <th>Doublecolon Rules</th>
      </tr>
      % for path in sorted(makefiles.keys()):
        <% makefile = makefiles[path] %>
        <tr>
          <td>${makefile_link(path)}</td>
          <td>${len(makefile['rules'])}</td>
          <td>${len(makefile['pattern_rules'])}</td>
          <td>${makefile['doublecolon_count']}</td>
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
            <th>Commands</th>
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
              % if len(rule['conditions']) > 0:
                <ul>
                % for c in rule['conditions']:
                  <li>${c | h}</li>
                % endfor
                </ul>
              % endif
              </td>

              <td>
                % for command in rule['commands']:
                  ${command.lstrip()}<br />
                % endfor
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
      <caption>Variable File Counts</caption>
      <tr>
        <th>Name</th>
        <th>Set</th>
        <th>Referenced</th>
        <th>Used in ifdef</th>
      </tr>
      % for name in sorted(variables.keys()):
        <% variable = variables[name] %>
        <tr>
          <td>
            <a href="#${variable['id']}">${name | h}</a>
            <small>${mxr_link(name, '(MXR)')}</small></td>
          <td>${len(variable['set_paths'])}</td>
          <td>${len(variable['referenced_paths'])}</td>
          <td>${len(variable['ifdef_paths'])}</td>
        </tr>
      % endfor
    </table>

    <h2>Variables by File Frequency</h2>
    <table border="1">
      <caption>Variables by File Frequency</caption>
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

    <h2>Variables Used in ifdefs</h2>
    <table border="1">
      <caption>Variables used in ifdefs</caption>
      <tr>
        <th>Name</th>
        <th># Makefiles</th>
      </tr>
      % for name in sorted(variables.keys()):
        <% variable = variables[name] %>
        % if len(variable['ifdef_paths']) > 0:
          <tr>
            <td><a href="#${variable['id']}">${name | h}</a></td>
            <td>${len(variable['ifdef_paths'])}</td>
          </tr>
        % endif
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
            <th>Set</th>
            <th>Referenced</th>
            <th>Used as ifdef</th>
          </tr>
          % for path in sorted(variable['all_paths']):
          <tr>
            <td>${makefile_link(path)}</td>
            <td>
              % if path in variable['set_paths']:
                Yes
              % else:
                No
              % endif
            </td>
            <td>
              % if path in variable['referenced_paths']:
                Yes
              % else:
                No
              % endif
            </td>
            <td>
              % if path in variable['ifdef_paths']:
                Yes
              % else:
                No
              % endif
            </td>
          </tr>
          % endfor
        </table>
      </div>
    % endfor
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

    <section id="commands">
      <h1>Commands</h1>
      <table border="1">
        <tr>
          <th>Command</th>
          <th>Makefile(s)</th>
        </tr>
        % for command in sorted(commands.keys()):
          <% data = commands[command] %>
          <tr>
            <td>${command | h}</td>
            <td>
              % if len(data['used_paths']) > 0:
                <ul>
                  % for path in sorted(data['used_paths']):
                    <li>${makefile_link(path)}</li>
                  % endfor
                </ul>
              % endif
            </td>
          </tr>
        % endfor
      </table>
    </section>

    <section id="shell">
      <h1>Shell Invocations</h1>
      <table border="1">
        <caption>Listing of shell invocations in Makefiles</caption>
        <tr>
          <th>File</th>
          <th>Statement</th>
        </tr>
        % for path in sorted(shell_statements.keys()):
          % for statement in shell_statements[path]:
            <tr>
              <td>${makefile_link(path)}</td>
              <td><pre>${statement[0] | h}</pre></td>
            </tr>
          % endfor
        % endfor
      </table>
    </section>

    <section id="filesystem">
      <h1>Filesystem Statements</h1>
      <table border="1">
        <caption>Listing of make statements dependent on filesystem</caption>
        <tr>
          <th>File</th>
          <th>Statement</th>
        </tr>
        % for path in sorted(filesystem_statements.keys()):
          % for statement in filesystem_statements[path]:
            <tr>
              <td>${makefile_link(path)}</td>
              <td><pre>${statement[0] | h}</pre></td>
            </tr>
          % endfor
        % endfor
      </table>
    </section>
  </body>
</html>

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
        uri = 'https://github.com/mozilla/mozilla-central/blob/master/%s' % newpath

        if line is not None:
            uri += '#L%s' % line
    else:
        raise 'Unknown flavor: %s' % flavor
    %>
    ${uri}
</%def>

<%def name="mxr_link(term, text)", buffered="True">
  <a href="https://mxr.mozilla.org/mozilla-central/search?string=${term | h}&amp;case=on">${text | h}</a>
</%def>
"""

def generate_bxr(config, fh, load_all=False, load_from_make=False):
    """Generate the BXR HTML and write to the specified file handle."""
    frontend = BuildFrontend(config)

    if load_all:
        frontend.load_all_input_files()
    elif load_from_make:
        frontend.load_input_files_from_root_makefile()
    else:
        frontend.load_autoconf_input_files()

    def get_variable_value(name):
        return {
            'id':               hashlib.sha1(name).hexdigest(),
            'set_paths':        set(),
            'ifdef_paths':      set(),
            'referenced_paths': set(),
        }

    makefiles = {}             # Path to dictionary of metadata
    variables = {}             # Name to dictionary of metadata
    targets = {}               # Expansion str to dictionary of metadata
    includes = {}              # Expansion str to list of tuples
    commands = {}              # Expansion str to dictionary of metadata
    shell_statements = {}      # Path to list of tuples
    filesystem_statements = {} # Path to list of tuples

    for m in frontend.makefiles.makefiles():
        key = m.filename

        if key.startswith(config.source_directory):
            key = key[len(config.source_directory) + 1:]

        statements = m.statements
        metadata = makefiles.get(key, None)
        if metadata is None:
            metadata = {
                'id':                    hashlib.sha1(key).hexdigest(),
                'rules':                 [],
                'pattern_rules':         [],
                'includes':              [],
                'doublecolon_count':     0,
                'shell_statements':      [],
                'filesystem_statements': [],
            }

        for statement, conditions, name, value, type in statements.variable_assignments():
            vdata = variables.get(name, None)
            if vdata is None:
                vdata = get_variable_value(name)

            vdata['set_paths'].add(key)
            variables[name] = vdata

        for statement, conditions, target, prerequisites, cmds in statements.rules():
            target_str = str(target)
            metadata['rules'].append({
                'target': target_str,
                'conditions': [str(c) for c in conditions],
                'prerequisites': prerequisites.split(),
                'commands': [str(c) for c in cmds],
                'line': statement.location.line,
                'doublecolon': statement.has_doublecolon,
            })

            metadata['doublecolon_count'] += 1

            for targ in target.split():
                target_data = targets.get(targ, None)
                if target_data is None:
                    target_data = {
                        'id': hashlib.sha1(target_str).hexdigest(),
                        'paths': set(),
                    }

                target_data['paths'].add(key)
                targets[targ] = target_data

            for command in cmds:
                cmd = command.command_name
                if cmd is not None:
                    command_data = commands.get(cmd, None)
                    if command_data is None:
                        command_data = {
                            'id': hashlib.sha1(cmd).hexdigest(),
                            'used_paths': set(),
                        }

                    command_data['used_paths'].add(key)
                    commands[cmd] = command_data

        for statement, conditions, target, pattern, prerequisites, cmds in statements.static_pattern_rules():
            metadata['pattern_rules'].append((
                str(target),
                conditions,
                str(pattern),
                prerequisites,
                cmds
            ))

            metadata['doublecolon_count'] += 1

        for statement, conditions, path in statements.includes():
            s = str(path)

            metadata['includes'].append((s, conditions, statement.required, statement.location))

            include = includes.get(s, [])
            include.append((s, conditions, statement.required, statement.location))
            includes[s] = include

        for statement, conditions, name, expected in statements.ifdefs():
            vdata = variables.get(name, None)
            if vdata is None:
                vdata = get_variable_value(name)

            vdata['ifdef_paths'].add(key)
            variables[name] = vdata

        for expansion in statements.variable_references():
            name = str(expansion)
            vdata = variables.get(name, None)
            if vdata is None:
                vdata = get_variable_value(name)

            vdata['referenced_paths'].add(key)
            variables[name] = vdata

        for statement, conditions in statements.shell_dependent_statements():
            t = (str(statement), statement.location.line)
            metadata['shell_statements'].append(t)

            sdata = shell_statements.get(key, [])
            sdata.append(t)
            shell_statements[key] = sdata

        for statement, conditions in statements.filesystem_dependent_statements():
            t = (str(statement), statement.location.line)
            metadata['filesystem_statements'].append(t)

            sdata = filesystem_statements.get(key, [])
            sdata.append(t)
            filesystem_statements[key] = sdata

        makefiles[key] = metadata

    for k, v in variables.iteritems():
        v['all_paths'] = v['set_paths'] | v['ifdef_paths'] | v['referenced_paths']

    variables_by_file_count = [(k, len(v['all_paths'])) for (k, v) in
                               sorted(variables.iteritems(),
                                      reverse=True,
                                      key=lambda(k, v): (len(v['all_paths']), k)
                               )]

    try:
        t = mako.template.Template(HTML_TEMPLATE)
        print >>fh, t.render(
            source_directory=config.source_directory,
            object_directory=config.object_directory,
            makefiles=makefiles,
            variables=variables,
            targets=targets,
            includes=includes,
            commands=commands,
            shell_statements=shell_statements,
            filesystem_statements=filesystem_statements,
            variables_by_makefile_count=variables_by_file_count
        )
    except:
        print >>fh, mako.exceptions.html_error_template().render()
        raise Exception('Error when rendering template. See file for full error.')
