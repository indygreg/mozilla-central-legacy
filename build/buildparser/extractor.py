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

# This file contains classes and methods used to extract metadata from the
# Mozilla build system.

from . import config
from . import data
from . import makefile

import hashlib
import os
import os.path
import re
import subprocess
import sys
import traceback
import xpidl

class BuildSystem(object):
    '''High-level interface to the build system.'''

    MANAGED_PATHS = (
        'js/src',
        'nsprpub',
    )

    # Ideally no paths should be ignored, but alas.
    IGNORED_PATHS = (
        # We ignore libffi because we have no way of producing the files from the
        # .in because configure doesn't give us an easily parseable file
        # containing the defines.
        'js/src/ctypes/libffi',
    )

    # Paths in object directory that are produced by configure. We keep
    # track of these paths and look for changes, etc.
    CONFIGURE_MANAGED_FILES = (
        'config/expandlibs_config.py',
        'config/autoconf.mk',
        'config/doxygen.cfg',
        'gfx/cairo/cairo/src/cairo-features.h',
        'js/src/config/autoconf.mk',
        'js/src/config/expandlibs_config.py',
        'js/src/config.status',
        'js/src/editline/Makefile',   # TODO why is this getting produced?
        'js/src/js-confdefs.h',
        'js/src/js-config',
        'js/src/js-config.h',
        'js/src/Makefile',            # TODO why is this getting produced
        'network/necko-config.h',
        'nsprpub/config/autoconf.mk',
        'nsprpub/config/nspr-config',
        'nsprpub/config/nsprincl.mk',
        'nsprpub/config/nsprincl.sh',
        'nsprpub/config.status',
        'xpcom/xpcom-config.h',
        'xpcom/xpcom-private.h',
        'config.status',
        'mozilla-config.h',
    )

    # Files produced by configure that we don't care about
    CONFIGURE_IGNORE_FILES = (
        'js/src/config.log',
        'js/src/unallmakefiles',
        'nsprpub/config.log',
        'config.cache',
        'config.log',
        'unallmakefiles',
    )

    CONFIGURE_IGNORE_DIRECTORIES = (
        'js/src/ctypes/libffi',
    )

    __slots__ = (
        # Mapping of identifiers to autoconf.mk data.Makefile instances
        'autoconfs',

        # Method that gets invoked any time an action is performed.
        'callback',

        # config.BuildConfig instance
        'config',

        # whether the object directory has been configured
        'is_configured',

        # Holds cached state for configure output
        'configure_state',
    )

    def __init__(self, conf, callback=None):
        '''Construct an instance from a source and target directory.'''
        assert(isinstance(conf, config.BuildConfig))
        self.config = conf
        self.callback = callback

        self.configure_state = {
            'files': {}
        }

        self.refresh_state()

    def build(self):
        if not self.is_configured:
            self.configure()

        # TODO make conditional
        self.generate_makefiles()

    def refresh_state(self):
        self.autoconfs = {}

        def get_variable_map(filename):
            d = {}

            statement = makefile.StatementCollection(filename=filename)
            for (name, value, token, conditional, location) in statement.variable_assignments:
                if conditional:
                    raise Exception('Conditional variable assignment encountered in autoconf file: %s' % location)

                if name in d:
                    if token not in ('=', ':='):
                        raise Exception('Variable assigned multiple times in autoconf file: %s' % name)

                d[name] = value

            return d

        self.is_configured = True

        for path in self.CONFIGURE_MANAGED_FILES:
            full = os.path.join(self.config.object_directory, path)

            # Construct defined variables from autoconf.mk files
            if path[-len('config/autoconf.mk'):] == 'config/autoconf.mk':
                if os.path.exists(full):
                    k = path[0:-len('config/autoconf.mk')].rstrip('/')
                    self.autoconfs[k] = get_variable_map(full)
                else:
                    self.is_configured = False

            if not os.path.exists(full) and path in self.configure_state['files']:
                raise Exception('File managed by configure has disappeared. Re-run configure: %s' % path)

            if os.path.exists(full):
                self.configure_state['files'][path] = {
                    'sha1': self._sha1_file_hash(full),
                    'mtime': os.path.getmtime(full),
                }

    def configure(self):
        '''Runs configure on the build system.'''

        # TODO regenerate configure's from configure.in's if needed

        # Create object directory if it doesn't exist
        if not os.path.exists(self.config.object_directory):
            self.run_callback('create_object_directory',
                              {'dir':self.config.object_directory},
                              'Creating object directory {dir}',
                              important=True)

            os.makedirs(self.config.object_directory)

        configure_path = os.path.join(self.config.source_directory, 'configure')

        env = {}
        for k, v in os.environ.iteritems():
            env[k] = v

        # We tell configure via an environment variable not to load a
        # .mozconfig
        env['IGNORE_MOZCONFIG'] = '1'

        # Tell configure scripts not to generate Makefiles, as we do that.
        env['DONT_GENERATE_MAKEFILES'] = '1'

        args = self.config.configure_args

        self.run_callback('configure_begin', {'args': args},
                          formatter='Starting configure: {args}',
                          important=True)

        p = subprocess.Popen(
            args,
            cwd=self.config.object_directory,
            executable=configure_path,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT
        )
        while True:
            for line in p.stdout:
                self.run_callback('configure_output', {'line': line.strip()},
                                  '{line}', important=False)

            if p.poll() is not None:
                break

        result = p.wait()

        if result != 0:
            self.run_callback('configure_error', {'resultcode': result},
                              'Configure Error: {resultcode}',
                              error=True)
        else:
            self.run_callback('configure_finish', {},
                              'Configure finished successfully',
                              important=True)

        self.refresh_state()

    def _find_input_makefiles(self):
        for root, dirs, files in os.walk(self.config.source_directory):
            # Filter out object directories inside the source directory
            if root[0:len(self.config.object_directory)] == self.config.object_directory:
                continue

            relative = root[len(self.config.source_directory)+1:]
            ignored = False

            for ignore in self.IGNORED_PATHS:
                if relative[0:len(ignore)] == ignore:
                    ignored = True
                    break

            if ignored:
                continue

            for name in files:
                if name == 'Makefile.in':
                    yield (relative, name)

    def generate_makefiles(self):
        '''Generate Makefile's into configured object tree.'''

        if not self.is_configured:
            self.configure()

        self.run_callback('generate_makefile_begin', {},
                          'Beginning generating of Makefiles',
                          important=True)

        # PyMake's cache only holds 15 items. We assume we have the resources
        # (because we are building m-c after all) and keep ALL THE THINGS in
        # memory.
        statements_cache = {}

        for (relative, path) in self._find_input_makefiles():
            try:
                full = os.path.join(self.config.source_directory, relative, path)

                statements_cache[full] = makefile.StatementCollection(filename=full)

                #autoconf = self._get_autoconf_for_file(relative)
                #self.generate_makefile(relative, path, translation_map=autoconf)
            except:
                self.run_callback(
                    'generate_makefile_exception',
                    {'path': os.path.join(relative, path), 'exception': traceback.format_exc()},
                    'Exception when generating Makefile {path}\n{exception}',
                    error=True)

        self.run_callback('generate_makefile_finish', {},
                          'Finished generation of Makefiles',
                          important=True)

    def generate_makefile(self, relative_path, filename, translation_map=None,
                          strip_false_conditionals=False, apply_rewrite=False):
        '''Generate a Makefile from an input file.

        Generation options can be toggled by presence of arguments:

          translation_map
              If defined as a dictionary, strings of form "@varname@" will be
              replaced by the value contained in the passed dictionary. If this
              argument is None (the default), no translation will occur.

          strip_false_conditionals
              If True, conditionals evaluated to false will be stripped from the
              Makefile. This implies apply_rewrite=True

          apply_rewrite
             If True, the Makefile will be rewritten from PyMake's parser
             output. This will lose formatting of the original file. However,
             the produced file should be functionally equivalent to the
             original. This argument likely has little use in normal
             operation. It is exposed to debug the functionality of the
             rewriting engine.
        '''
        if strip_false_conditionals:
            apply_rewrite = True

        input_path = os.path.join(self.config.source_directory, relative_path, filename)

        out_basename = filename
        if out_basename[-3:] == '.in':
            out_basename = out_basename[0:-3]

        output_path = os.path.join(self.config.object_directory,
                                   relative_path,
                                   out_basename)

        # Create output directory
        output_directory = os.path.dirname(output_path)

        if not os.path.exists(output_directory):
            os.makedirs(output_directory)
            self.run_callback('mkdir', {'dir': output_directory},
                              'Created directory: {dir}')

        managed_path = None
        for managed in self.MANAGED_PATHS:
            if relative_path[0:len(managed)] == managed:
                managed_path = managed
                break

        # We assume these will be calculated at least once b/c they
        # are common.
        top_source_directory = self.config.source_directory
        if managed_path is not None:
            top_source_directory = os.path.join(top_source_directory,
                                                managed_path)

        source_directory = os.path.join(self.config.source_directory,
                                        relative_path)

        sub_re = re.compile(r"@([a-z0-9_]+?)@")

        def perform_variable_translation(line):
            # Handle simple case of no substitution first
            if line.count('@') < 2:
                return line

            # Now we perform variable replacement on the line.
            newline = line
            for match in sub_re.finditer(line):
                variable = match.group(1)
                if variable == 'top_srcdir':
                    newline = newline.replace('@top_srcdir@', top_source_directory)
                elif variable == 'srcdir':
                    newline = newline.replace('@srcdir@', source_directory)
                else:
                    if variable not in translation_map:
                        # TODO warning
                        pass

                    value = translation_map.get(variable, '')
                    newline = newline.replace(match.group(0), value)

            return newline

        # We have two branches that perform outputting for performance reasons.
        # The rewrite branch reads files using PyMake. The simple branch reads
        # files manually. We don't perform them sequentially to save on the
        # redundant I/O.
        if apply_rewrite:
            raise Exception('Not implemented')
            m = makefile.Makefile(output_path)
            statements = [s for s in m.get_statements(expand_conditional=True)]
            with open(output_path, 'wb') as fh:
                m.write_statements_to_file(statements, fh)
        else:
            with open(input_path, 'r') as input:
                with open(output_path, 'wb') as output:
                    for line in input:
                        if translation_map is not None:
                            line = perform_variable_translation(line)

                        print >>output, line,

        self.run_callback(
            'generate_makefile_success',
            {'path': os.path.join(relative_path, out_basename)},
            'Generated Makefile {path}')

    def _get_autoconf_for_file(self, path):
        '''Obtain an autoconf file for a relative path.'''

        for managed in self.MANAGED_PATHS:
            if path[0:len(managed)] == managed:
                return self.autoconfs[managed]

        return self.autoconfs['']

    def _sha1_file_hash(self, filename):
        h = hashlib.sha1()
        with open(filename, 'rb') as fh:
            while True:
                data = fh.read(8192)
                if not data:
                    break

                h.update(data)

        return h.hexdigest()

    def run_callback(self, action, params, formatter,
                     important=False, error=False):
        if self.callback:
            self.callback(action, params, formatter,
                          important=important, error=error)

class ObjectDirectoryParser(object):
    '''A parser for an object directory.

    This holds state for a specific build instance. It is constructed from an
    object directory and gathers information from the files it sees.
    '''

    __slots__ = (
        'dir',                      # Directory data was extracted from.
        'parsed',
        'top_makefile',
        'top_source_dir',
        'retain_metadata',          # Boolean whether Makefile metadata is being
                                    # retained.
        'all_makefile_paths',       # List of all filesystem paths discovered
        'relevant_makefile_paths',  # List of all Makefiles relevant to our interest
        'ignored_makefile_paths',   # List of Makefile paths ignored
        'handled_makefile_paths',   # Set of Makefile paths which were processed
        'error_makefile_paths',     # Set of Makefile paths experiencing an error
                                    # during processing.
        'included_files',           # Dictionary defining which makefiles were
                                    # included from where. Keys are the included
                                    # filename and values are sets of paths that
                                    # included them.
        'variables',                # Dictionary holding details about variables.
        'ifdef_variables',          # Dictionary holding info on variables used
                                    # in ifdefs.
        'rules',                    # Dictionary of all rules encountered. Keys
                                    # Makefile paths. Values are lists of dicts
                                    # describing each rule.
        'unhandled_variables',

        'tree', # The parsed build tree
    )

    # Some directories cause PyMake to lose its mind when parsing. This is
    # likely due to a poorly configured PyMake environment. For now, we just
    # skip over these.
    # TODO support all directories.
    IGNORE_DIRECTORIES = [os.path.normpath(f) for f in [
        'accessible/src/atk', # non-Linux
        'build/win32',        # non-Linux
        'browser/app',
        'browser/installer',
        'browser/locales',   # $(shell) in global scope
        'js',
        'modules',
        'nsprpub',
        #'security/manager',
        'toolkit/content',
        'toolkit/xre',
        #'widget',
        'xpcom/reflect/xptcall',
    ]]

    SOURCE_DIR_MAKEFILES = [
        'config/config.mk',
        'config/rules.mk',
    ]

    def __init__(self, directory):
        '''Construct an instance from a directory.

        The given path must be absolute and must be a directory.
        '''
        if not os.path.isabs(directory):
            raise Exception('Path is not absolute: %s' % directory)

        if not os.path.isdir(directory):
            raise Exception('Path is not a directory: %s' % directory)

        self.dir = os.path.normpath(directory)
        self.parsed = False

        top_makefile_path = os.path.join(directory, 'Makefile')

        self.top_makefile = makefile.MozillaMakefile(top_makefile_path)
        self.top_source_dir = self.top_makefile.get_top_source_dir()

        # The following hold data once we are parsed.
        self.retain_metadata         = False
        self.all_makefile_paths      = None
        self.relevant_makefile_paths = None
        self.ignored_makefile_paths  = None
        self.handled_makefile_paths  = None
        self.error_makefile_paths    = None
        self.included_files          = {}
        self.unhandled_variables     = {}
        self.rules                   = {}
        self.variables               = {}
        self.ifdef_variables         = {}

    def load_tree(self, retain_metadata=False):
        '''Loads data from the entire build tree into the instance.'''

        self.retain_metadata = retain_metadata

        self.top_source_dir = self.top_makefile.get_variable_string('topsrcdir')

        # First, collect all the Makefiles that we can find.

        all_makefiles = set()

        for root, dirs, files in os.walk(self.dir):
            for name in files:
                if name == 'Makefile' or name[-3:] == '.mk':
                    all_makefiles.add(os.path.normpath(os.path.join(root, name)))

        # manually add other, special .mk files
        # TODO grab these automatically
        for path in self.SOURCE_DIR_MAKEFILES:
            all_makefiles.add(os.path.normpath(
                os.path.join(self.top_source_dir, path))
            )

        self.all_makefile_paths = sorted(all_makefiles)

        # Prune out the directories that have known problems.
        self.relevant_makefile_paths = []
        self.ignored_makefile_paths = []
        for path in self.all_makefile_paths:
            subpath = path[len(self.dir)+1:]

            relevant = True
            for ignore in self.IGNORE_DIRECTORIES:
                if subpath.find(ignore) == 0:
                    relevant = False
                    break

            if relevant:
                self.relevant_makefile_paths.append(path)
            else:
                self.ignored_makefile_paths.append(path)

        self.handled_makefile_paths = set()
        self.error_makefile_paths   = set()

        self.tree = data.TreeInfo()
        self.tree.object_directory = self.dir
        self.tree.top_source_directory = self.top_source_dir

        # Traverse over all relevant Makefiles
        for path in self.relevant_makefile_paths:
            try:
                self.load_makefile(path, retain_metadata=retain_metadata)
            except Exception, e:
                print 'Exception loading Makefile: %s' % path
                traceback.print_exc()
                self.error_makefile_paths.add(path)

        # Look for JAR Manifests in source directories and extract data from
        # them.
        for d in self.tree.source_directories:
            jarfile = os.path.normpath(os.path.join(d, 'jar.mn'))

            if os.path.exists(jarfile):
                self.tree.jar_manifests[jarfile] = self.parse_jar_manifest(jarfile)

        # Parse the IDL files.
        for m, d in self.tree.xpidl_modules.iteritems():
            for f in d['sources']:
                try:
                    filename = os.path.normpath(os.path.join(d['source_dir'], f))
                    self.tree.idl_sources[filename] = self.parse_idl_file(filename)
                except Exception, e:
                    print 'Error parsing IDL file: %s' % filename
                    print e

    def load_makefile(self, path, retain_metadata=False):
        '''Loads an indivudal Makefile into the instance.'''
        assert(os.path.normpath(path) == path)
        assert(os.path.isabs(path))

        self.handled_makefile_paths.add(path)
        m = makefile.MozillaMakefile(path)

        own_variables = set(m.get_own_variable_names(include_conditionals=True))

        if retain_metadata:
            self.collect_makefile_metadata(m)

        # We don't perform additional processing of included files. This
        # assumes that .mk means included, which appears to currently be fair.
        if path[-3:] == '.mk':
            return

        # prune out lowercase variables, which are defined as local
        lowercase_variables = set()
        for v in own_variables:
            if v.islower():
                lowercase_variables.add(v)

        used_variables = set()

        # We now register this Makefile with the monolithic data structure
        for obj in m.get_data_objects():
            used_variables |= obj.used_variables

            if obj.source_dir is not None:
                self.tree.source_directories.add(obj.source_dir)

            if isinstance(obj, data.XPIDLInfo):
                module = obj.module
                assert(module is not None)

                self.tree.xpidl_modules[module] = {
                    'source_dir': obj.source_dir,
                    'module':     module,
                    'sources':    obj.sources,
                }

                self.tree.idl_directories.add(obj.source_dir)

            elif isinstance(obj, data.ExportsInfo):
                for k, v in obj.exports.iteritems():
                    k = '/%s' % k

                    if k not in self.tree.exports:
                        self.tree.exports[k] = {}

                    for f in v:
                        #if f in v:
                        #    print 'WARNING: redundant exports file: %s (from %s)' % ( f, obj.source_dir )

                        search_paths = [obj.source_dir]
                        search_paths.extend(obj.vpath)

                        found = False

                        for path in search_paths:
                            filename = os.path.join(path, f)
                            if not os.path.exists(filename):
                                continue

                            found = True
                            self.tree.exports[k][f] = filename
                            break

                        if not found:
                            print 'Could not find export file: %s from %s' % ( f, obj.source_dir )

            elif isinstance(obj, data.LibraryInfo):
                name = obj.name

                if name in self.tree.libraries:
                    print 'WARNING: library already defined: %s' % name
                    continue

                def normalize_include(path):
                    if os.path.isabs(path):
                        return path

                    return os.path.normpath(os.path.join(obj.directory, path))

                includes = []
                for path in obj.includes:
                    includes.append(normalize_include(path))
                for path in obj.local_includes:
                    includes.append(normalize_include(path))

                self.tree.libraries[name] = {
                    'c_flags':     obj.c_flags,
                    'cpp_sources': obj.cpp_sources,
                    'cxx_flags':   obj.cxx_flags,
                    'defines':     obj.defines,
                    'includes':    includes,
                    'pic':         obj.pic,
                    'is_static':   obj.is_static,
                    'source_dir':  obj.source_dir,
                    'output_dir':  obj.directory,
                }

            elif isinstance(obj, data.MiscInfo):
                if obj.included_files is not None:
                    for path in obj.included_files:
                        v = self.included_files.get(path, set())
                        v.add(m.filename)
                        self.included_files[path] = v

        unused_variables = own_variables - used_variables - lowercase_variables
        for var in unused_variables:
            entry = self.unhandled_variables.get(var, set())
            entry.add(path)
            self.unhandled_variables[var] = entry

    def collect_makefile_metadata(self, m):
        '''Collects metadata from a Makefile into memory.'''
        assert(isinstance(m, makefile.MozillaMakefile))

        own_variables = set(m.get_own_variable_names(include_conditionals=True))
        own_variables_unconditional = set(m.get_own_variable_names(include_conditionals=False))

        for v in own_variables:
            if v not in self.variables:
                self.variables[v] = {
                    'paths':               set(),
                    'conditional_paths':   set(),
                    'unconditional_paths': set(),
                }

            info = self.variables[v]
            info['paths'].add(m.filename)
            if v in own_variables_unconditional:
                info['unconditional_paths'].add(m.filename)
            else:
                info['conditional_paths'].add(m.filename)

        for (name, expected, is_conditional, (path, line, column)) in m.statements.ifdefs:
            if name not in self.variables:
                self.variables[name] = {
                    'paths':               set(),
                    'conditional_paths':   set(),
                    'unconditional_paths': set(),
                }

            self.variables[name]['paths'].add(m.filename)

            if name not in self.ifdef_variables:
                self.ifdef_variables[name] = {}

            d = self.ifdef_variables[name]
            if m.filename not in d:
                d[m.filename] = []

            d[m.filename].append((expected, line))

        if m.filename not in self.rules:
            self.rules[m.filename] = []

        rules = self.rules[m.filename]

        for rule in m.statements.rules:
            rule['condition_strings'] = [m.condition_to_string(c) for c in rule['conditions']]
            rules.append(rule)

    def parse_jar_manifest(self, filename):
        '''Parse the contents of a JAR manifest filename into a data structure.'''

        # TODO hook into JarMaker.py to parse the JAR
        return {}

    def parse_idl_file(self, filename):
        idl_data = open(filename).read()
        p = xpidl.IDLParser()
        idl = p.parse(idl_data, filename=filename)

        # TODO it probably isn't correct to search *all* idl directories
        # because the same file may be defined multiple places.
        idl.resolve(self.tree.idl_directories, p)

        return {
            'filename':     filename,
            'dependencies': [os.path.normpath(dep) for dep in idl.deps],
        }

    def get_rules_for_makefile(self, path):
        '''Obtain all the rules for a Makefile at a path.'''

        if not self.retain_metadata:
            raise Exception('Metadata is not being retained. Refusing to proceed.')

        return self.rules.get(path, [])

    def get_target_names_from_makefile(self, path):
        '''Obtain a set of target names from a Makefile.'''
        if not self.retain_metadata:
            raise Exception('Metadata is not being retained. Refusing to proceed.')

        targets = set()

        for rule in self.rules.get(path, []):
            targets |= set(rule['targets'])

        return targets